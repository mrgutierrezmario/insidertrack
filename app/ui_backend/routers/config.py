import logging
import time
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models.analysis import DailyAnalysis
from models.subscriber import EmailSubscriber
from routers.access import require_admin, _valid_admin_token, _COOKIE_NAME
from routers.watchlist import _check_rate, _norm_email
from services.email_sender import send_report
from services.subscriber_links import manage_url as _manage_url, sig_ok as _sig_ok, sub_sig as _sub_sig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# ── Rate limiting ─────────────────────────────────────────────────────────────
# Per IP (the proxy-aware IP from routers.access, so a forged X-Forwarded-For
# can't dodge it) for every public subscriber request, and per email for
# anything that sends mail, so nobody can flood a stranger's inbox.
_SUB_WINDOW, _SUB_MAX = 3600, 5
_sub_hits: dict[str, deque] = defaultdict(deque)
_MAIL_WINDOW, _MAIL_MAX = 3600, 3
_mail_hits: dict[str, deque] = defaultdict(deque)


def _check_sub_rate_limit(request: Request):
    _check_rate(_sub_hits, _SUB_WINDOW, _SUB_MAX, request, "subscription")


def _mail_allowed(email: str) -> bool:
    now = time.time()
    bucket = _mail_hits[email]
    while bucket and now - bucket[0] > _MAIL_WINDOW:
        bucket.popleft()
    if len(bucket) >= _MAIL_MAX:
        return False
    bucket.append(now)
    return True


def _is_admin(request: Request, x_admin_token: str | None) -> bool:
    return _valid_admin_token(request.cookies.get(_COOKIE_NAME)) or _valid_admin_token(x_admin_token)


def _send_confirm(sub: EmailSubscriber):
    from services.email_layout import MUTED, SITE_URL, button
    from services.email_sender import send_simple_email

    link = f"{SITE_URL}/config/subscribers/confirm?sub={sub.id}&sig={_sub_sig(sub)}"
    body = (
        '<p style="margin:0 0 14px;">Someone, hopefully you, asked to get InsiderTrack market '
        "reports at this address. Confirm below and they'll start with the next report.</p>"
        + button("Confirm my subscription", link)
        + f'<p style="margin:16px 0 0;color:{MUTED};font-size:13px;">Didn\'t ask for this? Ignore this '
        "email and you won't hear from us again.</p>"
    )
    try:
        send_simple_email(
            "Confirm your InsiderTrack reports", body, [sub.email],
            title="Confirm your subscription", eyebrow="InsiderTrack reports",
        )
    except Exception:
        logger.exception("Failed to send subscription confirmation to %s", sub.email)


def _send_manage_link(sub: EmailSubscriber):
    from services.email_layout import MUTED, button
    from services.email_sender import send_simple_email

    body = (
        '<p style="margin:0 0 14px;">Here is the link to change or cancel your InsiderTrack '
        "report emails.</p>"
        + button("Manage my reports", _manage_url(sub))
        + f'<p style="margin:16px 0 0;color:{MUTED};font-size:13px;">Didn\'t ask for this? You can '
        "ignore this email. Nothing has changed.</p>"
    )
    try:
        send_simple_email(
            "Manage your InsiderTrack reports", body, [sub.email],
            title="Manage your reports", eyebrow="InsiderTrack reports",
        )
    except Exception:
        logger.exception("Failed to send subscription link to %s", sub.email)


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


class ManageLinkIn(BaseModel):
    email: EmailStr


_CHECK_INBOX = {"status": "check_email"}


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
def lookup_subscriber(
    request: Request,
    sub: int = Query(...),
    sig: str = Query(...),
    db: Session = Depends(get_db),
):
    """The subscriber behind an emailed manage link."""
    _check_sub_rate_limit(request)
    row = db.query(EmailSubscriber).filter(EmailSubscriber.id == sub).first()
    if not row or not _sig_ok(row, sig):
        raise HTTPException(status_code=404, detail="This link is not valid. Request a new one.")
    return row


