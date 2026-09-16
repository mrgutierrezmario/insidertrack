"""
News and sentiment feed using Alpha Vantage NEWS_SENTIMENT.

Free tier: 25 req/day, 5/min. We cache aggressively to stay within limits.
Falls back to empty list if AV key is not configured.
"""

import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

AV_BASE = "https://www.alphavantage.co/query"
CACHE_TTL = 14_400  # 4 hours — conserve AV quota
_cache: dict[str, tuple[float, list]] = {}


def _cache_get(key: str) -> Optional[list]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, data: list) -> None:
    _cache[key] = (time.time(), data)


def _parse_av_time(s: str) -> str:
    """Convert '20240501T120000' → '2024-05-01T12:00:00'"""
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%S").isoformat()
    except Exception:
        return s


SENTIMENT_COLORS = {
    "Bullish": "#4ade80",
    "Somewhat-Bullish": "#86efac",
    "Neutral": "#94a3b8",
    "Somewhat-Bearish": "#fb923c",
    "Bearish": "#f87171",
}


def _sentiment_score(label: str) -> int:
    return {
        "Bullish": 100,
        "Somewhat-Bullish": 70,
        "Neutral": 50,
        "Somewhat-Bearish": 30,
        "Bearish": 0,
    }.get(label, 50)


def get_news(tickers: list[str], limit: int = 20) -> list[dict]:
    """
    Fetch news + sentiment for a list of tickers.
    All tickers are batched into a single AV request to conserve quota.
    """
    if not tickers:
        return []

    # Normalize + deduplicate
    tickers = list({t.upper() for t in tickers if t})[:10]
    cache_key = "news:" + ",".join(sorted(tickers))

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not settings.alpha_vantage_key:
        return []

    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(AV_BASE, params={
                "function": "NEWS_SENTIMENT",
                "tickers": ",".join(tickers),
                "limit": str(min(limit, 50)),
                "apikey": settings.alpha_vantage_key,
            })
            r.raise_for_status()
            data = r.json()

        if "Note" in data or "Information" in data:
            logger.warning("AV rate limit or key issue: %s", data.get("Note") or data.get("Information"))
            return []

        feed = data.get("feed", [])
        results = []
        for item in feed:
            ticker_sentiments = {
                ts["ticker"]: ts
                for ts in (item.get("ticker_sentiment") or [])
            }
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
                "published": _parse_av_time(item.get("time_published", "")),
                "summary": item.get("summary", "")[:300],
                "overall_label": item.get("overall_sentiment_label", "Neutral"),
                "overall_score": round(float(item.get("overall_sentiment_score", 0)), 3),
                "overall_color": SENTIMENT_COLORS.get(item.get("overall_sentiment_label", ""), "#94a3b8"),
                "sentiment_value": _sentiment_score(item.get("overall_sentiment_label", "Neutral")),
                "tickers": list(ticker_sentiments.keys()),
                "ticker_sentiment": {
                    t: {
                        "label": ts.get("ticker_sentiment_label", "Neutral"),
                        "score": round(float(ts.get("ticker_sentiment_score", 0)), 3),
                        "relevance": round(float(ts.get("relevance_score", 0)), 3),
                    }
                    for t, ts in ticker_sentiments.items()
                },
            })

        _cache_set(cache_key, results)
        logger.info(f"AV news: fetched {len(results)} items for {tickers}")
        return results

    except Exception as e:
        logger.warning(f"News fetch failed: {e}")
        return []


def average_sentiment(tickers: list[str]) -> dict[str, float]:
    """
    Returns {ticker: avg_sentiment_score} (0-100) for the given tickers.
    Uses cached news data if available.
    """
    news = get_news(tickers)
    scores: dict[str, list[float]] = {t: [] for t in tickers}

    for item in news:
        for ticker, ts in (item.get("ticker_sentiment") or {}).items():
            if ticker in scores:
                scores[ticker].append(_sentiment_score(ts.get("label", "Neutral")))

    return {
        t: round(sum(v) / len(v)) if v else 50
        for t, v in scores.items()
    }
