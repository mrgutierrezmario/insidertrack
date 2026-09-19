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


# ── Member skill factor ───────────────────────────────────────────────────────
SKILL_MIN_TRADES = 10       # fewer measured buys → factor stays 1.0
SKILL_WINDOW = "90"         # the window the factor reads from


def skill_factor(beat_spy_rate: Optional[float], n: int) -> float:
    """Map a 90-day beat-SPY rate (%) to a 0.5–1.5 weight. 50% (a coin flip)
    is 1.0; the mapping is linear so a member who beats SPY 70% of the time
    counts 1.4× and one at 30% counts 0.6×. Too few trades → 1.0."""
    if beat_spy_rate is None or n < SKILL_MIN_TRADES:
        return 1.0
    return round(0.5 + max(0.0, min(100.0, beat_spy_rate)) / 100.0, 2)


SKILL_JOB_KEY = "job:skill_refresh"


def _job_flag(db: Session, key: str, value: Optional[str]) -> None:
    """Set/clear a 'running' marker in app_settings so deploy/start.sh can see
    a job that runs outside the web process (docker exec)."""
    from models.app_setting import AppSetting
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if value is None:
            if row:
                db.delete(row)
        elif row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
        db.commit()
    except Exception:
        db.rollback()


def refresh_skill(db: Session, span_days: int = 1200) -> dict:
    """Weekly: recompute every member's track record and store the factor.
    One price series per ticker at a fixed span so all members share the
    cache; slow (thousands of tickers) but it runs off-hours."""
    from models.politician import Politician
    from models.trade import Trade
    ids = [pid for (pid,) in db.query(Trade.politician_id).filter(Trade.direction == "buy").distinct().all()]
    _job_flag(db, SKILL_JOB_KEY, date.today().isoformat() + "T" + __import__("time").strftime("%H:%M:%S"))
    updated = 0
    try:
        return _refresh_skill_members(db, ids, span_days)
    finally:
        _job_flag(db, SKILL_JOB_KEY, None)


def _refresh_skill_members(db: Session, ids: list[int], span_days: int) -> dict:
    from models.politician import Politician
    updated = 0
    for pid in ids:
        try:
            rec = compute_track_record(db, pid, force=True, span_days=span_days)
        except Exception as exc:
            logger.warning(f"skill refresh: member {pid} failed: {exc}")
            continue
        w = rec["windows"].get(SKILL_WINDOW) or {}
        n = int(w.get("n") or 0)
        rate = w.get("beat_spy_rate")
        p = db.query(Politician).filter(Politician.id == pid).first()
        if not p:
            continue
        p.skill_factor = skill_factor(rate, n)
        p.skill_n = n
        p.skill_beat_spy = rate
        p.skill_as_of = date.today()
        updated += 1
        db.commit()
    logger.info(f"Skill refresh: {updated} member(s) updated")
    return {"members": updated}


def compute_track_record(db: Session, politician_id: int, force: bool = False,
                         span_days: Optional[int] = None) -> dict:
    key = f"track_record:{politician_id}:v2"
    if not force:
        hit = cache_get(key)
        if hit:
            return hit[0]

    today = date.today()
    base = (
        db.query(Trade)
        .filter(
            Trade.politician_id == politician_id,
            Trade.asset_type == "stock",
            Trade.ticker.isnot(None),
            Trade.disclosure_date.isnot(None),
            Trade.disclosure_date <= today - timedelta(days=WINDOWS[0]),
        )
        .order_by(Trade.disclosure_date.desc())
    )
    buys = base.filter(Trade.direction == "buy").limit(MAX_TRADES).all()
    sells = base.filter(Trade.direction == "sell").limit(MAX_TRADES).all()
    result: dict = {"politician_id": politician_id, "windows": {}, "trades": [], "evaluated": 0, "skipped_demo": 0,
                    "sells": {"windows": {}, "trades": [], "evaluated": 0}}
    if not buys and not sells:
        cache_set(key, result, CACHE_TTL)
        return result

    # One history per ticker, long enough for its oldest disclosure.
    oldest = min(t.disclosure_date for t in buys + sells)
    span = span_days or _bucket((today - oldest).days + 10)
    tickers = sorted({t.ticker for t in buys + sells})

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

    def measure(trades: list) -> tuple[list[dict], int]:
        rows, demo = [], 0
        for t in trades:
            hist = histories.get(t.ticker) or []
            if not hist or hist[-1].get("_demo"):
                demo += 1
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
        return rows, demo

    def summarise(rows: list[dict], good_when_negative: bool = False) -> dict:
        """Per-window aggregates. For sells a *negative* return/excess is the
        good outcome (the stock went down after they sold), so 'win' and
        'beat SPY' flip sign; averages are reported as-is."""
        out = {}
        sign = -1 if good_when_negative else 1
        for w in WINDOWS:
            rs = [r[f"r{w}"] for r in rows if r[f"r{w}"] is not None]
            xs = [r[f"x{w}"] for r in rows if r[f"x{w}"] is not None]
            out[str(w)] = {
                "n": len(rs),
                "avg_return": round(mean(rs), 2) if rs else None,
                "median_return": round(median(rs), 2) if rs else None,
                "win_rate": round(sum(1 for r in rs if sign * r > 0) / len(rs) * 100, 1) if rs else None,
                "avg_excess": round(mean(xs), 2) if xs else None,
                "beat_spy_rate": round(sum(1 for x in xs if sign * x > 0) / len(xs) * 100, 1) if xs else None,
            }
        return out

    rows, demo = measure(buys)
    result["skipped_demo"] += demo
    result["windows"] = summarise(rows)
    result["trades"] = rows
    result["evaluated"] = len(rows)

    sell_rows, demo = measure(sells)
    result["skipped_demo"] += demo
    result["sells"] = {"windows": summarise(sell_rows, good_when_negative=True),
                       "trades": sell_rows, "evaluated": len(sell_rows)}
    cache_set(key, result, CACHE_TTL)
    return result
