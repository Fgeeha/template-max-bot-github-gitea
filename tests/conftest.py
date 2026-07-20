"""Общие фикстуры.

Тесты герметичны: в сеть не ходят, реальный токен не используют. Настройки
задаются через переменные окружения — так же, как в проде, поэтому проверяется
в том числе и разбор конфигурации.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from bot.config import Settings, get_settings


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
        base = {"MAX_BOT_TOKEN": "test-token", "PROD": "true", "ADMIN_IDS": ""}
        for key, value in {**base, **overrides}.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)  # type: ignore[call-arg]

    return _apply
