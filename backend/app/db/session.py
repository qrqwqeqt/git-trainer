"""Async DB engine, session maker, lifespan hooks та FastAPI dependency.

Engine створюється ліниво при першому виклику get_engine(). DATABASE_URL
читається через app.config.get_settings() (LRU-кеш), тому щоб у тестах
перевизначити URL — спочатку міняйте env, потім робіть get_settings.cache_clear().
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models.db import Base

logger = logging.getLogger(__name__)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Повернути (або ліниво створити) глобальний async engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        # SQLite (dev/тести) → NullPool: connection pool погано переноситься
        # між event loop-ами (TestClient портал → конфлікти на teardown),
        # а для file-SQLite пул мало що дає. Для Postgres лишаємо default
        # QueuePool з pool_pre_ping.
        is_sqlite = settings.database_url.startswith("sqlite")
        engine_kwargs: dict[str, object] = {"echo": False, "future": True}
        if is_sqlite:
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_pre_ping"] = True
        _engine = create_async_engine(settings.database_url, **engine_kwargs)
        logger.info(
            "db.engine.created",
            extra={
                "url": _mask_url(settings.database_url),
                "dialect": _engine.dialect.name,
            },
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Повернути (або ліниво створити) sessionmaker для get_session()."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


async def init_db() -> None:
    """Створити всі таблиці, які ще не існують. Викликається з lifespan.

    Це ідемпотентний `CREATE TABLE IF NOT EXISTS` через SQLAlchemy metadata —
    безпечно для dev/SQLite. У проді (Postgres) поверх ще накатуються
    Alembic-міграції; цей виклик нічого не зламає, бо create_all пропускає
    існуючі таблиці.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db.schema.ready")


async def close_db() -> None:
    """Закрити engine. Викликається з lifespan shutdown і у тестових teardown-ах."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        logger.info("db.engine.closed")
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: повертає AsyncSession, закриває по виходу.

    Транзакція не починається автоматично — викликайте session.begin() або
    робіть commit явно. Це залишає вибір транзакційності за endpoint-ом.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


def _mask_url(url: str) -> str:
    """Прибрати пароль з URL у логах."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return url
