"""
Earnings calendar using Alpha Vantage EARNINGS_CALENDAR endpoint.

Free tier: counts against 25 req/day quota. Cached for 24 hours.
Returns upcoming earnings dates for tracked tickers.
"""

import csv
import io
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

AV_BASE = "https://www.alphavantage.co/query"
CACHE_TTL = 86_400  # 24 hours — earnings dates rarely change
_cache: dict[str, tuple[float, list]] = {}


def _cache_get(key: str) -> Optional[list]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, data: list) -> None:
    _cache[key] = (time.time(), data)


def _days_until(date_str: str) -> Optional[int]:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (d - date.today()).days
    except Exception:
        return None


def get_earnings_calendar(tickers: list[str]) -> list[dict]:
    """
    Fetch upcoming earnings dates for the given tickers (next 3 months).
    Returns list sorted by reportDate ascending.
    """
    if not tickers or not settings.alpha_vantage_key:
        return []

    tickers_upper = [t.upper() for t in tickers if t]
    cache_key = "earnings:" + ",".join(sorted(tickers_upper))

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    results = []
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(AV_BASE, params={
                "function": "EARNINGS_CALENDAR",
                "horizon": "3month",
                "apikey": settings.alpha_vantage_key,
            })
            r.raise_for_status()
            # Response is CSV
            reader = csv.DictReader(io.StringIO(r.text))
            ticker_set = set(tickers_upper)
            for row in reader:
                sym = (row.get("symbol") or "").upper()
                if sym not in ticker_set:
                    continue
                report_date = row.get("reportDate") or ""
                days = _days_until(report_date)
                results.append({
                    "ticker": sym,
                    "company": row.get("name") or sym,
                    "report_date": report_date,
                    "fiscal_date_ending": row.get("fiscalDateEnding") or "",
                    "estimate": row.get("estimate") or None,
                    "days_until": days,
                    "is_upcoming": days is not None and days >= 0,
                })

        results.sort(key=lambda x: x["report_date"])
        _cache_set(cache_key, results)
        logger.info(f"Earnings calendar: {len(results)} entries for {tickers_upper}")
    except Exception as e:
        logger.warning(f"Earnings calendar fetch failed: {e}")

    return results


def next_earnings(ticker: str) -> Optional[dict]:
    """Return the next upcoming earnings entry for a single ticker."""
    all_earnings = get_earnings_calendar([ticker])
    upcoming = [e for e in all_earnings if e.get("is_upcoming")]
    return upcoming[0] if upcoming else None
