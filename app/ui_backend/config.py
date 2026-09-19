from pathlib import Path
from pydantic_settings import BaseSettings

# Dev config lives next to the code: app/ui_backend/.env (the deploy/ stack passes
# everything as environment variables instead).
ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    database_url: str
    alpha_vantage_key: str = ""

    # AI research notes. Keys and the provider choice are admin-editable in
    # Settings (stored in app_settings, applied live); these are the defaults.
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    ai_provider: str = "claude"            # claude | gemini | openai
    claude_model: str = "claude-opus-5"
    gemini_model: str = "gemini-flash-latest"
    openai_model: str = "gpt-4o-mini"
    admin_password: str = "191919"

    # Set true behind HTTPS (production via Tailscale Funnel / reverse proxy) — the
    # admin_token cookie will only be sent over TLS. Leave false in plain-HTTP
    # dev or the browser silently drops the cookie and admin login appears to fail.
    cookie_secure: bool = False

    # Public hostname the app is served from (no scheme). Used in the CORS
    # allowlist. Empty value = only same-origin / localhost is trusted.
    public_domain: str = ""

    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = ""
    mail_from_name: str = "InsiderTrack"
    # Optional Reply-To, for when MAIL_FROM is a do-not-reply account.
    mail_reply_to: str = ""
    # Where operational notices go (data-source failures). Defaults to the
    # sending account.
    mail_admin_to: str = ""

    class Config:
        env_file = str(ENV_FILE)
        extra = "ignore"


settings = Settings()
