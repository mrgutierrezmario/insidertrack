from pathlib import Path
from pydantic_settings import BaseSettings

# .env lives one level up from the backend/ folder
ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    database_url: str
    alpha_vantage_key: str = ""
    anthropic_api_key: str = ""
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

    class Config:
        env_file = str(ENV_FILE)
        extra = "ignore"


settings = Settings()
