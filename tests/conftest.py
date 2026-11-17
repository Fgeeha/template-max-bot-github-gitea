"""Общие фикстуры.

Тесты герметичны: в сеть не ходят, реальный токен не используют. Настройки
задаются через переменные окружения — так же, как в проде, поэтому проверяется
в том числе и разбор конфигурации.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import Settings, get_settings
from bot.db import session as db_session
from bot.db.models import Base
from bot.handlers.pending import waiting


@pytest.fixture(autouse=True)
def _clean_settings_cache() -> Iterator[None]:
    """Сбрасывает кэш настроек до и после каждого теста.

    Без этого настройки, созданные в одном тесте, протекали бы в следующий:
    get_settings кэширует результат на весь процесс.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """Задаёт переменные окружения бота.

    Файл .env в тестах игнорируется через _env_file=None: иначе локальный .env
    разработчика влиял бы на результат, и тесты падали бы только у него.
    """

    def _apply(**overrides: str) -> Settings:
        base = {
            "MAX_BOT_TOKEN": "test-token",
            "PROD": "true",
            "ADMIN_IDS": "",
            "DATABASE_URL": "postgresql+asyncpg://bot:bot@db:5432/bot",
        }
        for key, value in {**base, **overrides}.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)  # type: ignore[call-arg]

    return _apply


@pytest.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Схема в SQLite в памяти — запросы репозитория переносимые.

    Каскадное удаление в SQLite выключено по умолчанию — включаем PRAGMA,
    иначе тест удаления ветки проходил бы не по той причине.
    """
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(
    monkeypatch: pytest.MonkeyPatch, env, sessionmaker: async_sessionmaker[AsyncSession]
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    env(ADMIN_IDS="1")  # ADMIN из test_editor_flow
    maker = sessionmaker

    # session_scope берёт фабрику через get_sessionmaker() при каждом вызове,
    # поэтому одна подмена покрывает все модули (editor, menu, tools, admin).
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: maker)
    waiting.clear()
    yield maker
