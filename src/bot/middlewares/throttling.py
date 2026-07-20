"""Ограничение частоты входящих событий по пользователю.

Защищает от «залипшей» кнопки и намеренного флуда: без этого один клиент
способен выдать десятки событий в секунду, каждое из которых потянет вызовы
MAX API и упрётся в антиспам-лимит уже на стороне платформы.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types.updates.message_callback import MessageCallback

logger = logging.getLogger(__name__)

# Сколько записей о пользователях держим в памяти. При превышении чистим
# протухшие — иначе словарь рос бы неограниченно на публичном боте.
_MAX_TRACKED_USERS = 10_000


class ThrottlingMiddleware(BaseMiddleware):
    """Пропускает не чаще одного события на пользователя в `rate` секунд.

    Хранит время последнего события в памяти процесса. При нескольких
    репликах бота лимит становится «мягким» (каждая реплика считает свои
    события) — для честного распределённого лимита нужен Redis.
    """

    def __init__(self, rate: float = 0.5) -> None:
        self._rate = rate
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            _, user_id = event_object.get_ids()
        except (NotImplementedError, AttributeError):
            return await handler(event_object, data)

        if user_id is None:
            return await handler(event_object, data)

        now = time.monotonic()
        last = self._last_seen.get(user_id)
        if last is not None and now - last < self._rate:
            await _reject(event_object)
            return None

        self._last_seen[user_id] = now
        if len(self._last_seen) > _MAX_TRACKED_USERS:
            self._evict(now)
        return await handler(event_object, data)

    def _evict(self, now: float) -> None:
        """Удаляет записи, которые уже не влияют на решение."""
        cutoff = now - self._rate
        stale = [uid for uid, seen in self._last_seen.items() if seen < cutoff]
        for uid in stale:
            del self._last_seen[uid]
        logger.debug("throttling: очищено %d записей", len(stale))


async def _reject(event_object: Any) -> None:
    """Гасит слишком частое событие.

    На callback отвечаем уведомлением, чтобы кнопка не осталась в состоянии
    ожидания. Сообщения игнорируем молча: предупреждение на каждое сообщение
    само по себе стало бы флудом.
    """
    if not isinstance(event_object, MessageCallback):
        return
    try:
        await event_object.answer(notification="Слишком часто, подождите секунду")
    except Exception as exc:
        logger.debug("throttling: не удалось ответить на callback: %s", exc)
