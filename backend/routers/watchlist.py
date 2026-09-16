"""
Per-visitor watchlist, authenticated by a bearer token bound to the visitor's
email. The token is minted on the first POST /watchlist/ for a new email and
returned exactly once; subsequent reads and mutations must present it in the
`Authorization: Bearer <token>` header. Lost tokens are recovered via
POST /watchlist/recover, which emails the address a freshly minted token.

This replaces the prior "?email=<email>" lookup, where knowing the email was
enough to read or modify someone's watchlist.
"""

import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.watchlist import WatchlistItem, WatchlistOwner

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────

class WatchIn(BaseModel):
    email: str
    ticker: str
    note: str | None = None


class RecoverIn(BaseModel):
    email: str


# ── Email normalization ───────────────────────────────────────────────────────

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()


# ── Token helpers ─────────────────────────────────────────────────────────────

def _mint_token() -> str:
    """Generate a fresh URL-safe bearer token. ~43 chars, 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _extract_token(request: Request) -> str | None:
    """Pull bearer token from Authorization header (preferred) or X-Watchlist-Token."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    fallback = request.headers.get("x-watchlist-token", "").strip()
    return fallback or None


def _require_owner(request: Request, email: str, db: Session) -> WatchlistOwner:
    """
    Verify the bearer token in `request` matches the stored hash for `email`.
    Raises 400/401/403 on failure. Updates last_used_at on success.
    """
    email = _norm_email(email)
    if not email:
        raise HTTPException(400, detail="email is required")
    token = _extract_token(request)
    if not token:
        raise HTTPException(401, detail="Watchlist token required.")
    owner = db.query(WatchlistOwner).filter(WatchlistOwner.email == email).first()
    if not owner or not owner.token_hash:
        # No owner row, or seeded row from the migration with an empty hash:
        # the user needs to claim/recover before any token will work.
        raise HTTPException(
            401,
            detail="Watchlist token required. If you've used this watchlist "
                   "before, request a new token via /watchlist/recover.",
        )
    if not hmac.compare_digest(_hash_token(token), owner.token_hash):
        raise HTTPException(403, detail="Watchlist token does not match this email.")
    owner.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return owner


# ── Rate limiters ─────────────────────────────────────────────────────────────
# GET endpoints: 30/min/IP — defence-in-depth on top of the token check.
# Recovery: 3/hour/IP — recovery sends an email; tight cap discourages spamming
# someone else's inbox.

_GET_WINDOW   = 60
_GET_MAX_HITS = 30
_get_hits: dict[str, deque] = defaultdict(deque)

_RECOVER_WINDOW   = 3600
_RECOVER_MAX_HITS = 3
_recover_hits: dict[str, deque] = defaultdict(deque)

# Per-email throttle on top of the per-IP one — prevents a distributed
# attacker (cycling IPs) from spamming a victim's inbox with recovery emails.
_RECOVER_EMAIL_WINDOW   = 3600
_RECOVER_EMAIL_MAX_HITS = 3
_recover_email_hits: dict[str, deque] = defaultdict(deque)


def _check_recover_email_rate(email: str):
    """Per-email recovery throttle. Silent (no 429) — recovery returns 200
    regardless to avoid leaking whether a hit was rate-limited vs unknown
    email vs delivered. Returns True if the send should proceed."""
    now = time.time()
    bucket = _recover_email_hits[email]
    while bucket and now - bucket[0] > _RECOVER_EMAIL_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RECOVER_EMAIL_MAX_HITS:
        return False
    bucket.append(now)
    if len(_recover_email_hits) > 500:
        for k in [k for k, v in list(_recover_email_hits.items()) if not v]:
            del _recover_email_hits[k]
    return True


def _check_rate(bucket_map: dict[str, deque], window: int, max_hits: int, request: Request, label: str):
    from routers.access import _get_ip  # local import to avoid cycle
    ip = _get_ip(request)
    now = time.time()
    bucket = bucket_map[ip]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= max_hits:
        raise HTTPException(429, detail=f"Too many {label} requests. Try again later.")
    bucket.append(now)
    if len(bucket_map) > 500:
        for k in [k for k, v in list(bucket_map.items()) if not v]:
            del bucket_map[k]


def _check_get_rate(request: Request):
    _check_rate(_get_hits, _GET_WINDOW, _GET_MAX_HITS, request, "watchlist")


