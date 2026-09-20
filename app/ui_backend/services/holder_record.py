"""
Track records for 13F holders, on the same terms as the members and the AI
Desk: every NEW or INCREASED position measured from the day the filing
became public to 30/60/90 days later, against SPY; DECREASED / CLOSED
measured the same way with the sense flipped (a cut was a good call if the
stock then lagged). A fund's first loaded quarter ("initial") is skipped —
there is nothing to compare against.

The honest caveat, stated on the page: a 13F is a quarter-end snapshot that
becomes public up to 45 days later, so "the fund bought" is old news by the
time anyone can act on it. That's exactly why the record starts from the
filing date and not the quarter end.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from statistics import mean, median
from typing import Optional

from sqlalchemy.orm import Session

from models.whale import WhaleHolder, WhalePosition
from services.market_data import get_price_history
from services.persistent_cache import cache_get, cache_set
from services.track_record import WINDOWS, _bucket, _close_on_or_after, _close_on_or_before, _pct

logger = logging.getLogger(__name__)

CACHE_TTL = 12 * 3600
MAX_POSITIONS = 250          # newest first
BUY_TYPES = ("new", "increased")
SELL_TYPES = ("decreased", "closed")


def _measure(entries: list[dict], histories: dict, spy: list[dict], today: date) -> list[dict]:
    rows = []
    for e in entries:
        hist = histories.get(e["ticker"]) or []
        if not hist or hist[-1].get("_demo"):
            continue
        entry = _close_on_or_after(hist, e["public_on"])
        if not entry:
            continue
        entry_date, entry_px = entry
        spy_entry = _close_on_or_after(spy, e["public_on"]) if spy else None
        row = {**e, "entry_date": entry_date.isoformat(), "entry_price": round(entry_px, 2), "public_on": e["public_on"].isoformat()}
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
    return rows


def _summarise(rows: list[dict], good_when_negative: bool = False) -> dict:
    sign = -1 if good_when_negative else 1
    out = {}
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


def compute_holder_record(db: Session, holder_id: int, force: bool = False) -> dict:
    key = f"holder_record:{holder_id}:v2"
    if not force:
        hit = cache_get(key)
        if hit:
            return hit[0]
    today = date.today()
    positions = (
        db.query(WhalePosition)
        .filter(WhalePosition.holder_id == holder_id, WhalePosition.filed_on.isnot(None),
                WhalePosition.filed_on <= today - timedelta(days=WINDOWS[0]),
                WhalePosition.change_type.in_(BUY_TYPES + SELL_TYPES))
        .order_by(WhalePosition.filed_on.desc(), WhalePosition.value_usd.desc())
        .limit(MAX_POSITIONS)
        .all()
    )
    result: dict = {"holder_id": holder_id, "buys": {"windows": {}, "trades": [], "evaluated": 0},
                    "sells": {"windows": {}, "trades": [], "evaluated": 0}, "skipped_demo": 0}
    if not positions:
        cache_set(key, result, CACHE_TTL)
        return result
    # A 13F can list one ticker on several rows (share classes, sub-accounts);
    # the record is per ticker per filing, so keep the largest row only.
    seen: set = set()
    entries = []
    for p in positions:
        if (p.ticker, p.quarter) in seen:
            continue
        seen.add((p.ticker, p.quarter))
        entries.append({"position_id": p.id, "ticker": p.ticker, "company": p.company_name, "change": p.change_type,
                        "quarter": p.quarter, "value_usd": p.value_usd, "public_on": p.filed_on})
    oldest = min(e["public_on"] for e in entries)
    span = _bucket((today - oldest).days + 10)
    tickers = sorted({e["ticker"] for e in entries})

    def fetch(tk):
        try:
            return tk, get_price_history(tk, days=span)
        except Exception:
            return tk, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        histories = dict(pool.map(fetch, tickers + ["SPY"]))
    spy = histories.pop("SPY", [])
    if not spy or spy[-1].get("_demo"):
        spy = []

    buys = _measure([e for e in entries if e["change"] in BUY_TYPES], histories, spy, today)
    sells = _measure([e for e in entries if e["change"] in SELL_TYPES], histories, spy, today)
    result["buys"] = {"windows": _summarise(buys), "trades": buys, "evaluated": len(buys)}
    result["sells"] = {"windows": _summarise(sells, good_when_negative=True), "trades": sells, "evaluated": len(sells)}
    result["skipped_demo"] = len(entries) - len(buys) - len(sells)
    cache_set(key, result, CACHE_TTL)
    return result


def holder_leaderboard(db: Session) -> list[dict]:
    """Every tracked holder's beat-SPY rate on new/increased positions, at
    the longest window that has data yet (90 → 60 → 30 days; a fresh filing
    only has 30-day numbers for its first two months). Reads the per-holder
    cache; holders never computed show as pending rather than blocking."""
    out = []
    for h in db.query(WhaleHolder).filter(WhaleHolder.is_tracked == True).all():  # noqa: E712
        hit = cache_get(f"holder_record:{h.id}:v2")
        rec = hit[0] if hit else None
        windows = (rec or {}).get("buys", {}).get("windows", {})
        window, w = None, None
        for cand in ("90", "60", "30"):
            if windows.get(cand, {}).get("n"):
                window, w = int(cand), windows[cand]
                break
        out.append({"id": h.id, "name": h.name, "computed": rec is not None, "window": window,
                    "n": (w or {}).get("n"), "beat_spy_rate": (w or {}).get("beat_spy_rate"), "avg_excess": (w or {}).get("avg_excess")})
    out.sort(key=lambda r: (r["beat_spy_rate"] is None, -(r["beat_spy_rate"] or 0), -(r["window"] or 0)))
    return out


def refresh_all(db: Session) -> int:
    """Weekly, after the 13F sync: compute every tracked holder's record so
    the leaderboard reads from cache."""
    n = 0
    for h in db.query(WhaleHolder).filter(WhaleHolder.is_tracked == True).all():  # noqa: E712
        try:
            compute_holder_record(db, h.id, force=True)
            n += 1
        except Exception as exc:
            logger.warning(f"holder record {h.id} failed: {exc}")
    return n
