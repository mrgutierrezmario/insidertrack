"""Alert rules + triggered alert events."""

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from routers.access import require_admin
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.alert import AlertEvent, AlertRule

router = APIRouter(prefix="/alerts", tags=["alerts"])

ALERT_TYPES = {
    "high_signal":   "Composite signal score at or above a threshold",
    "momentum":      "Ticker shows a BULLISH technical signal",
    "insider_buy":   "A tracked politician disclosed a purchase",
    "fed_trade":     "A Federal Reserve official disclosed a trade",
    "whale_new":     "An institution opened a new 13F position",
    "earnings_soon": "A tracked ticker has earnings within N days",
}


class RuleIn(BaseModel):
    name: str
    alert_type: str
    ticker: str | None = None
    threshold: float | None = None
    is_active: bool = True
    notify_email: str | None = None


class RulePatch(BaseModel):
    name: str | None = None
    ticker: str | None = None
    threshold: float | None = None
    is_active: bool | None = None
    notify_email: str | None = None


def _rule_dict(r: AlertRule, include_email: bool = False) -> dict:
    d = {
        "id": r.id,
        "name": r.name,
        "alert_type": r.alert_type,
        "ticker": r.ticker,
        "threshold": r.threshold,
        "is_active": r.is_active,
        "event_count": len(r.events),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if include_email:
        d["notify_email"] = r.notify_email
    return d


@router.get("/types")
def list_types():
    return [{"value": k, "description": v} for k, v in ALERT_TYPES.items()]


@router.get("/rules")
def list_rules(
    x_admin_token: str | None = Header(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    from routers.config import _is_admin
    include_email = _is_admin(x_admin_token)
    rules = (
        db.query(AlertRule)
        .order_by(AlertRule.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_rule_dict(r, include_email=include_email) for r in rules]


@router.post("/rules")
def create_rule(body: RuleIn, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    if body.alert_type not in ALERT_TYPES:
        raise HTTPException(400, detail=f"Unknown alert_type '{body.alert_type}'")
    rule = AlertRule(
        name=body.name.strip() or body.alert_type,
        alert_type=body.alert_type,
        ticker=(body.ticker or "").upper().strip() or None,
        threshold=body.threshold,
        is_active=body.is_active,
        notify_email=(body.notify_email or "").strip() or None,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_dict(rule, include_email=True)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: RulePatch, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, detail="Rule not found")
    if body.name is not None:
        rule.name = body.name.strip()
    if body.ticker is not None:
        rule.ticker = body.ticker.upper().strip() or None
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.is_active is not None:
        rule.is_active = body.is_active
    if body.notify_email is not None:
        rule.notify_email = body.notify_email.strip() or None
    db.commit()
    db.refresh(rule)
    return _rule_dict(rule, include_email=True)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, detail="Rule not found")
    db.delete(rule)
    db.commit()


@router.get("/events")
def list_events(
    unseen_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(AlertEvent).order_by(AlertEvent.triggered_at.desc())
    if unseen_only:
        q = q.filter(AlertEvent.seen == False)  # noqa: E712
    events = q.limit(limit).all()
    return [
        {
            "id": e.id,
            "rule_id": e.rule_id,
            "rule_name": e.rule.name if e.rule else None,
            "alert_type": e.rule.alert_type if e.rule else None,
            "ticker": e.ticker,
            "message": e.message,
            "seen": e.seen,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
        }
        for e in events
    ]


@router.get("/events/unseen-count")
def unseen_count(db: Session = Depends(get_db)):
    n = db.query(AlertEvent).filter(AlertEvent.seen == False).count()  # noqa: E712
    return {"unseen": n}


@router.post("/events/mark-seen")
def mark_seen(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(AlertEvent).filter(AlertEvent.seen == False).update({"seen": True})  # noqa: E712
    db.commit()
    return {"status": "ok"}


@router.post("/run")
def run_now(background_tasks: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Manually trigger an alert evaluation pass."""
    from services.alert_engine import evaluate_alerts
    background_tasks.add_task(evaluate_alerts, db)
    return {"status": "started"}
