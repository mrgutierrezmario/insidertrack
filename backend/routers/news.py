"""
News and sentiment endpoints.
Backed by Alpha Vantage NEWS_SENTIMENT (free tier, cached 4 hours).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from services.news_fetcher import get_news, average_sentiment
from services.tickers import tracked_tickers as _tracked_tickers  # re-exported for back-compat

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/feed")
def news_feed(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Latest news for all tickers traded by tracked politicians."""
    tickers = _tracked_tickers(db)
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