def _check_recover_rate(request: Request):
    _check_rate(_recover_hits, _RECOVER_WINDOW, _RECOVER_MAX_HITS, request, "recovery")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def get_watchlist(
    request: Request,
    email: str = Query(...),
    db: Session = Depends(get_db),
):
    _check_get_rate(request)
    _require_owner(request, email, db)
    email = _norm_email(email)
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.email == email)
        .order_by(WatchlistItem.created_at.desc())
        .all()
    )
    return [
        {
            "id": i.id,
            "ticker": i.ticker,
            "note": i.note,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in items
    ]


@router.get("/signals")
def watchlist_with_signals(
    request: Request,
    email: str = Query(...),
    db: Session = Depends(get_db),
):
    """Watchlist enriched with current composite signal scores and 7-day price change."""
    _check_get_rate(request)
    _require_owner(request, email, db)
    email = _norm_email(email)
    items = db.query(WatchlistItem).filter(WatchlistItem.email == email).all()
    tickers = {i.ticker for i in items}
    if not tickers:
        return []

    signal_by_ticker: dict[str, dict] = {}
    try:
        from routers.signals import technical_signals
        for s in technical_signals(db).get("signals", []):
            signal_by_ticker[s["ticker"]] = s
    except Exception:
        pass

    # 7-day return per ticker using cached price history
    change_by_ticker: dict[str, float | None] = {}
    try:
        from services.market_data import get_price_history
        for ticker in tickers:
            try:
                hist = get_price_history(ticker, days=12)
                if len(hist) >= 2:
                    latest = hist[-1]["close"]
                    target = (date.today() - timedelta(days=7)).isoformat()
                    ref_bar = next((h for h in reversed(hist[:-1]) if h["date"] <= target), hist[0])
                    old_price = ref_bar["close"]
                    change_by_ticker[ticker] = round((latest - old_price) / old_price * 100, 1)
            except Exception:
                change_by_ticker[ticker] = None
    except Exception:
        pass

    out = []
    for i in items:
        s = signal_by_ticker.get(i.ticker, {})
        out.append({
            "id": i.id,
            "ticker": i.ticker,
            "note": i.note,
            "composite_score": s.get("composite_score"),
            "label": s.get("label"),
            "signal": s.get("signal"),
            "current_price": s.get("current_price"),
            "price_7d_change": change_by_ticker.get(i.ticker),
        })
    out.sort(key=lambda x: x["composite_score"] or -1, reverse=True)
    return out


@router.post("/")
def add_to_watchlist(
    body: WatchIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Add a ticker to the watchlist.

    First call for a new email mints the bearer token and returns it once as
    `token` in the response — the client must store it. Subsequent calls
    require the token in `Authorization: Bearer <token>`.
    """
    email = _norm_email(body.email)
    ticker = (body.ticker or "").upper().strip()
    if not email or not ticker:
        raise HTTPException(400, detail="email and ticker are required")

    owner = db.query(WatchlistOwner).filter(WatchlistOwner.email == email).first()
    minted_token: str | None = None
    if owner is None:
        # First time this email has been used → mint and return the token.
        minted_token = _mint_token()
        owner = WatchlistOwner(email=email, token_hash=_hash_token(minted_token))
        db.add(owner)
        db.flush()
    elif not owner.token_hash:
        # Seeded migration row (existing watchlist user from before tokens existed):
        # accept the add but force them through the recovery flow for reads/deletes.
        # We mint a fresh token here so the client gets it without needing recovery.
        minted_token = _mint_token()
        owner.token_hash = _hash_token(minted_token)
    else:
        # Established owner → require the token before mutating.
        _require_owner(request, email, db)

    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.email == email, WatchlistItem.ticker == ticker)
        .first()
    )
    if existing:
        if body.note is not None:
            existing.note = body.note
        owner.last_used_at = datetime.now(timezone.utc)
        db.commit()
        resp = {"id": existing.id, "ticker": ticker, "status": "already_watching"}
    else:
        item = WatchlistItem(email=email, ticker=ticker, note=body.note)
        db.add(item)
        owner.last_used_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)
        resp = {"id": item.id, "ticker": ticker, "status": "added"}

    if minted_token:
        resp["token"] = minted_token
    return resp


@router.delete("/{item_id}", status_code=204)
def remove_from_watchlist(
    item_id: int,
    request: Request,
    email: str = Query(default=""),
    db: Session = Depends(get_db),
):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise HTTPException(404, detail="Watchlist item not found")
    # Token must match the email on the item — not the one in the query
    # (otherwise a caller could send their own token + somebody else's id).
    _require_owner(request, item.email, db)
    if _norm_email(email) and _norm_email(email) != item.email:
        # Belt-and-braces: if the client did pass an email, it must agree with the row.
        raise HTTPException(403, detail="Email does not match this watchlist item.")
    db.delete(item)
    db.commit()


@router.post("/recover")
def recover_watchlist_token(
    body: RecoverIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Rotate the bearer token for `email` and send the new value to that
    inbox. Returns 200 whether or not the email exists (avoid email
    enumeration); the actual delivery is observable only by the address owner.
    """
    _check_recover_rate(request)
    email = _norm_email(body.email)
    if not email:
        raise HTTPException(400, detail="email is required")

    owner = db.query(WatchlistOwner).filter(WatchlistOwner.email == email).first()
    # If the email has watchlist items but no owner row (shouldn't happen post-migration,
    # but defensive), seed the owner here.
    if owner is None:
        has_items = db.query(WatchlistItem).filter(WatchlistItem.email == email).first()
        if not has_items:
            # No record of this email — return 200 anyway to avoid enumeration.
            return {"status": "ok"}
        owner = WatchlistOwner(email=email, token_hash="")
        db.add(owner)
        db.flush()

    # Per-email throttle: don't rotate the token or send an email if this
    # address has already received N recovery emails in the window. Returns
    # 200 silently either way so the response leaks nothing about the throttle.
    if not _check_recover_email_rate(email):
        return {"status": "ok"}

    new_token = _mint_token()
    owner.token_hash = _hash_token(new_token)
    owner.last_used_at = datetime.now(timezone.utc)
    db.commit()

    # Best-effort email send. We do not surface delivery failures to the client.
    try:
        from services.email_sender import send_simple_email
        import html as _html
        # `new_token` is from secrets.token_urlsafe — already HTML-safe, but escape
        # defensively in case the implementation ever changes.
        body = (
            "<p>You requested a new watchlist access token for InsiderTrack.</p>"
            f"<p><strong>Token:</strong> <code>{_html.escape(new_token)}</code></p>"
            "<p>Paste it into the InsiderTrack watchlist page to regain access. "
            "Any prior token for this email is now invalid.</p>"
            "<p>If you did not request this, you can ignore this email — your "
            "watchlist data has not been disclosed.</p>"
        )
        send_simple_email("InsiderTrack — watchlist access token", body, [email])
    except Exception:
        logger.exception("Failed to send watchlist recovery email to %s", email)

    return {"status": "ok"}
