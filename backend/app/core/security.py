from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings

UTC = timezone.utc
ALGORITHM = "HS256"


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token for the given subject (user_id)."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(UTC) + expires_delta
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_access_token(token: str) -> str:
    """Decode and verify a JWT, returning the subject (user_id).

    Raises HTTPException(401) if the token is invalid or expired.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        subject: Optional[str] = payload.get("sub")
        if subject is None:
            raise credentials_exception
        return subject
    except JWTError:
        raise credentials_exception from None


def hash_password(password: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored bcrypt *hashed* password."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_fernet() -> Fernet:
    """Return a Fernet instance initialised with the app-level encryption key."""
    return Fernet(settings.KOMOOT_ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> bytes:
    """Encrypt a plaintext string and return the Fernet token bytes."""
    return get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt Fernet token bytes and return the plaintext string."""
    return get_fernet().decrypt(ciphertext).decode()


def decrypt_maybe_plaintext(value: bytes) -> str:
    """Return a plaintext token from either encrypted bytes or legacy raw bytes."""
    try:
        return decrypt(value)
    except InvalidToken:
        return value.decode()


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key*."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> tuple:
    """Generate a new API key.

    Returns:
        (raw_key, key_hash) where raw_key starts with ``kss_`` and is safe to
        return to the user exactly once, and key_hash is the SHA-256 hex digest
        suitable for storage in the database.
    """
    raw_key = "rp_" + secrets.token_urlsafe(32)
    return raw_key, hash_api_key(raw_key)
