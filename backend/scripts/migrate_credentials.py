"""One-shot script: backfill Connection + Pipeline rows from legacy User columns.

Run AFTER migration 002 has been applied and BEFORE migration 003.

    python -m scripts.migrate_credentials

Idempotent — skips users that already have a komoot or strava Connection row.
"""

from __future__ import annotations

import asyncio
import json
import logging

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import encrypt
from app.db.models.connection import Connection
from app.db.models.pipeline import Pipeline
from app.db.models.user import StravaToken, User

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    fernet = Fernet(settings.KOMOOT_ENCRYPTION_KEY.encode())

    async with Session() as db:
        users = (await db.execute(select(User))).scalars().all()
        log.info("Found %d users", len(users))

        for user in users:
            # ------------------------------------------------------------------
            # Check if already migrated
            # ------------------------------------------------------------------
            existing = (
                (await db.execute(select(Connection).where(Connection.user_id == user.id)))
                .scalars()
                .all()
            )
            existing_platforms = {c.platform for c in existing}

            komoot_conn: Connection | None = None
            strava_conn: Connection | None = None

            # ------------------------------------------------------------------
            # Komoot connection
            # ------------------------------------------------------------------
            if "komoot" not in existing_platforms and user.komoot_user_id:
                try:
                    email = fernet.decrypt(user.komoot_email_encrypted).decode()
                    password = fernet.decrypt(user.komoot_password_encrypted).decode()
                    creds = {"email": email, "password": password, "user_id": user.komoot_user_id}
                    komoot_conn = Connection(
                        user_id=user.id,
                        platform="komoot",
                        display_name=email,
                        credentials_enc=encrypt(json.dumps(creds)),
                        status="active",
                        last_synced_at=user.last_komoot_poll_at,
                        meta={
                            "poll_interval_min": user.komoot_poll_interval_min,
                            "key_version": user.komoot_key_version,
                        },
                    )
                    db.add(komoot_conn)
                    log.info("  user %s → created komoot connection", user.id)
                except Exception as exc:
                    log.warning("  user %s → failed to decrypt komoot creds: %s", user.id, exc)

            # ------------------------------------------------------------------
            # Strava connection
            # ------------------------------------------------------------------
            if "strava" not in existing_platforms:
                token = (
                    await db.execute(select(StravaToken).where(StravaToken.user_id == user.id))
                ).scalar_one_or_none()

                if token:
                    from app.core.security import decrypt_maybe_plaintext

                    access = decrypt_maybe_plaintext(token.access_token)
                    refresh = decrypt_maybe_plaintext(token.refresh_token)
                    creds = {
                        "access_token": access,
                        "refresh_token": refresh,
                        "expires_at": token.expires_at.isoformat(),
                        "athlete_id": token.strava_athlete_id,
                        "scope": token.scope,
                    }
                    strava_conn = Connection(
                        user_id=user.id,
                        platform="strava",
                        display_name=f"Strava athlete {token.strava_athlete_id}",
                        credentials_enc=encrypt(json.dumps(creds)),
                        status="active",
                        last_synced_at=token.last_refreshed_at,
                        meta={"app_id": token.strava_app_id},
                    )
                    db.add(strava_conn)
                    log.info("  user %s → created strava connection", user.id)

            await db.flush()

            # ------------------------------------------------------------------
            # Pipeline — only if we have both and none already exists
            # ------------------------------------------------------------------
            existing_pipelines = (
                (await db.execute(select(Pipeline).where(Pipeline.user_id == user.id)))
                .scalars()
                .all()
            )

            if not existing_pipelines and komoot_conn and strava_conn:
                pipeline = Pipeline(
                    user_id=user.id,
                    source_connection_id=komoot_conn.id,
                    dest_connection_id=strava_conn.id,
                    name="Komoot → Strava",
                    enabled=user.sync_komoot_to_strava,
                )
                db.add(pipeline)
                log.info("  user %s → created pipeline komoot→strava", user.id)

        await db.commit()
        log.info("Migration complete.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
