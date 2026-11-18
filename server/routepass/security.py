from __future__ import annotations

import hmac
from functools import lru_cache

from cryptography.fernet import Fernet

from routepass.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.secret_key
    if not key:
        key_file = settings.data_dir / "secret.key"
        if key_file.exists():
            key = key_file.read_text().strip()
        else:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key().decode()
            key_file.write_text(key)
            key_file.chmod(0o600)
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def token_ok(presented: str | None) -> bool:
    expected = get_settings().api_token
    if not expected:
        return True
    return presented is not None and hmac.compare_digest(presented, expected)
