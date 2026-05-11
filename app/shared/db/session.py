from contextlib import contextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.mer_persona.core.config import get_settings

# ── Async (app 컨테이너) ──────────────────────────────────────────────────
_async_engine = None
_async_session_factory = None


def _get_async_engine():
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        # psycopg3 async driver
        dsn = settings.PG_DSN.replace("postgresql+psycopg://", "postgresql+psycopg_async://")
        _async_engine = create_async_engine(dsn, pool_pre_ping=True)
    return _async_engine


def _get_async_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=_get_async_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _async_session_factory


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with _get_async_factory()() as session:
        yield session


# ── Sync (batch 컨테이너) ─────────────────────────────────────────────────
_sync_engine = None
_sync_session_factory = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        settings = get_settings()
        _sync_engine = create_engine(settings.PG_DSN, pool_pre_ping=True)
    return _sync_engine


def _get_sync_factory():
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(
            bind=_get_sync_engine(), expire_on_commit=False
        )
    return _sync_session_factory


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    session = _get_sync_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
