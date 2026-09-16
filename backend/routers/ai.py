"""AI-generated research summaries (Anthropic Claude)."""

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


@router.get("/status")
def ai_status():
    return {"configured": bool(settings.anthropic_api_key)}


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
    if refresh:
        from routers.access import _make_token
        expected = _make_token(settings.admin_password)
        if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
            raise HTTPException(status_code=403, detail="Admin token required to force-refresh AI summaries.")
    from services.ai_summary import generate_stock_summary
    return generate_stock_summary(ticker, db, force=refresh)
