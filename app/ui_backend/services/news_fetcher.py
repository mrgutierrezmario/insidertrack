"""
News feed for tickers.

With an Alpha Vantage key: NEWS_SENTIMENT (headlines + a sentiment label;
free tier 25 req/day, 5/min, so it's cached 4 h and batched). Without one,
or when AV's quota is spent: Google News RSS — keyless headlines per ticker,
no sentiment (labelled "Headline"). Either way the composite score no longer
uses sentiment (scoring v2+); this feed is for reading.
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
        results = _google_news(tickers, limit)
        _cache_set(cache_key, results)
        return results

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
            results = _google_news(tickers, limit)
            _cache_set(cache_key, results)
            return results

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
                "provider": "alpha-vantage",
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
        results = _google_news(tickers, limit)
        _cache_set(cache_key, results)
        return results


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def _parse_rss_time(s: str) -> str:
    """'Fri, 19 Sep 2026 14:02:00 GMT' → ISO."""
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).isoformat()
    except Exception:
        return s


def _google_news(tickers: list[str], limit: int = 20) -> list[dict]:
    """Keyless headlines from Google News RSS, a few per ticker, newest
    first. No sentiment — every item is a plain "Headline"."""
    import xml.etree.ElementTree as ET
    per = max(3, limit // max(len(tickers), 1))
    out: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0 (InsiderTrack news reader)"}, follow_redirects=True) as client:
        for t in tickers:
            try:
                r = client.get(GOOGLE_NEWS_RSS, params={"q": f"{t} stock", "hl": "en-US", "gl": "US", "ceid": "US:en"})
                if r.status_code != 200:
                    continue
                root = ET.fromstring(r.text)
            except Exception as exc:
                logger.warning(f"Google News fetch failed for {t}: {exc}")
                continue
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not title or link in seen:
                    continue
                seen.add(link)
                src = item.find("source")
                out.append({
                    "title": title, "url": link,
                    "source": (src.text or "").strip() if src is not None else "",
                    "published": _parse_rss_time(item.findtext("pubDate") or ""),
                    "summary": "",
                    "overall_label": "Headline", "overall_score": None,
                    "overall_color": "#94a3b8", "sentiment_value": 50,
                    "provider": "google-news",
                    "tickers": [t], "ticker_sentiment": {},
                })
                if sum(1 for o in out if o["tickers"] == [t]) >= per:
                    break
    out.sort(key=lambda o: o["published"], reverse=True)
    return out[:limit]


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
