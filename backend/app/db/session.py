"""Database engine and session management.

SQLite is the default so the platform runs with zero external services - a
hard requirement for a laptop demo.  The engine configuration below is
PostgreSQL-ready: point ``OCEANVIEW_DATABASE_URL`` at Postgres/PostGIS and
nothing else changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.logging import get_logger
from app.db.models import Base

logger = get_logger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")

engine: Engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    # SQLite's default thread check would break FastAPI's threadpool workers.
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        """Enable WAL and foreign keys.

        WAL lets reads proceed during a write, which matters because
        ingestion and the API share one file.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def init_db() -> None:
    """Create tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)
    logger.info("database_ready", extra={"url": _safe_url(settings.database_url)})


def drop_db() -> None:
    """Drop every table - used by the test-suite and the reset script."""
    Base.metadata.drop_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and background work."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def healthcheck() -> bool:
    """Return ``True`` when the database answers a trivial query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("database_healthcheck_failed")
        return False


def _safe_url(url: str) -> str:
    """Strip credentials before a connection string reaches the logs."""
    if "@" in url and "//" in url:
        scheme, _, rest = url.partition("//")
        _, _, host = rest.partition("@")
        return f"{scheme}//***@{host}"
    return url
