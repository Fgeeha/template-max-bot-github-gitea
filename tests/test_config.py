"""Проверки разбора и валидации настроек."""

from __future__ import annotations

import pytest

from bot.config import BotMode


def test_defaults_are_safe(env) -> None:
    """Незаданный PROD оставляет бота закрытым, а режим — polling."""
    settings = env(PROD="false")
    assert settings.bot_mode is BotMode.POLLING
    assert settings.is_maintenance is True
    assert settings.use_webhook is False


def test_admin_ids_parsing(env) -> None:
    settings = env(ADMIN_IDS=" 123, 456 ,789 ")
    assert settings.admin_ids_set == frozenset({123, 456, 789})


def test_admin_ids_ignores_garbage(env) -> None:
    """Мусор в списке не должен ронять старт — просто не попадает в множество."""
    settings = env(ADMIN_IDS="123, abc, , -5, 456")
    assert settings.admin_ids_set == frozenset({123, 456})


def test_webhook_requires_host(env) -> None:
    with pytest.raises(ValueError, match="WEBHOOK_HOST"):
        env(BOT_MODE="webhook", WEBHOOK_SECRET="s" * 32)


def test_webhook_requires_secret(env) -> None:
    """Webhook без секрета — открытый эндпоинт, старт запрещён."""
    with pytest.raises(ValueError, match="WEBHOOK_SECRET"):
        env(BOT_MODE="webhook", WEBHOOK_HOST="https://bot.example.ru")


def test_webhook_url_built_from_parts(env) -> None:
    settings = env(
        BOT_MODE="webhook",
        WEBHOOK_HOST="https://bot.example.ru/",
        WEBHOOK_PATH="hook",
        WEBHOOK_SECRET="s" * 32,
    )
    # Лишний слеш в хосте и отсутствующий в пути не должны давать // или склейку.
    assert settings.webhook_url == "https://bot.example.ru/hook"


def test_sync_dsn_rejected(env) -> None:
    """Синхронный драйвер с async-движком не работает — ловим на старте."""
    with pytest.raises(ValueError, match="asyncpg"):
        env(DATABASE_URL="postgresql://bot:bot@db:5432/bot")


def test_async_dsn_accepted(env) -> None:
    settings = env(DATABASE_URL="postgresql+asyncpg://bot:bot@db:5432/bot")
    assert settings.database_url is not None
