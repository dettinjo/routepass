from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from routepass.config import get_settings
from routepass.models import Base

# Bump and append to _MIGRATIONS when the schema changes; create_all handles new tables.
SCHEMA_VERSION = 1
_MIGRATIONS: dict[int, list[str]] = {}

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _on_connect(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.execute("PRAGMA cache_size=-32000")
    cur.close()


def init_db(url: str | None = None) -> Engine:
    global _engine, _Session
    if url is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{settings.db_path}"
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(_engine, "connect", _on_connect)
    Base.metadata.create_all(_engine)
    with _engine.begin() as conn:
        current = conn.execute(text("PRAGMA user_version")).scalar() or 0
        if current == 0:
            conn.execute(text(f"PRAGMA user_version={SCHEMA_VERSION}"))
        else:
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for stmt in _MIGRATIONS.get(version, []):
                    conn.execute(text(stmt))
                conn.execute(text(f"PRAGMA user_version={version}"))
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    assert _engine is not None, "init_db() not called"
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    assert _Session is not None, "init_db() not called"
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session
