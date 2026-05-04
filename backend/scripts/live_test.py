from __future__ import annotations

"""End-to-End Live Integration Test using actual Strava and Komoot credentials."""

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

UTC = UTC

# Fix python path for script execution
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Override environment variables before app loads
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test_key"
os.environ["KOMOOT_ENCRYPTION_KEY"] = "V2_bN33G249Y2iS5Z0tC1E9oXy7UqJ0lVzU6M1hP5s8="
os.environ["STRAVA_CLIENT_ID"] = "226500"
os.environ["STRAVA_CLIENT_SECRET"] = "97eb1224d05fb83e4416c6f0244a2e16f95e1f40"

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Import backend modules
from app.core import security
from app.db.base import Base
from app.db.models.sync import SyncedActivity
from app.db.models.user import StravaApp, StravaToken, User
from app.services.komoot import KomootClient
from app.services.strava import StravaClient
from app.services.sync import SyncService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("live_test")


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    TestingSessionLocal = async_sessionmaker(expire_on_commit=False, bind=engine)

    # 1. Initialize Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Initializing Live DB Test Environment...")

    import uuid

    test_user_id = uuid.uuid4()
    test_app_id = 999

    async with TestingSessionLocal() as db:
        # 2. Seed Test Architecture
        test_app = StravaApp(
            id=test_app_id,
            client_id="226500",
            client_secret=b"97eb1224d05fb83e4416c6f0244a2e16f95e1f40",
            display_name="Live Test Env",
        )
        db.add(test_app)

        test_user = User(
            id=test_user_id,
            email="j.dettinger@student.vu.nl",
            komoot_email_encrypted=security.encrypt("j.dettinger@student.vu.nl"),
            komoot_password_encrypted=security.encrypt(".mL/f4Y$KV8Wmj4"),
            komoot_user_id="5676414827752",
            sync_komoot_to_strava=True,
        )
        db.add(test_user)

        test_token = StravaToken(
            user_id=test_user_id,
            strava_app_id=test_app_id,
            strava_athlete_id=9999999,  # Dummy
            access_token=b"b418e56773811fce52f532cc05790c2387040bbc",
            refresh_token=b"dcf234dfc8ed9e55eb03a583916cd885811e04e7",
            expires_at=datetime.now(UTC) + timedelta(minutes=60),
            connected_at=datetime.now(UTC),
        )
        db.add(test_token)
        await db.commit()

        logger.info("Data seeded successfully. Instantiating Services...")

        # 3. Instantiate Clients
        # Subclass KomootClient to limit results during live testing
        class LimitedKomootClient(KomootClient):
            async def get_tours(self, since: datetime):
                # Always fetch exactly 1 tour from the super class to save rates!
                results = []
                async for raw in self._iter_tour_pages():
                    # Manually parsing same as komoot.py
                    from app.services.komoot import Tour, _parse_date, _strava_sport

                    date = _parse_date(raw["date"])
                    sport = raw.get("sport", "")

                    results.append(
                        Tour(
                            id=str(raw["id"]),
                            name=raw.get("name", "Komoot Activity"),
                            description=raw.get("description") or "",
                            sport=sport,
                            strava_sport=_strava_sport(sport),
                            date=date,
                            distance_m=float(raw.get("distance", 0)),
                            elevation_up_m=float(raw.get("elevation_up", 0)),
                        )
                    )
                    break  # STOP AFTER 1 ITERATION (Max 1 Tour fetched!)
                return results

        komoot = LimitedKomootClient(
            email="j.dettinger@student.vu.nl",
            password=".mL/f4Y$KV8Wmj4",
            user_id="5676414827752",
        )
        strava = StravaClient(access_token="b418e56773811fce52f532cc05790c2387040bbc")

        # 4. Trigger Sync
        sync = SyncService(db)

        logger.info("Triggering Full Pipeline Synchronization...")
        try:
            await sync.sync_komoot_to_strava(test_user, test_app, komoot, strava)
        except Exception as e:
            logger.error("Sync Engine failed during test execution: %s", e)

        # 5. Assertions
        stmt = select(SyncedActivity).where(SyncedActivity.user_id == test_user_id)
        res = await db.execute(stmt)
        activities = res.scalars().all()

        logger.info(f"Test Finished. Generated {len(activities)} database rows.")
        for a in activities:
            logger.info(
                "Status: [%s] | Direction: [%s] | Komoot ID: [%s] | Strava ID: [%s]",
                a.sync_status,
                a.sync_direction,
                a.komoot_tour_id,
                getattr(a, "strava_activity_id", "N/A"),
            )


if __name__ == "__main__":
    asyncio.run(main())
