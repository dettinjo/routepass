from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379"
    SECRET_KEY: str
    KOMOOT_ENCRYPTION_KEY: str
    STRAVA_CLIENT_ID: str
    STRAVA_CLIENT_SECRET: str
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_LIFETIME: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    ENVIRONMENT: str = "production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    FRONTEND_URL: str = "http://localhost:3000"
    STRAVA_WEBHOOK_VERIFY_TOKEN: str = ""

    # Deployment mode — controls feature set and billing availability.
    # "cloud"      → full SaaS with Stripe, shared Strava app pool, tier enforcement
    # "selfhosted" → single-user, no billing, all features unlocked, own Strava app
    DEPLOYMENT_MODE: str = "cloud"

    # Maximum registered users. 0 = unlimited (cloud default).
    # Set to 1 for a standard single-user self-hosted install.
    MAX_USERS: int = 0

    # DB connection pool (tune per deployment; pgBouncer overrides these)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # ARQ worker concurrency
    ARQ_MAX_JOBS: int = 10

    # Object storage backend.
    # "db"  → store GPX blobs in the DB (suitable for self-hosted, small installs)
    # "s3"  → AWS S3-compatible (also works for Hetzner Object Storage)
    # "r2"  → Cloudflare R2 (uses S3 API but requires custom endpoint)
    STORAGE_BACKEND: str = "db"
    STORAGE_BUCKET: str = ""
    STORAGE_ENDPOINT_URL: str = ""  # R2 or MinIO custom endpoint
    STORAGE_ACCESS_KEY_ID: str = ""
    STORAGE_SECRET_ACCESS_KEY: str = ""
    STORAGE_REGION: str = "auto"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
