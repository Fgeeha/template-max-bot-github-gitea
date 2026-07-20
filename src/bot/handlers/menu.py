"""Навигация по разделам: /help, callback'и меню и разбор свободного текста."""

from __future__ import annotations

import logging

from maxapi import Dispatcher
from maxapi.filters.command import Command
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot.handlers.start import WELCOME_TEXT
from bot.keyboards.callbacks import BackPayload, MenuPayload, PayloadError
from bot.keyboards.menus import back_keyboard, get_section, main_menu

logger = logging.getLogger(__name__)

UNKNOWN_TEXT = "Не понял запрос. Выберите раздел в меню 👇"


def register(dp: Dispatcher) -> None:
    dp.message_created(Command("help"))(on_help)
    dp.message_callback()(on_callback)
    # Catch-all: регистрируется последним, иначе перехватит команды.
    dp.message_created()(on_free_text)


async def on_help(event: MessageCreated) -> None:
    section = get_section("help")
    text = section.text if section else UNKNOWN_TEXT
    await event.message.answer(text=text, attachments=[main_menu().as_markup()])


async def on_callback(event: MessageCallback) -> None:
    """Единая точка обработки нажатий кнопок."""
    payload = event.callback.payload or ""

    if BackPayload.matches(payload):
        await _show_main_menu(event)
        return

    if not MenuPayload.matches(payload):
        # Payload из старой версии клавиатуры или подделанный.
        logger.info("Неизвестный payload callback: %r", payload)
        await event.answer(notification="Кнопка устарела, откройте меню заново")
        return

    try:
        section_id = MenuPayload.unpack(payload).section
    except PayloadError as exc:
        logger.warning("Битый payload: %s", exc)
        await event.answer(notification="Кнопка устарела, откройте меню заново")
        return

    section = get_section(section_id)
    if section is None or section.url:
        # Раздел удалён из SECTIONS, либо это внешняя ссылка — у неё нет
        # экрана внутри бота.
        await event.answer(notification="Раздел недоступен")
        return

    await event.message.answer(
        text=f"{section.title}\n\n{section.text}",
        attachments=[back_keyboard().as_markup()],
    )


async def on_free_text(event: MessageCreated) -> None:
    """Ответ на произвольный текст.

    Здесь обычно живёт поиск или разбор пользовательского ввода. В шаблоне —
    возврат в меню.
    """
    from maxapi.enums.chat_type import ChatType

    # В группах на каждое сообщение не отвечаем: бот превратился бы в спамера.
    if event.message.recipient.chat_type != ChatType.DIALOG:
        return

    await event.message.answer(
        text=UNKNOWN_TEXT,
        attachments=[main_menu().as_markup()],
    )


async def _show_main_menu(event: MessageCallback) -> None:
    await event.message.answer(
        text=WELCOME_TEXT,
        attachments=[main_menu().as_markup()],
    )
