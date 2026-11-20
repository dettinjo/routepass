from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from routepass.config import get_settings
from routepass.models import Base

# Bump and append to _MIGRATIONS when the schema changes; create_all handles new tables.
SCHEMA_VERSION = 5
_MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE activities ADD COLUMN rpe INTEGER",
        "ALTER TABLE training_sessions ADD COLUMN rpe INTEGER",
        "ALTER TABLE training_sessions ADD COLUMN feel VARCHAR(12)",
        "ALTER TABLE training_sessions ADD COLUMN feedback_note TEXT",
        "ALTER TABLE training_sessions ADD COLUMN original_target JSON",
    ],
    3: [
        "ALTER TABLE training_weeks ADD COLUMN ai_written_at DATETIME",
        "ALTER TABLE training_sessions ADD COLUMN coach_feedback TEXT",
        "ALTER TABLE plan_adaptations ADD COLUMN details JSON",
        "ALTER TABLE plan_adaptations ADD COLUMN ai_error TEXT",
    ],
    4: ["ALTER TABLE activities ADD COLUMN coach_analysis JSON"],
    5: ["ALTER TABLE training_sessions ADD COLUMN route_data JSON"],
}

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


def _column_exists(conn, stmt: str) -> bool:
    words = stmt.split()
    if len(words) < 6 or [w.upper() for w in words[:2]] != ["ALTER", "TABLE"] or words[3].upper() != "ADD":
        return False
    table, column = words[2], words[5] if words[4].upper() == "COLUMN" else words[4]
    return any(row[1] == column for row in conn.execute(text(f"PRAGMA table_info({table})")))


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
                    if _column_exists(conn, stmt):
                        continue  # table was created by create_all above with the column already
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
