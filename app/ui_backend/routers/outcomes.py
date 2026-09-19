from datetime import date
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from routers.access import require_admin
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.signal_outcome import SignalOutcome

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


@router.post("/snapshot")
def run_snapshot(background_tasks: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Manually trigger today's signal snapshot."""
    from services.outcome_tracker import snapshot_signals
    background_tasks.add_task(snapshot_signals, db)
    return {"status": "snapshot started"}


@router.post("/fill")
def run_fill(background_tasks: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Manually trigger outcome price fill."""
    from services.outcome_tracker import fill_outcomes
    background_tasks.add_task(fill_outcomes, db)
    return {"status": "fill started"}


@router.post("/backfill")
def run_backfill(
    background_tasks: BackgroundTasks,
    window_days: int = Query(default=14, ge=1, le=60),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reconstruct snapshot rows for weekdays in the last `window_days` that
    are missing. See services.outcome_tracker.backfill_snapshot_gaps for the
    reconstruction caveats — backfilled rows are flagged `is_backfilled=True`."""
    from services.outcome_tracker import backfill_snapshot_gaps
    background_tasks.add_task(backfill_snapshot_gaps, db, window_days)
    return {"status": "backfill started", "window_days": window_days}


@router.get("/stats")
def outcome_stats(
    score_version: int | None = Query(default=None, description="Restrict to one scoring regime; default = current"),
    all_versions: bool = Query(default=False, description="Blend every regime (not comparable — for reference only)"),
    db: Session = Depends(get_db),
):
    """
    Win-rate summary grouped by label and timeframe.
    Returns counts + hit rate (% UP) for 30/60/90d.

    Snapshots from different scoring regimes are not comparable, so by default
    only the current SCORE_VERSION is counted.
    """
    from routers.signals import SCORE_VERSION
    version = None if all_versions else (score_version or SCORE_VERSION)
    labels = ["Strong Watch", "Watch", "Neutral", "High Risk", "Avoid for Now"]
    result = []

    def base(*conds):
        q = db.query(func.count(SignalOutcome.id)).filter(*conds)
        if version is not None:
            q = q.filter(SignalOutcome.score_version == version)
        return q.scalar() or 0

    for label in labels:
        row: dict = {"label": label}
        for days, col in [(30, "outcome_30d"), (60, "outcome_60d"), (90, "outcome_90d")]:
            total = base(SignalOutcome.label == label, getattr(SignalOutcome, col) != None)  # noqa: E711
            up = base(SignalOutcome.label == label, getattr(SignalOutcome, col) == "UP")
            down = base(SignalOutcome.label == label, getattr(SignalOutcome, col) == "DOWN")

            row[f"d{days}"] = {
                "total":    total,
                "up":       up,
                "down":     down,
                "flat":     total - up - down,
                "win_rate": round(up / total * 100, 1) if total else None,
            }
        result.append(row)

    scope = db.query(SignalOutcome)
    if version is not None:
        scope = scope.filter(SignalOutcome.score_version == version)
    total_snaps = scope.with_entities(func.count(SignalOutcome.id)).scalar() or 0
    oldest = scope.with_entities(func.min(SignalOutcome.signal_date)).scalar()
    newest = scope.with_entities(func.max(SignalOutcome.signal_date)).scalar()
    versions = [
        {"version": v, "snapshots": n, "since": s.isoformat() if s else None, "until": u.isoformat() if u else None}
        for v, n, s, u in db.query(SignalOutcome.score_version, func.count(SignalOutcome.id),
                                   func.min(SignalOutcome.signal_date), func.max(SignalOutcome.signal_date))
        .group_by(SignalOutcome.score_version).order_by(SignalOutcome.score_version).all()
    ]

    return {
        "labels": result,
        "total_snapshots": total_snaps,
        "tracking_since": oldest.isoformat() if oldest else None,
        "latest_snapshot": newest.isoformat() if newest else None,
        "score_version": version,          # None = all regimes blended
        "current_version": SCORE_VERSION,
        "versions": versions,
    }


@router.get("/")
def list_outcomes(
    ticker: str = "",
    label: str = "",
    resolved: bool | None = None,
    score_version: int | None = Query(default=None, description="Restrict to one scoring regime"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(SignalOutcome).order_by(SignalOutcome.signal_date.desc())
    if score_version is not None:
        q = q.filter(SignalOutcome.score_version == score_version)
    if ticker:
        q = q.filter(SignalOutcome.ticker == ticker.upper())
    if label:
        q = q.filter(SignalOutcome.label == label)
    if resolved is True:
        q = q.filter(SignalOutcome.outcome_30d != None)   # noqa: E711
    if resolved is False:
        q = q.filter(SignalOutcome.outcome_30d == None)   # noqa: E711
    rows = q.limit(limit).all()

    return [
        {
            "id":              r.id,
            "ticker":          r.ticker,
            "signal_date":     r.signal_date.isoformat(),
            "composite_score": r.composite_score,
            "label":           r.label,
            "signal":          r.signal,
            "price_at_signal": r.price_at_signal,
            "politician_id":   r.politician_id,
            "politician_name": r.politician_name,
            "is_backfilled":   bool(r.is_backfilled),
            "score_version":   r.score_version,
            "sub_scores": {
                "smart_money": r.smart_money_score,
                "insider":     r.insider_score,
                "corporate":   r.corporate_score,
                "momentum":    r.momentum_score,
                "sentiment":   r.sentiment_score,
                "risk_penalty":r.risk_penalty,
            },
            "d30": {"price": r.price_30d, "return": r.return_30d, "outcome": r.outcome_30d},
            "d60": {"price": r.price_60d, "return": r.return_60d, "outcome": r.outcome_60d},
            "d90": {"price": r.price_90d, "return": r.return_90d, "outcome": r.outcome_90d},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
