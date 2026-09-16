"""
User-configurable API keys and credentials.
Values are stored in the `app_settings` DB table and applied to the live
`settings` object immediately — no restart required.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.app_setting import AppSetting
from routers.access import require_admin

router = APIRouter(prefix="/settings", tags=["settings"])

# Keys that users can configure, with metadata for the UI
KEYS = {
    "alpha_vantage_key": {
        "label": "Alpha Vantage API Key",
        "description": "Enables minute-by-minute intraday charts on ticker pages.",
        "help": "Free at alphavantage.co — 25 requests/day on the free tier.",
        "link": "https://www.alphavantage.co/support/#api-key",
        "sensitive": True,
        "placeholder": "e.g. AB12CD34EF56GH78",
    },
    "anthropic_api_key": {
        "label": "Anthropic API Key",
        "description": "Enables AI-generated bull/bear research summaries on ticker pages.",
        "help": "Get one at console.anthropic.com — pay-as-you-go, summaries are cached 6h.",
        "link": "https://console.anthropic.com/settings/keys",
        "sensitive": True,
        "placeholder": "sk-ant-...",
    },
    "mail_username": {
        "label": "Gmail Address",
        "description": "The Gmail account used to send email reports.",
        "help": "Must be a Gmail address. Used as both login and sender.",
        "link": None,
        "sensitive": False,
        "placeholder": "you@gmail.com",
    },
    "mail_password": {
        "label": "Gmail App Password",
        "description": "16-character App Password for Gmail SMTP.",
        "help": "Go to myaccount.google.com/apppasswords — requires 2FA enabled.",
        "link": "https://myaccount.google.com/apppasswords",
        "sensitive": True,
        "placeholder": "xxxx xxxx xxxx xxxx",
    },
    "mail_from_name": {
        "label": "Email Sender Name",
        "description": "Display name shown on outgoing report emails.",
        "help": "Shown as \"From: InsiderTrack <you@gmail.com>\" in recipients' inboxes.",
        "link": None,
        "sensitive": False,
        "placeholder": "InsiderTrack",
    },
}


def _live_value(key: str) -> str:
    """Return the current live value from the settings object."""
    return getattr(settings, key, "") or ""


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "●" * len(value)
    return value[:4] + "●" * (len(value) - 8) + value[-4:]


def _apply_to_settings(key: str, value: str):
    """Push a new value into the live settings object."""
    if hasattr(settings, key):
        object.__setattr__(settings, key, value)
    # Bust caches that depend on this key
    if key == "alpha_vantage_key":
        from services.market_data import _cache, _history_cache
        for k in list(_cache.keys()):
            if "movers" in k:
                del _cache[k]
        _history_cache.clear()


class UpdateSetting(BaseModel):
    value: str


@router.get("/keys")
def list_keys(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    db_rows = {r.key: r.value for r in db.query(AppSetting).all()}

    result = []
    for key, meta in KEYS.items():
        live = _live_value(key)
        is_set = bool(live)
        source = "env" if is_set and key not in db_rows else ("db" if key in db_rows and db_rows[key] else "unset")
        result.append({
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "help": meta["help"],
            "link": meta["link"],
            "sensitive": meta["sensitive"],
            "placeholder": meta["placeholder"],
            "is_set": is_set,
            "source": source,
            "masked_value": _mask(live) if meta["sensitive"] else live,
        })
    return result


@router.patch("/keys/{key}")
def update_key(key: str, body: UpdateSetting, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    if key not in KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown key '{key}'")

    value = body.value.strip()

    # Upsert into DB
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()

    # Apply to live settings immediately (no restart needed)
    _apply_to_settings(key, value)

    meta = KEYS[key]
    is_set = bool(value)
    return {
        "key": key,
        "label": meta["label"],
        "is_set": is_set,
        "source": "db",
        "masked_value": _mask(value) if meta["sensitive"] else value,
    }


@router.delete("/keys/{key}", status_code=204)
def clear_key(key: str, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    if key not in KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown key '{key}'")
    db.query(AppSetting).filter(AppSetting.key == key).delete()
    db.commit()
    _apply_to_settings(key, "")


def load_db_settings(db: Session):
    """Called at startup — overlays any DB-stored keys onto the live settings."""
    rows = db.query(AppSetting).all()
    for row in rows:
        if row.value and row.key in KEYS:
            _apply_to_settings(row.key, row.value)
