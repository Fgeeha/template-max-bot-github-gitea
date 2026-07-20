"""Проверки ограничения частоты событий по пользователю."""

from __future__ import annotations

from typing import Any

from bot.middlewares.throttling import ThrottlingMiddleware


class _Event:
    """Минимальная заглушка события с идентификаторами."""

    def __init__(self, user_id: int | None) -> None:
        self._user_id = user_id

    def get_ids(self) -> tuple[int, int | None]:
        return 1, self._user_id


async def _handler(event: Any, data: dict[str, Any]) -> str:
    return "handled"


async def test_first_event_passes() -> None:
    middleware = ThrottlingMiddleware(rate=10.0)
    assert await middleware(_handler, _Event(1), {}) == "handled"


async def test_second_event_blocked() -> None:
    middleware = ThrottlingMiddleware(rate=10.0)
    await middleware(_handler, _Event(1), {})
    assert await middleware(_handler, _Event(1), {}) is None


async def test_different_users_independent() -> None:
    """Лимит персональный: активный пользователь не блокирует остальных."""
    middleware = ThrottlingMiddleware(rate=10.0)
    await middleware(_handler, _Event(1), {})
    assert await middleware(_handler, _Event(2), {}) == "handled"


async def test_event_without_user_passes() -> None:
    """Системные события без user_id ограничивать нечем — пропускаем."""
    middleware = ThrottlingMiddleware(rate=10.0)
    assert await middleware(_handler, _Event(None), {}) == "handled"
    assert await middleware(_handler, _Event(None), {}) == "handled"


async def test_rate_expires() -> None:
    middleware = ThrottlingMiddleware(rate=0.0)
    await middleware(_handler, _Event(1), {})
    assert await middleware(_handler, _Event(1), {}) == "handled"
