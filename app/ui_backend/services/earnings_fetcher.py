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


# ── Nasdaq's public calendar (keyless) ────────────────────────────────────────
# One request per calendar day: every company reporting that day, with the
# consensus EPS estimate. Cached per day in the persistent cache for 24 h so
# the ~60 business days ahead cost ~60 requests once a day, not per visitor.
NASDAQ_CALENDAR = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
CALENDAR_DAYS_AHEAD = 90
_DAY_TTL = 24 * 3600


def _nasdaq_day(client: httpx.Client, day: date) -> list[dict]:
    """All companies reporting on `day` → [{symbol, name, time, estimate, fiscal}]."""
    from services.persistent_cache import cache_get, cache_set
    key = f"earnings_day:{day.isoformat()}"
    hit = cache_get(key)
    if hit:
        return hit[0]
    r = client.get(NASDAQ_CALENDAR, params={"date": day.isoformat()}, headers=NASDAQ_HEADERS)
    if r.status_code != 200:
        return []
    rows = ((r.json().get("data") or {}).get("rows")) or []
    out = [{
        "symbol": (row.get("symbol") or "").upper(),
        "name": row.get("name") or "",
        "time": {"time-pre-market": "before open", "time-after-hours": "after close"}.get(row.get("time") or "", ""),
        "estimate": row.get("epsForecast") or None,
        "fiscal": row.get("fiscalQuarterEnding") or "",
    } for row in rows]
    cache_set(key, out, _DAY_TTL)
    return out


def _nasdaq_calendar(tickers_upper: list[str]) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    wanted = set(tickers_upper)
    results: list[dict] = []
    today = date.today()
    days = [today + timedelta(days=i) for i in range(CALENDAR_DAYS_AHEAD + 1) if (today + timedelta(days=i)).weekday() < 5]

    def fetch(day: date) -> tuple[date, list[dict]]:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                return day, _nasdaq_day(client, day)
        except Exception as exc:
            logger.warning(f"Nasdaq earnings calendar {day}: {exc}")
            return day, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        per_day = dict(pool.map(fetch, days))
    for day in days:
        i = (day - today).days
        for row in per_day.get(day) or []:
                if row["symbol"] in wanted:
                    results.append({
                        "ticker": row["symbol"], "company": row["name"] or row["symbol"],
                        "report_date": day.isoformat(), "fiscal_date_ending": row["fiscal"],
                        "estimate": row["estimate"], "time": row["time"],
                        "days_until": i, "is_upcoming": True, "source": "nasdaq",
                    })
    return results


def warm_calendar() -> int:
    """Daily: fetch every day of the calendar into the persistent cache so the
    page and the alert engine never pay for the walk."""
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        today = date.today()
        n = 0
        for i in range(CALENDAR_DAYS_AHEAD + 1):
            day = today + timedelta(days=i)
            if day.weekday() >= 5:
                continue
            try:
                n += len(_nasdaq_day(client, day))
            except Exception as exc:
                logger.warning(f"earnings warm {day}: {exc}")
    _cache.clear()   # the per-ticker-list L1 results are built from what we just refreshed
    logger.info(f"Earnings calendar warm: {n} reporting entries over {CALENDAR_DAYS_AHEAD} days")
    return n


def get_earnings_calendar(tickers: list[str]) -> list[dict]:
    """
    Upcoming earnings dates for the given tickers (next 3 months), sorted by
    date. Nasdaq's keyless calendar first; Alpha Vantage only if that yields
    nothing and a key is configured.
    """
    if not tickers:
        return []

    tickers_upper = [t.upper() for t in tickers if t]
    cache_key = "earnings:" + ",".join(sorted(tickers_upper))

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    results = _nasdaq_calendar(tickers_upper)
    if results:
        results.sort(key=lambda x: x["report_date"])
        _cache_set(cache_key, results)
        logger.info(f"Earnings calendar (Nasdaq): {len(results)} entries for {len(tickers_upper)} tickers")
        return results
    if not settings.alpha_vantage_key:
        _cache_set(cache_key, [])
        return []

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
