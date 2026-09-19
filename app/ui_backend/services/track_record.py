"""
Per-member track record: how did a member's disclosed stock purchases do
at 30 / 60 / 90 days after the public could see them, and did they beat SPY?

Entry is the first close on or after the *disclosure* date (a follower
couldn't act before then). Returns are close-to-close; excess = return −
SPY over the same window. Only stock buys count (options and bonds have no
clean price path; sells are a separate question).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from statistics import mean, median
from typing import Optional

from sqlalchemy.orm import Session

from models.trade import Trade
from services.market_data import get_price_history
from services.persistent_cache import cache_get, cache_set

logger = logging.getLogger(__name__)

WINDOWS = (30, 60, 90)
MAX_TRADES = 300            # most recent evaluable buys per member
CACHE_TTL = 6 * 3600
# History is fetched in coarse buckets so many trades of one ticker share a
# cached series instead of each asking for its own day-count.
_BUCKETS = (200, 400, 800, 1200, 1600)


def _bucket(days: int) -> int:
    for b in _BUCKETS:
        if days <= b:
            return b
    return _BUCKETS[-1]


def _close_on_or_after(history: list[dict], target: date) -> Optional[tuple[date, float]]:
    for row in history:
        try:
            d = date.fromisoformat(row["date"])
        except Exception:
            continue
        if d >= target:
            return d, float(row["close"])
    return None


def _close_on_or_before(history: list[dict], target: date) -> Optional[float]:
    best = None
    for row in history:
        try:
            d = date.fromisoformat(row["date"])
        except Exception:
            continue
        if d <= target:
            best = float(row["close"])
        else:
            break
    return best


def _pct(a: float, b: float) -> float:
    return round((b - a) / a * 100, 2)


def compute_track_record(db: Session, politician_id: int, force: bool = False) -> dict:
    key = f"track_record:{politician_id}:v1"
    if not force:
        hit = cache_get(key)
        if hit:
            return hit[0]

    today = date.today()
    buys = (
        db.query(Trade)
        .filter(
            Trade.politician_id == politician_id,
            Trade.direction == "buy",
            Trade.asset_type == "stock",
            Trade.ticker.isnot(None),
            Trade.disclosure_date.isnot(None),
            Trade.disclosure_date <= today - timedelta(days=WINDOWS[0]),
        )
        .order_by(Trade.disclosure_date.desc())
        .limit(MAX_TRADES)
        .all()
    )
    result: dict = {"politician_id": politician_id, "windows": {}, "trades": [], "evaluated": 0, "skipped_demo": 0}
    if not buys:
        cache_set(key, result, CACHE_TTL)
        return result

    # One history per ticker, long enough for its oldest disclosure.
    oldest = min(t.disclosure_date for t in buys)
    span = _bucket((today - oldest).days + 10)
    tickers = sorted({t.ticker for t in buys})

    def fetch(tk: str) -> tuple[str, list[dict]]:
        try:
            return tk, get_price_history(tk, days=span)
        except Exception:
            return tk, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        histories = dict(pool.map(fetch, tickers + ["SPY"]))
    spy = histories.pop("SPY", [])
    if not spy or spy[-1].get("_demo"):
        logger.warning("track record: no SPY history — excess returns unavailable")
        spy = []

    rows = []
    for t in buys:
        hist = histories.get(t.ticker) or []
        if not hist or hist[-1].get("_demo"):
            result["skipped_demo"] += 1
            continue
        entry = _close_on_or_after(hist, t.disclosure_date)
        if not entry:
            continue
        entry_date, entry_px = entry
        spy_entry = _close_on_or_after(spy, t.disclosure_date) if spy else None
        row = {
            "trade_id": t.id, "ticker": t.ticker, "trade_date": t.trade_date.isoformat(),
            "disclosure_date": t.disclosure_date.isoformat(), "entry_date": entry_date.isoformat(),
            "entry_price": round(entry_px, 2), "amount_range": t.amount_range, "owner": t.owner,
        }
        for w in WINDOWS:
            target = entry_date + timedelta(days=w)
            if target > today:
                row[f"r{w}"] = None; row[f"x{w}"] = None
                continue
            px = _close_on_or_before(hist, target)
            r = _pct(entry_px, px) if px else None
            row[f"r{w}"] = r
            x = None
            if r is not None and spy_entry:
                spy_px = _close_on_or_before(spy, target)
                if spy_px:
                    x = round(r - _pct(spy_entry[1], spy_px), 2)
            row[f"x{w}"] = x
        rows.append(row)

    for w in WINDOWS:
        rs = [r[f"r{w}"] for r in rows if r[f"r{w}"] is not None]
        xs = [r[f"x{w}"] for r in rows if r[f"x{w}"] is not None]
        result["windows"][str(w)] = {
            "n": len(rs),
            "avg_return": round(mean(rs), 2) if rs else None,
            "median_return": round(median(rs), 2) if rs else None,
            "win_rate": round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1) if rs else None,
            "avg_excess": round(mean(xs), 2) if xs else None,
            "beat_spy_rate": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1) if xs else None,
        }
    result["trades"] = rows
    result["evaluated"] = len(rows)
    cache_set(key, result, CACHE_TTL)
    return result
