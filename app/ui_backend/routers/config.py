import hmac
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models.analysis import DailyAnalysis
from models.subscriber import EmailSubscriber
from routers.access import require_admin, _make_token
from services.email_sender import send_report
from config import settings

router = APIRouter(prefix="/config", tags=["config"])

# ── Rate limiting for subscriber signup ───────────────────────────────────────
_sub_attempts: dict[str, list[float]] = defaultdict(list)
_SUB_WINDOW = 3600   # 1-hour window
_SUB_MAX    = 5      # max signups per IP per hour


def _check_sub_rate_limit(request: Request):
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    now = time.time()
    recent = [t for t in _sub_attempts[ip] if now - t < _SUB_WINDOW]
    if len(recent) >= _SUB_MAX:
        raise HTTPException(status_code=429, detail="Too many signup attempts. Try again later.")
    recent.append(now)
    _sub_attempts[ip] = recent
    stale = [k for k, v in list(_sub_attempts.items()) if k != ip and not any(now - t < _SUB_WINDOW for t in v)]
    for k in stale:
        del _sub_attempts[k]


def _is_admin(x_admin_token: str | None) -> bool:
    if not x_admin_token:
        return False
    return hmac.compare_digest(x_admin_token, _make_token(settings.admin_password))


class SubscriberCreate(BaseModel):
    email: EmailStr
    subscribe_morning: bool = True
    subscribe_midday: bool = True
    subscribe_evening: bool = True


class SubscriberUpdate(BaseModel):
    subscribe_morning: bool | None = None
    subscribe_midday: bool | None = None
    subscribe_evening: bool | None = None
    is_active: bool | None = None


@router.get("/subscribers")
def list_subscribers(
    email: Optional[str] = Query(default=None),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all subscribers. Admin token required."""
    q = db.query(EmailSubscriber)
    if email:
        q = q.filter(EmailSubscriber.email == email.lower().strip())
    return q.order_by(EmailSubscriber.created_at).all()


@router.get("/subscribers/lookup")
def lookup_subscriber(email: str = Query(...), db: Session = Depends(get_db)):
    """Self-service lookup by email — no admin token required."""
    sub = db.query(EmailSubscriber).filter(
        EmailSubscriber.email == email.lower().strip()
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found for that email.")
    return sub


@router.post("/subscribers", status_code=201)
def add_subscriber(
    body: SubscriberCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    _check_sub_rate_limit(request)
    existing = db.query(EmailSubscriber).filter(EmailSubscriber.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already subscribed.")
    sub = EmailSubscriber(**body.model_dump())
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.patch("/subscribers/{sub_id}")
def update_subscriber(
    sub_id: int,
    body: SubscriberUpdate,
    email: str = Query(default=""),
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    sub = db.query(EmailSubscriber).filter(EmailSubscriber.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found.")

    if not _is_admin(x_admin_token):
        if not email:
            raise HTTPException(status_code=403, detail="Email verification required.")
        if sub.email.lower() != email.lower().strip():
            raise HTTPException(status_code=403, detail="Email does not match subscription.")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(sub, field, value)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subscribers/{sub_id}", status_code=204)
def delete_subscriber(
    sub_id: int,
    email: str = Query(default=""),
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    sub = db.query(EmailSubscriber).filter(EmailSubscriber.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found.")

    if not _is_admin(x_admin_token):
        if not email:
            raise HTTPException(status_code=403, detail="Email verification required.")
        if sub.email.lower() != email.lower().strip():
            raise HTTPException(status_code=403, detail="Email does not match subscription.")

    db.delete(sub)
    db.commit()


@router.post("/send-report/{period}")
def send_report_now(
    period: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if period not in ("morning", "midday", "evening"):
        raise HTTPException(status_code=400, detail="period must be morning | midday | evening")

    analysis = (
        db.query(DailyAnalysis)
        .filter(DailyAnalysis.period == period)
        .order_by(DailyAnalysis.created_at.desc())
        .first()
    )
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail=f"No {period} analysis found. Run an analysis first.",
        )

    col = f"subscribe_{period}"
    recipients = [
        s.email
        for s in db.query(EmailSubscriber).filter(
            EmailSubscriber.is_active == True,  # noqa: E712
            getattr(EmailSubscriber, col) == True,  # noqa: E712
        ).all()
    ]

    if not recipients:
        raise HTTPException(status_code=400, detail="No active subscribers for this report.")

    ok = send_report(analysis, recipients)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="Email failed to send. Check that MAIL_PASSWORD is set in .env.",
        )

    return {"status": "sent", "period": period, "recipients": len(recipients)}


@router.get("/email-status")
def email_status():
    from config import settings
    configured = bool(settings.mail_username and settings.mail_password)
    return {
        "configured": configured,
        "from": settings.mail_from if configured else None,
        "note": "Add MAIL_PASSWORD (Gmail App Password) to .env to enable email reports." if not configured else "Email is configured and ready.",
    }
