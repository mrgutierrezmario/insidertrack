import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from routers.access import require_admin
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.politician import Politician
from models.trade import Trade
from services.congress_fetcher import get_last_sync, get_sync_state, sync_all

router = APIRouter(prefix="/trades", tags=["trades"])

_AMOUNT_MAP = {
    "1,001": 1_001, "15,000": 15_000, "50,000": 50_000,
    "100,000": 100_000, "250,000": 250_000, "500,000": 500_000,
    "1,000,000": 1_000_000, "5,000,000": 5_000_000,
}


def _parse_amount_upper(amount_range: str) -> int:
    """Extract the upper bound from '$1,001 - $15,000' style strings."""
    if not amount_range:
        return 0
    nums = re.findall(r"[\d,]+", amount_range)
    if not nums:
        return 0
    # Take the last (larger) number
    raw = nums[-1].replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return 0


def _risk_level(trade: Trade) -> str:
    today = date.today()
    trade_dt = trade.trade_date
    if isinstance(trade_dt, datetime):
        trade_dt = trade_dt.date()

    age_days = (today - trade_dt).days if trade_dt else 999

    # Information staleness: older disclosure = harder to act on
    if age_days <= 14:
        age_risk = "LOW"
    elif age_days <= 35:
        age_risk = "MEDIUM"
    else:
        age_risk = "HIGH"

    # Disclosure lag: time between trade and when it was reported
    disclose_dt = trade.disclosure_date
    if isinstance(disclose_dt, datetime):
        disclose_dt = disclose_dt.date()
    if trade_dt and disclose_dt:
        lag = (disclose_dt - trade_dt).days
        lag_risk = "LOW" if lag <= 15 else ("MEDIUM" if lag <= 35 else "HIGH")
    else:
        lag_risk = "MEDIUM"

    # Trade size
    upper = _parse_amount_upper(trade.amount_range or "")
    if upper >= 1_000_000:
        size_label = "LARGE"
    elif upper >= 250_000:
        size_label = "MEDIUM"
    else:
        size_label = "SMALL"

    # Composite: age drives risk, lag and size are secondary
    levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    composite = max(levels[age_risk], levels[lag_risk])
    # Large trades from insiders reduce risk rating by 1 (more conviction signal)
    if size_label == "LARGE" and composite > 0:
        composite -= 1

    return ["LOW", "MEDIUM", "HIGH"][composite]


def refresh_risk_levels(db: Session) -> int:
    """Recompute and store risk_level for every trade. Run daily by the scheduler.

    Cheap: ~100µs per row in Python, single bulk commit. The values drift only
    over calendar time (age-based bucketing), so a daily refresh is enough.
    """
    rows = db.query(Trade).all()
    changed = 0
    for t in rows:
        new = _risk_level(t)
        if t.risk_level != new:
            t.risk_level = new
            changed += 1
    if changed:
        db.commit()
    return changed


def _trade_dict(t: Trade, risk: str) -> dict:
    return {
        "id": t.id,
        "ticker": t.ticker,
        "asset_name": t.asset_name,
        "transaction_type": t.transaction_type,
        "amount_range": t.amount_range,
        "trade_date": t.trade_date,
        "disclosure_date": t.disclosure_date,
        "source": t.source,
        "risk_level": risk,
        "politician": {
            "id": t.politician.id,
            "name": t.politician.name,
            "chamber": t.politician.chamber,
            "party": t.politician.party,
            "state": t.politician.state,
        } if t.politician else None,
    }


@router.get("/")
def list_trades(
    ticker: Optional[str] = None,
    tracked_only: bool = False,
    transaction_type: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
    politician_id: Optional[int] = None,
    risk_level: Optional[str] = None,
    sort_by: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Trade).options(joinedload(Trade.politician))

    if ticker:
        q = q.filter(Trade.ticker == ticker.upper())
    if tracked_only:
        q = q.join(Politician).filter(Politician.is_tracked == True)  # noqa: E712
    if transaction_type:
        q = q.filter(Trade.transaction_type.ilike(f"%{transaction_type}%"))
    if since:
        q = q.filter(Trade.trade_date >= since)
    if until:
        q = q.filter(Trade.trade_date <= until)
    if politician_id:
        q = q.filter(Trade.politician_id == politician_id)

    order = Trade.disclosure_date.desc() if sort_by == "disclosure_date" else Trade.trade_date.desc()

    # risk_level is now stored on the row (refreshed daily by the scheduler).
    # The filter is a real SQL predicate — no more over-fetch + Python re-evaluation.
    if risk_level:
        q = q.filter(Trade.risk_level == risk_level.upper())

    total = q.count()
    rows = q.order_by(order).offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    # Prefer the stored value; fall back to live compute for rows the daily job
    # hasn't touched yet (fresh inserts between job runs).
    items = [_trade_dict(t, t.risk_level or _risk_level(t)) for t in rows[:limit]]
    return {"items": items, "total": total, "offset": offset, "limit": limit, "has_more": has_more}


@router.post("/sync")
def trigger_sync(background_tasks: BackgroundTasks, _: None = Depends(require_admin)):
    """Kick off the House + Senate sync in the background.

    The sync downloads and parses many government PDFs/pages and can run for a
    minute or more, so we don't block the request (and the single worker)
    waiting on it. Poll GET /trades/sync-status for progress and results.
    """
    if get_sync_state()["running"]:
        return {"status": "already_running"}

    def _run():
        from database import SessionLocal
        with SessionLocal() as s:
            sync_all(s)

    background_tasks.add_task(_run)
    return {"status": "started"}


@router.get("/sync-status")
def sync_status(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Live status of the current/last sync, plus the last persisted outcome
    (which survives restarts and covers the 8 AM scheduler run)."""
    return {**get_sync_state(), "last": get_last_sync(db)}
