from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROUTEPASS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    # Bearer token for API and MCP clients (also accepted as a UI login fallback).
    api_token: str = ""
    # Who may sign in to the web UI (comma-separated e-mails). With neither this nor api_token set,
    # the instance is open (trusted network only).
    allowed_emails: str = ""
    # Trust `Tailscale-User-Login` on the private listener (only behind `tailscale serve`).
    trust_tailscale_headers: bool = False
    # Optional second listener for the internet-facing proxy: API paths only, API token only.
    port: int = 8000
    public_port: int = 0
    google_client_id: str = ""
    google_client_secret: str = ""
    # Fernet key used to encrypt provider credentials at rest. Generated into data_dir when empty.
    secret_key: str = ""
    # URL where you open the UI (redirect target after Strava OAuth).
    base_url: str = "http://localhost:8000"
    # Optional internet-facing URL that only exposes the API paths (OAuth callback, Strava
    # webhook, REST, MCP). Used for the Strava redirect and webhook callback when set.
    public_url: str = ""
    strava_webhook_verify_token: str = ""

    # Override the OAuth redirect (e.g. a domain already registered on the Strava app); the
    # code can then be pasted into Settings when that page cannot reach this instance.
    strava_redirect_uri: str = ""
    strava_client_id: str = ""
    strava_client_secret: str = ""

    # Background loop: how often to poll both providers for new activities.
    poll_interval_minutes: int = 30
    scheduler_enabled: bool = True

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "routepass.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
