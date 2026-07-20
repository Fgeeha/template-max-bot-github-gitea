"""Асинхронный движок и фабрика сессий SQLAlchemy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Возвращает singleton движка.

    Движок создаётся лениво: до первого обращения к БД пул соединений не
    поднимается, поэтому бот без БД ничего не платит за наличие этого модуля.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            msg = "DATABASE_URL не задан — слой БД недоступен"
            raise RuntimeError(msg)
        _engine = create_async_engine(
            settings.database_url,
            # pool_pre_ping отсекает соединения, разорванные файрволом или
            # рестартом Postgres, — без него первый запрос после простоя падает.
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=10,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Возвращает singleton фабрики сессий."""
    global _sessionmaker
    if _sessionmaker is None:
        # expire_on_commit=False: иначе после commit обращение к любому полю
        # объекта вызывает новый SELECT, а в async это выстреливает
        # MissingGreenlet вне сессии.
        _sessionmaker = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Генератор сессии — для внедрения зависимости в хендлеры и сервисы."""
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Транзакция: commit при успехе, rollback при исключении."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Закрывает пул соединений при остановке бота."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
