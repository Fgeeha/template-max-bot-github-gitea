"""Служебные команды для администраторов: /v, /status.

Админка разделов — в bot.handlers.editor.

Неадминам команды не отвечают вовсе — для стороннего пользователя их как бы
не существует. Это осознанный выбор: сообщение «недостаточно прав» само по
себе раскрывает наличие скрытой функциональности.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from maxapi import Dispatcher
from maxapi.filters.command import Command
from maxapi.types.updates.message_created import MessageCreated

from bot.config import get_settings
from bot.db.repositories import StaffRepository
from bot.db.session import session_scope

logger = logging.getLogger(__name__)

# Запас от лимита платформы (~4096 символов) — длинное сообщение режем сами.
MAX_MESSAGE_LEN = 3800


def user_id_of(event: Any) -> int | None:
    """user_id автора события; None — у системных событий его нет."""
    try:
        _, user_id = event.get_ids()
    except (NotImplementedError, AttributeError):
        return None
    return user_id


def is_owner(user_id: int | None) -> bool:
    """Владелец — user_id из ADMIN_IDS: всё, включая управление администраторами."""
    return user_id is not None and user_id in get_settings().admin_ids_set


async def is_admin(user_id: int | None) -> bool:
    """Владелец или администратор, добавленный через админку (таблица staff).

    Роль читается из БД на каждом событии: отозванный администратор теряет
    доступ сразу, без перезапуска бота.
    """
    if user_id is None:
        return False
    if is_owner(user_id):
        return True
    async with session_scope() as session:
        return await StaffRepository(session).exists(user_id)


def admin_only(
    handler: Callable[[MessageCreated], Awaitable[None]],
) -> Callable[[MessageCreated], Awaitable[None]]:
    """Пропускает к хендлеру только владельцев и администраторов."""

    @wraps(handler)
    async def wrapper(event: MessageCreated) -> None:
        if not await is_admin(user_id_of(event)):
            return
        await handler(event)

    return wrapper


def register(dp: Dispatcher) -> None:
    dp.message_created(Command("v"))(on_version)
    dp.message_created(Command("status"))(on_status)


@admin_only
async def on_version(event: MessageCreated) -> None:
    """Тег текущей сборки — чтобы убедиться, что на проде именно та версия."""
    settings = get_settings()
    text = f"Версия: `{settings.build_tag}`" if settings.build_tag else "Тег сборки не задан."
    await event.message.answer(text=text)


@admin_only
async def on_status(event: MessageCreated) -> None:
    """Сводка по текущей конфигурации бота."""
    for chunk in split_message(build_status_text()):
        await event.message.answer(text=chunk)


def build_status_text() -> str:
    """Собирает отчёт о конфигурации.

    Секреты не выводим — только факт того, задано значение или нет.
    """
    settings = get_settings()
    lines = [
        "🔧 Статус",
        "",
        f"Режим: {settings.bot_mode.value}",
        f"PROD: {settings.prod}",
        f"Владельцев (ADMIN_IDS): {len(settings.admin_ids_set)}",
        f"Статистика: {'включена' if settings.stats_enabled else 'выключена'}",
        f"Метрики: {'включены' if settings.metrics_enabled else 'выключены'}",
        f"Сборка: {settings.build_tag or '—'}",
    ]
    if settings.use_webhook:
        lines.append(f"Webhook: {settings.webhook_url}")
    return "\n".join(lines)


def split_message(text: str, max_len: int = MAX_MESSAGE_LEN) -> list[str]:
    """Режет длинный текст на части по границам строк.

    Разрыв строки посередине ломает форматирование и таблицы, поэтому
    переносим целыми строками, даже если часть выйдет короче предела.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        need = len(line) + 1  # +1 за перевод строки
        if current_len + need > max_len and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = need
        else:
            current.append(line)
            current_len += need
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]
