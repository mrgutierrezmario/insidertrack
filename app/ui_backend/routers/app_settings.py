"""
User-configurable API keys, credentials and the AI provider choice.
Values are stored in the `app_settings` DB table and applied to the live
`settings` object immediately — no restart required.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
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
        "label": "Claude API Key",
        "description": "AI research notes via Anthropic Claude.",
        "help": "console.anthropic.com — pay-as-you-go; notes are cached 6h so a ticker costs one call per refresh.",
        "link": "https://console.anthropic.com/settings/keys",
        "sensitive": True,
        "placeholder": "sk-ant-...",
        "group": "ai",
    },
    "gemini_api_key": {
        "label": "Gemini API Key",
        "description": "AI research notes via Google Gemini.",
        "help": "aistudio.google.com — has a free tier.",
        "link": "https://aistudio.google.com/apikey",
        "sensitive": True,
        "placeholder": "AIza...",
        "group": "ai",
    },
    "openai_api_key": {
        "label": "OpenAI API Key",
        "description": "AI research notes via OpenAI.",
        "help": "platform.openai.com — pay-as-you-go.",
        "link": "https://platform.openai.com/api-keys",
        "sensitive": True,
        "placeholder": "sk-...",
        "group": "ai",
    },
    "ai_provider": {
        "label": "Research notes provider",
        "description": "Which provider writes the bull/bear notes. Any other provider with a key saved is used as a fallback.",
        "help": "claude | gemini | openai",
        "link": None,
        "sensitive": False,
        "placeholder": "claude",
        "group": "ai_model",
        "choices": ["claude", "gemini", "openai"],
    },
    "claude_model": {
        "label": "Claude model",
        "description": "Model ID used when Claude writes the note.",
        "help": "e.g. claude-opus-5, claude-sonnet-5",
        "link": "https://docs.anthropic.com/en/docs/about-claude/models",
        "sensitive": False,
        "placeholder": "claude-opus-5",
        "group": "ai_model",
    },
    "gemini_model": {
        "label": "Gemini model",
        "description": "Model ID used when Gemini writes the note. The list is fetched live from Google for your key.",
        "help": "gemini-flash-latest tracks the newest Flash release.",
        "link": None,
        "sensitive": False,
        "placeholder": "gemini-flash-latest",
        "group": "ai_model",
    },
    "openai_model": {
        "label": "OpenAI model",
        "description": "Model ID used when OpenAI writes the note.",
        "help": "e.g. gpt-4o-mini",
        "link": None,
        "sensitive": False,
        "placeholder": "gpt-4o-mini",
        "group": "ai_model",
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


# Non-secret settings that must never be blank: clearing them restores the
# config.py default instead of leaving an empty model name behind.
_DEFAULTED = {"ai_provider", "claude_model", "gemini_model", "openai_model", "mail_from_name"}


def _apply_to_settings(key: str, value: str):
    """Push a new value into the live settings object."""
    if not value and key in _DEFAULTED:
        value = type(settings).model_fields[key].default
    if hasattr(settings, key):
        object.__setattr__(settings, key, value)
    # Bust caches that depend on this key
    if key in ("ai_provider", "claude_model", "gemini_model", "openai_model", "anthropic_api_key", "gemini_api_key", "openai_api_key"):
        from services.ai_summary import _cache as _summary_cache
        _summary_cache.clear()
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
            "group": meta.get("group", "general"),
            "choices": meta.get("choices"),
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
    choices = KEYS[key].get("choices")
    if choices and value and value not in choices:
        raise HTTPException(status_code=400, detail=f"'{key}' must be one of: {', '.join(choices)}")

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


# ── AI provider helpers ───────────────────────────────────────────────────────

@router.get("/ai")
def ai_status():
    """Public: which provider writes research notes right now (no secrets)."""
    from services import providers
    active = providers.active_provider()
    return {
        "configured": active is not None,
        "active": active,
        "chosen": settings.ai_provider,
        "providers": {
            p: {"label": providers.LABELS[p], "configured": providers.configured(p), "model": providers.model_for(p)}
            for p in providers.PROVIDERS
        },
    }


@router.get("/ai/models")
def ai_models(provider: str = Query(...), _: None = Depends(require_admin)):
    """Models available to the saved key for a provider, from that provider's live list."""
    from services import providers
    try:
        return providers.list_models(provider)
    except Exception as e:  # noqa: BLE001 — surfaced to the settings UI
        raise HTTPException(status_code=502, detail=str(e)[:200])


@router.post("/ai/test")
def test_ai_provider(provider: str = Query(...), _: None = Depends(require_admin)):
    """Cheap connectivity check for one provider."""
    from services import providers
    ok, message = providers.test_provider(provider)
    return {"provider": provider, "ok": ok, "message": message}


def load_db_settings(db: Session):
    """Called at startup — overlays any DB-stored keys onto the live settings."""
    rows = db.query(AppSetting).all()
    for row in rows:
        if row.value and row.key in KEYS:
            _apply_to_settings(row.key, row.value)
