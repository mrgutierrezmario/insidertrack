"""
Earnings calendar endpoints.
Backed by Alpha Vantage EARNINGS_CALENDAR (free tier, cached 24 hours).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from typing import Optional

from database import get_db
from models.watchlist import WatchlistItem
from services.earnings_fetcher import get_earnings_calendar, next_earnings
from services.tickers import tracked_tickers as _tracked_tickers  # re-exported for back-compat

router = APIRouter(prefix="/earnings", tags=["earnings"])


@router.get("/")
def earnings_for_tracked(email: Optional[str] = None, db: Session = Depends(get_db)):
    """Upcoming earnings for tracked politician tickers, optionally merged with watchlist."""
    tickers = _tracked_tickers(db)
    if email:
        watchlist_tickers = [
            w.ticker for w in db.query(WatchlistItem).filter(WatchlistItem.email == email.lower().strip()).all()
        ]
        tickers = sorted(set(tickers) | set(watchlist_tickers))
    all_earnings = get_earnings_calendar(tickers)
    upcoming = [e for e in all_earnings if e.get("is_upcoming")]
    past = [e for e in all_earnings if not e.get("is_upcoming")]
    return {
        "tickers": tickers,
        "has_key": bool(__import__("config").settings.alpha_vantage_key),
        "upcoming": upcoming,
        "recent": past[-5:] if past else [],
    }


@router.get("/{ticker}")
def earnings_for_ticker(ticker: str):
    """Next earnings date for a single ticker."""
    result = next_earnings(ticker.upper())
    return result or {"ticker": ticker.upper(), "message": "No upcoming earnings found or AV key not configured"}
