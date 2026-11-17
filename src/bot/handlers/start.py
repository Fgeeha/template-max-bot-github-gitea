"""Приветствие: команда /start и системное событие bot_started.

Текст приветствия и кнопки главного меню — корневой раздел в БД, правится
через /admin.
"""

from __future__ import annotations

from functools import partial

from maxapi import Dispatcher
from maxapi.enums.chat_type import ChatType
from maxapi.filters.command import Command, CommandStart
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_created import MessageCreated

from bot.handlers.admin import user_id_of
from bot.handlers.menu import load_root, send_root, send_screen


def register(dp: Dispatcher) -> None:
    dp.message_created(CommandStart())(on_start_command)
    dp.message_created(Command("id"))(on_id_command)
    # bot_started приходит при первом открытии диалога — до того, как
    # пользователь что-либо отправит. Без этого хендлера первый экран пустой.
    dp.bot_started()(on_bot_started)


async def on_start_command(event: MessageCreated) -> None:
    await send_root(event)


async def on_id_command(event: MessageCreated) -> None:
    """Свой MAX user ID — его владелец вводит, добавляя администратора."""
    user_id = user_id_of(event)
    if user_id is None or event.message.recipient.chat_type != ChatType.DIALOG:
        return
    await event.message.answer(text=f"Ваш MAX user ID: {user_id}")


async def on_bot_started(event: BotStarted) -> None:
    text, attachments = await load_root()
    # Отвечать некуда — сообщения ещё нет, поэтому пишем напрямую пользователю.
    await send_screen(
        partial(event.bot.send_message, user_id=event.user.user_id), text, attachments
    )
