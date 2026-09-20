"""
News and sentiment endpoints.
Backed by Alpha Vantage NEWS_SENTIMENT (free tier, cached 4 hours).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from services.news_fetcher import get_news, average_sentiment
from services.tickers import tracked_tickers as _tracked_tickers  # re-exported for back-compat

NEWS_TICKERS = 10   # the source is called per ticker (Google News) or batched (AV); keep it to the ones that matter


def _news_tickers(db: Session) -> list[str]:
    """The tickers worth reading about: most-traded by members in the last
    30 days first, then the top current signals. Not the alphabetical head
    of every ticker ever traded (which is how this used to pick 'AA, AAGIY,
    AAL…')."""
    from datetime import date, timedelta
    from sqlalchemy import func
    from models.politician import Politician
    from models.trade import Trade
    cutoff = date.today() - timedelta(days=30)
    rows = (
        db.query(Trade.ticker, func.count(Trade.id))
        .join(Politician)
        .filter(Politician.is_tracked == True, Trade.trade_date >= cutoff, Trade.ticker.isnot(None))  # noqa: E712
        .group_by(Trade.ticker).order_by(func.count(Trade.id).desc()).limit(NEWS_TICKERS).all()
    )
    picked = [t for t, _ in rows]
    if len(picked) < NEWS_TICKERS:
        try:
            from routers.signals import technical_signals
            for s in technical_signals(db).get("signals", []):
                if s["ticker"] not in picked:
                    picked.append(s["ticker"])
                if len(picked) >= NEWS_TICKERS:
                    break
        except Exception:
            pass
    return picked

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/feed")
def news_feed(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Latest news for the tickers members are trading most right now."""
    tickers = _news_tickers(db)
    news = get_news(tickers, limit=limit)
    return {
        "tickers": tickers,
        "count": len(news),
        "has_key": bool(__import__("config").settings.alpha_vantage_key),
        "items": news,
    }


@router.get("/")
def ticker_news(
    tickers: str = Query(description="Comma-separated tickers, e.g. AAPL,NVDA"),
    limit: int = Query(default=20, le=50),
):
    """News for specific tickers."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    news = get_news(ticker_list, limit=limit)
    return {
        "tickers": ticker_list,
        "count": len(news),
        "has_key": bool(__import__("config").settings.alpha_vantage_key),
        "items": news,
    }
