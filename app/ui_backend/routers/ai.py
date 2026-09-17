"""AI-generated research summaries (Claude / Gemini / OpenAI, chosen in Settings)."""

import hmac
import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from config import settings
from database import get_db

router = APIRouter(prefix="/ai", tags=["ai"])

# Tight enough to catch garbage and abuse, loose enough for real tickers
# (incl. multi-class shares like BRK.B and exchange suffixes like RY.TO).
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

# ── Per-IP rate limiter for the unauth read path ───────────────────────────────
# Even with input validation, a tight loop hitting valid tickers (AAPL, MSFT,
# NVDA, ...) can force fresh Anthropic calls every time cache evicts. 20
# summaries/minute is plenty for a real user browsing tickers; abuse trips 429.
_AI_WINDOW   = 60
_AI_MAX_HITS = 20
_ai_hits: dict[str, deque] = defaultdict(deque)


def _check_ai_rate(request: Request):
    from routers.access import _get_ip  # local import to avoid cycle
    ip = _get_ip(request)
    now = time.time()
    bucket = _ai_hits[ip]
    while bucket and now - bucket[0] > _AI_WINDOW:
        bucket.popleft()
    if len(bucket) >= _AI_MAX_HITS:
        raise HTTPException(429, detail="Too many AI summary requests. Try again in a minute.")
    bucket.append(now)
    if len(_ai_hits) > 500:
        for k in [k for k, v in list(_ai_hits.items()) if not v]:
            del _ai_hits[k]


def _visitor_cred(request: Request):
    """A visitor's own key, if the browser sent one. Headers are set by the
    frontend from localStorage; nothing here is persisted or logged."""
    from services.providers import Credential, PROVIDERS
    provider = (request.headers.get("X-AI-Provider") or "").strip().lower()
    key = (request.headers.get("X-AI-Key") or "").strip()
    model = (request.headers.get("X-AI-Model") or "").strip() or None
    if not provider or not key:
        return None
    if provider not in PROVIDERS or len(key) > 512 or (model and len(model) > 100):
        raise HTTPException(status_code=400, detail="Invalid AI provider settings.")
    return Credential(provider=provider, key=key, model=model)


@router.get("/status")
def ai_status():
    from services.providers import active_provider, LABELS, model_for
    active = active_provider()
    return {
        "configured": active is not None,
        "provider": active,
        "label": LABELS.get(active) if active else None,
        "model": model_for(active) if active else None,
    }


@router.get("/summary/{ticker}")
def stock_summary(
    request: Request,
    ticker: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
    x_admin_token: str | None = Header(default=None),
):
    """Bull/bear research note for a ticker. Cached 6h; pass refresh=true to regenerate (admin only)."""
    # Validate BEFORE any cache lookup or external call — `ticker` flows into
    # the Anthropic prompt and cache key, so unbounded input is both an abuse
    # vector and a cost-amplification path.
    ticker = (ticker or "").upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker. Expected 1-10 chars: A-Z, 0-9, '.', '-'.")
    _check_ai_rate(request)
    cred = _visitor_cred(request)
    # A visitor with their own key pays for the regeneration, so they may force it.
    if refresh and cred is None:
        from routers.access import _make_token
        expected = _make_token(settings.admin_password)
        if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
            raise HTTPException(status_code=403, detail="Admin token required to force-refresh AI summaries.")
    from services.ai_summary import generate_stock_summary
    return generate_stock_summary(ticker, db, force=refresh, cred=cred)


@router.post("/test")
def test_own_key(request: Request):
    """Connectivity check for the key the visitor pasted in Settings."""
    _check_ai_rate(request)
    cred = _visitor_cred(request)
    if cred is None:
        raise HTTPException(status_code=400, detail="Send X-AI-Provider and X-AI-Key.")
    from services.providers import test_provider
    ok, message = test_provider(cred.provider, cred)
    return {"provider": cred.provider, "ok": ok, "message": message}


@router.get("/models")
def own_models(request: Request):
    """Models available to the visitor's own key, from the provider's live list."""
    _check_ai_rate(request)
    cred = _visitor_cred(request)
    if cred is None:
        raise HTTPException(status_code=400, detail="Send X-AI-Provider and X-AI-Key.")
    from services.providers import list_models
    try:
        return list_models(cred.provider, cred.key)
    except Exception as e:  # noqa: BLE001 — surfaced to the settings UI
        raise HTTPException(status_code=502, detail=str(e)[:200])
