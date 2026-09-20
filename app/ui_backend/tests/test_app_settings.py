"""routers.app_settings — clearing an Admin override restores the .env value."""

from config import settings
from routers import app_settings as aps


def test_clear_restores_env_baseline(monkeypatch):
    monkeypatch.setitem(aps._ENV_BASELINE, "mail_username", "env-user@example.com")
    aps._apply_to_settings("mail_username", "override@example.com")
    assert settings.mail_username == "override@example.com"
    aps._apply_to_settings("mail_username", "")          # what DELETE /settings/keys/{key} does
    assert settings.mail_username == "env-user@example.com"
    aps._apply_to_settings("mail_username", aps._ENV_BASELINE["mail_username"])


def test_clear_falls_back_to_model_default_when_env_is_empty(monkeypatch):
    monkeypatch.setitem(aps._ENV_BASELINE, "ai_provider", "")
    aps._apply_to_settings("ai_provider", "gemini")
    aps._apply_to_settings("ai_provider", "")
    assert settings.ai_provider == type(settings).model_fields["ai_provider"].default
