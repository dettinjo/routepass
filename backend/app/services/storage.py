"""Object storage service for GPX files.

Falls back to a no-op (returns None) when STORAGE_BACKEND=db so callers
always store data in the gpx_data column instead.
"""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level cache: one aiobotocore client context manager per endpoint+key pair.
# Not pre-created — initialised lazily on first use.
_S3_SESSION = None


def _get_s3_client():
    """Return an async context manager that yields an aiobotocore S3 client."""
    import aiobotocore.session  # type: ignore

    global _S3_SESSION
    if _S3_SESSION is None:
        _S3_SESSION = aiobotocore.session.get_session()

    return _S3_SESSION.create_client(
        "s3",
        region_name=settings.STORAGE_REGION,
        endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.STORAGE_SECRET_ACCESS_KEY,
    )


class StorageService:
    @staticmethod
    def _key(user_id: str, activity_id: str) -> str:
        return f"gpx/{user_id}/{activity_id}.gpx"

    @classmethod
    async def put_gpx(cls, user_id: str, activity_id: str, data: bytes) -> str | None:
        """Upload GPX bytes and return the storage key, or None when using DB backend."""
        if settings.STORAGE_BACKEND == "db":
            return None

        key = cls._key(str(user_id), str(activity_id))
        try:
            async with _get_s3_client() as client:
                await client.put_object(
                    Bucket=settings.STORAGE_BUCKET,
                    Key=key,
                    Body=data,
                    ContentType="application/gpx+xml",
                )
            logger.debug("StorageService.put_gpx: stored %s (%d bytes)", key, len(data))
            return key
        except Exception as exc:
            logger.error("StorageService.put_gpx failed for key %s: %s", key, exc)
            raise

    @classmethod
    async def get_gpx(cls, key: str) -> bytes:
        """Download GPX bytes by storage key."""
        try:
            async with _get_s3_client() as client:
                resp = await client.get_object(Bucket=settings.STORAGE_BUCKET, Key=key)
                return await resp["Body"].read()
        except Exception as exc:
            logger.error("StorageService.get_gpx failed for key %s: %s", key, exc)
            raise

    @classmethod
    async def generate_presigned_url(cls, key: str, expires_in: int = 300) -> str:
        """Return a presigned GET URL for a stored GPX object (default TTL: 5 min)."""
        try:
            async with _get_s3_client() as client:
                url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": settings.STORAGE_BUCKET, "Key": key},
                    ExpiresIn=expires_in,
                )
            logger.debug("StorageService.generate_presigned_url: %s (ttl=%ds)", key, expires_in)
            return url
        except Exception as exc:
            logger.error("StorageService.generate_presigned_url failed for key %s: %s", key, exc)
            raise

    @classmethod
    async def delete_gpx(cls, key: str) -> None:
        """Delete a stored GPX object. No-op when using DB backend."""
        if settings.STORAGE_BACKEND == "db":
            return
        try:
            async with _get_s3_client() as client:
                await client.delete_object(Bucket=settings.STORAGE_BUCKET, Key=key)
            logger.debug("StorageService.delete_gpx: deleted %s", key)
        except Exception as exc:
            logger.warning("StorageService.delete_gpx failed for key %s: %s", key, exc)
