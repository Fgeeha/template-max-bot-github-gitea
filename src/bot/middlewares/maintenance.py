"""Maintenance-гейт: пока PROD=false, бот отвечает только администраторам.

Регистрируется как outer middleware — перехватывает сообщения, callback'и и
bot_started единым кодом, до того как сработают фильтры хендлеров.
"""

from __future__ import annotations

import logging
from typing import Any

from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot.config import get_settings

logger = logging.getLogger(__name__)

MAINTENANCE_TEXT = "Бот в разработке, скоро откроется."


class MaintenanceMiddleware(BaseMiddleware):
    """Блокирует неадминов, пока PROD=false."""

    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: Any,
        data: dict[str, Any],
    ) -> Any:
        settings = get_settings()
        if not settings.is_maintenance:
            return await handler(event_object, data)

        try:
            _, user_id = event_object.get_ids()
        except (NotImplementedError, AttributeError):
            # Системные события без user_id пропускаем: блокировать нечего и некого.
            return await handler(event_object, data)

        if user_id is not None and user_id in settings.admin_ids_set:
            return await handler(event_object, data)

        await _notify(event_object, user_id)
        return None


async def _notify(event_object: Any, user_id: int | None) -> None:
    """Сообщает о недоступности способом, подходящим типу события."""
    try:
        if isinstance(event_object, MessageCallback):
            # На callback единственный корректный ответ — всплывающее
            # уведомление; отправка сообщения оставит «часики» на кнопке.
            await event_object.answer(notification=MAINTENANCE_TEXT)

        elif isinstance(event_object, MessageCreated):
            from maxapi.enums.chat_type import ChatType

            # В группах молчим: ответ на каждое упоминание превращается в спам.
            if event_object.message.recipient.chat_type != ChatType.DIALOG:
                return
            await event_object.message.answer(text=MAINTENANCE_TEXT)

        elif isinstance(event_object, BotStarted) and user_id is not None:
            await event_object.bot.send_message(user_id=user_id, text=MAINTENANCE_TEXT)

        # Остальные системные события (user_added, bot_removed) игнорируем молча.
    except Exception as exc:
        # Не даём сбою уведомления сломать обработку события.
        logger.warning("maintenance: не удалось отправить заглушку: %s", exc)
