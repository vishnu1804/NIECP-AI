"""Database engine, session management and declarative base.

Supports PostgreSQL (production target) and SQLite (local/offline persistence).
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings

log = logging.getLogger("niecp.db")


class Base(DeclarativeBase):
    """Declarative base with a shared naming convention so Alembic can
    autogenerate stable constraint names on both PostgreSQL and SQLite."""

    type_annotation_map: dict[Any, Any] = {}


def _build_engine() -> Engine:
    url = settings.database_url
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}

    if url.startswith("sqlite"):
        kwargs.update(
            {
                "connect_args": {"check_same_thread": False, "timeout": 30},
                "poolclass": StaticPool if ":memory:" in url else None,
            }
        )
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        return engine

    kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }
    )
    return create_engine(url, **kwargs)


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background jobs (renewal engine, monitors)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def database_dialect() -> str:
    return engine.dialect.name


def check_database_connectivity() -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - reported, not swallowed silently
        log.warning("database connectivity check failed: %s", exc)
        return False, str(exc)


def init_models() -> None:
    """Create tables if they do not exist.

    Alembic owns schema evolution in production (`alembic upgrade head`);
    this is the convenience path used for fresh local installs and tests.
    """
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