@router.get("/subscribers/confirm")
def confirm_subscriber(sub: int = Query(...), sig: str = Query(...), db: Session = Depends(get_db)):
    """The link in the confirmation email: switch the reports on, then open Settings."""
    row = db.query(EmailSubscriber).filter(EmailSubscriber.id == sub).first()
    if not row or not _sig_ok(row, sig):
        return RedirectResponse("/config?confirmed=invalid", status_code=302)
    if not row.confirmed:
        row.confirmed = True
        db.commit()
    return RedirectResponse(f"/config?sub={row.id}&sig={sig}&confirmed=1", status_code=302)


@router.post("/subscribers", status_code=202)
def add_subscriber(
    body: SubscriberCreate,
    request: Request,
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Admin: add a subscriber directly. Public: always the same "check your
    inbox" answer, and nothing is sent until the owner clicks the link."""
    email = _norm_email(body.email)
    existing = db.query(EmailSubscriber).filter(EmailSubscriber.email == email).first()

    if _is_admin(request, x_admin_token):
        if existing:
            raise HTTPException(status_code=409, detail="Email already subscribed.")
        row = EmailSubscriber(**{**body.model_dump(), "email": email}, confirmed=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    _check_sub_rate_limit(request)
    if existing and existing.confirmed:
        # Already on the list: send the manage link instead. The answer is the
        # same either way, so this can't be used to test who subscribes.
        if _mail_allowed(email):
            _send_manage_link(existing)
        return _CHECK_INBOX
    if existing:
        row = existing
        for k, v in body.model_dump(exclude={"email"}).items():
            setattr(row, k, v)
    else:
        row = EmailSubscriber(**{**body.model_dump(), "email": email}, confirmed=False)
        db.add(row)
    db.commit()
    db.refresh(row)
    if _mail_allowed(email):
        _send_confirm(row)
    return _CHECK_INBOX


@router.post("/subscribers/manage-link")
def request_manage_link(body: ManageLinkIn, request: Request, db: Session = Depends(get_db)):
    """Email the manage link to a confirmed subscriber. Same answer either way."""
    _check_sub_rate_limit(request)
    email = _norm_email(body.email)
    row = db.query(EmailSubscriber).filter(EmailSubscriber.email == email).first()
    if row and row.confirmed and _mail_allowed(email):
        _send_manage_link(row)
    return _CHECK_INBOX


def _owned_subscriber(sub_id: int, sig: str, request: Request, x_admin_token: str | None, db: Session):
    row = db.query(EmailSubscriber).filter(EmailSubscriber.id == sub_id).first()
    if _is_admin(request, x_admin_token):
        if not row:
            raise HTTPException(status_code=404, detail="Subscriber not found.")
        return row
    _check_sub_rate_limit(request)
    if not row or not _sig_ok(row, sig):
        raise HTTPException(status_code=403, detail="This link is not valid. Request a new one.")
    return row


@router.patch("/subscribers/{sub_id}")
def update_subscriber(
    sub_id: int,
    body: SubscriberUpdate,
    request: Request,
    sig: str = Query(default=""),
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    row = _owned_subscriber(sub_id, sig, request, x_admin_token, db)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/subscribers/{sub_id}", status_code=204)
def delete_subscriber(
    sub_id: int,
    request: Request,
    sig: str = Query(default=""),
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    row = _owned_subscriber(sub_id, sig, request, x_admin_token, db)
    db.delete(row)
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
    subs = db.query(EmailSubscriber).filter(
        EmailSubscriber.is_active == True,  # noqa: E712
        EmailSubscriber.confirmed == True,  # noqa: E712
        getattr(EmailSubscriber, col) == True,  # noqa: E712
    ).all()
    recipients = [s.email for s in subs]

    if not recipients:
        raise HTTPException(status_code=400, detail="No active subscribers for this report.")

    ok = send_report(analysis, recipients, {s.email: _manage_url(s) for s in subs})
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
