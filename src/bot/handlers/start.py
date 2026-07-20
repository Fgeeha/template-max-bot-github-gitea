"""Приветствие: команда /start и системное событие bot_started."""

from __future__ import annotations

from textwrap import dedent

from maxapi import Dispatcher
from maxapi.filters.command import CommandStart
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_created import MessageCreated

from bot.keyboards.menus import main_menu

WELCOME_TEXT = dedent(
    """\
    👋 Здравствуйте!

    Это шаблон бота для мессенджера MAX.
    Замените этот текст описанием своего бота.

    Выберите раздел 👇
    """
)


def register(dp: Dispatcher) -> None:
    dp.message_created(CommandStart())(on_start_command)
    # bot_started приходит при первом открытии диалога — до того, как
    # пользователь что-либо отправит. Без этого хендлера первый экран пустой.
    dp.bot_started()(on_bot_started)


async def on_start_command(event: MessageCreated) -> None:
    await event.message.answer(
        text=WELCOME_TEXT,
        attachments=[main_menu().as_markup()],
    )


async def on_bot_started(event: BotStarted) -> None:
    # Отвечать некуда — сообщения ещё нет, поэтому пишем напрямую пользователю.
    await event.bot.send_message(
        user_id=event.user.user_id,
        text=WELCOME_TEXT,
        attachments=[main_menu().as_markup()],
    )
