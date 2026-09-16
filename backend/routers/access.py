import hashlib
import hmac
import os
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.access import SiteAccess

router = APIRouter(prefix="/access", tags=["access"])

# ── Rate limiting (in-memory, resets on restart) ───────────────────────────────
_attempts: dict[str, list[float]] = defaultdict(list)
_WINDOW = 300   # 5-minute window
_MAX    = 10    # max attempts per window

def _check_rate_limit(ip: str):
    now = time.time()
    recent = [t for t in _attempts[ip] if now - t < _WINDOW]
    if len(recent) >= _MAX:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in 5 minutes.")
    recent.append(now)
    _attempts[ip] = recent
    # Evict keys with no recent attempts to prevent unbounded growth
    stale = [k for k, v in list(_attempts.items()) if k != ip and not any(now - t < _WINDOW for t in v)]
    for k in stale:
        del _attempts[k]


def _get_ip(request: Request) -> str:
    """Return the client IP, only honouring X-Forwarded-For when behind a trusted proxy.

    Trusting `X-Forwarded-For` unconditionally lets any client claim any IP, which
    defeats the rate limiter and the terms-agreement gate. We now only consult
    the header when the immediate peer (`request.client.host`) matches an entry
    in `TRUSTED_PROXIES` (comma-separated, from env), and we use the
    *right-most* value — the address closest to the trusted proxy — not the
    left-most, which is fully client-controlled.
    """
    immediate = request.client.host if request.client else "unknown"
    trusted = {p.strip() for p in (os.environ.get("TRUSTED_PROXIES") or "").split(",") if p.strip()}
    if immediate in trusted:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
    return immediate


# ── Admin token (hourly rotating HMAC, stateless) ─────────────────────────────
def _make_token(password: str) -> str:
    hour = int(time.time()) // 3600
    return hashlib.sha256(f"{password}:{hour}".encode()).hexdigest()[:32]


_COOKIE_NAME = "admin_token"


def _valid_admin_token(token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, _make_token(settings.admin_password))


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)):
    # Prefer httpOnly cookie; fall back to X-Admin-Token header for backward compat
    if _valid_admin_token(request.cookies.get(_COOKIE_NAME)):
        return
    if _valid_admin_token(x_admin_token):
        return
    raise HTTPException(status_code=401, detail="Admin authentication required.")


# ── Site access ────────────────────────────────────────────────────────────────
class AgreeRequest(BaseModel):
    email: str = ""


@router.get("/check")
def check_access(request: Request, db: Session = Depends(get_db)):
    ip = _get_ip(request)
    exists = db.query(SiteAccess).filter(SiteAccess.ip_address == ip).first()
    return {"agreed": exists is not None, "ip": ip}


@router.post("/agree")
def record_agreement(body: AgreeRequest, request: Request, db: Session = Depends(get_db)):
    ip = _get_ip(request)
    existing = db.query(SiteAccess).filter(SiteAccess.ip_address == ip).first()
    if existing:
        if body.email and not existing.email:
            existing.email = body.email
        db.commit()
    else:
        db.add(SiteAccess(
            ip_address=ip,
            email=body.email or None,
            user_agent=request.headers.get("User-Agent"),
        ))
        db.commit()
    return {"status": "ok", "ip": ip}


@router.get("/log")
def list_access(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(SiteAccess).order_by(SiteAccess.agreed_at.desc()).all()
    return [
        {
            "id": r.id,
            "ip_address": r.ip_address,
            "email": r.email,
            "user_agent": r.user_agent,
            "agreed_at": r.agreed_at.isoformat() if r.agreed_at else None,
        }
        for r in rows
    ]


# ── Admin password verification ────────────────────────────────────────────────
class AdminVerifyRequest(BaseModel):
    password: str


@router.post("/admin/verify")
def admin_verify(body: AdminVerifyRequest, request: Request):
    """Legacy endpoint — returns token for header-based auth. Prefer /admin/login."""
    _check_rate_limit(_get_ip(request))
    if not hmac.compare_digest(body.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"ok": True, "token": _make_token(body.password)}


@router.post("/admin/login")
def admin_login(body: AdminVerifyRequest, request: Request, response: Response):
    """Set an httpOnly admin session cookie. Safer than the token-in-sessionStorage approach."""
    _check_rate_limit(_get_ip(request))
    if not hmac.compare_digest(body.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    response.set_cookie(
        key=_COOKIE_NAME,
        value=_make_token(body.password),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,  # COOKIE_SECURE=true behind HTTPS (prod)
        max_age=3600,                   # matches the 1-hour token rotation window
    )
    return {"ok": True}


@router.post("/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie(_COOKIE_NAME)
    return {"ok": True}


@router.get("/admin/status")
def admin_status(request: Request):
    return {"is_admin": _valid_admin_token(request.cookies.get(_COOKIE_NAME))}
