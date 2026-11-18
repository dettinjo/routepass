"""Build provider clients from stored credentials."""

from __future__ import annotations

from sqlalchemy.orm import Session

from routepass import store
from routepass.config import get_settings
from routepass.db import session_scope
from routepass.providers.komoot import KomootClient
from routepass.providers.strava import StravaClient

STRAVA_TOKENS = "strava.tokens"
STRAVA_ATHLETE = "strava.athlete"
STRAVA_APP = "strava.app"
KOMOOT_CREDENTIALS = "komoot.credentials"
KOMOOT_ACCOUNT = "komoot.account"


class NotConnected(Exception):
    pass


def strava_app(db: Session) -> tuple[str, str]:
    """Client id/secret: from the UI-stored app first, else environment."""
    app = store.get_secret(db, STRAVA_APP) or {}
    settings = get_settings()
    return (
        app.get("client_id") or settings.strava_client_id,
        app.get("client_secret") or settings.strava_client_secret,
    )


def _save_tokens(tokens: dict) -> None:
    with session_scope() as db:
        store.set_secret(db, STRAVA_TOKENS, tokens)


def strava_client(db: Session, *, background: bool = False) -> StravaClient:
    tokens = store.get_secret(db, STRAVA_TOKENS)
    if not tokens:
        raise NotConnected("Strava is not connected")
    client_id, client_secret = strava_app(db)
    # Background work keeps headroom for interactive use and sync uploads.
    return StravaClient(
        client_id,
        client_secret,
        tokens,
        on_refresh=_save_tokens,
        reserve_15=25 if background else 2,
        reserve_day=150 if background else 5,
    )


def komoot_client(db: Session) -> KomootClient:
    creds = store.get_secret(db, KOMOOT_CREDENTIALS)
    if not creds:
        raise NotConnected("Komoot is not connected")
    return KomootClient(creds["email"], creds["password"], creds["user_id"])


def connected(db: Session) -> dict[str, bool]:
    return {
        "strava": store.get_value(db, STRAVA_TOKENS) is not None,
        "komoot": store.get_value(db, KOMOOT_CREDENTIALS) is not None,
    }
