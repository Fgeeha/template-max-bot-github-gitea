"""Сборка клавиатур из описания разделов.

Разделы заданы данными, а не кодом: чтобы добавить пункт меню, достаточно
дописать запись в SECTIONS — клавиатура и обработчик подхватят её сами.
"""

from __future__ import annotations

from dataclasses import dataclass

from maxapi.types.attachments.buttons.callback_button import CallbackButton
from maxapi.types.attachments.buttons.link_button import LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.keyboards.callbacks import BackPayload, MenuPayload


@dataclass(frozen=True)
class Section:
    """Раздел меню.

    url задан — кнопка ведёт наружу (LinkButton), текст не нужен.
    url пуст — кнопка callback, бот покажет `text` и кнопку «Назад».
    """

    id: str
    title: str
    text: str = ""
    url: str | None = None


# Демонстрационное наполнение — замените разделами своего бота.
SECTIONS: tuple[Section, ...] = (
    Section(
        id="about",
        title="ℹ️ О боте",
        text=(
            "Шаблон бота для мессенджера MAX.\n\n"
            "Здесь описано, что умеет бот и как им пользоваться."
        ),
    ),
    Section(
        id="help",
        title="❓ Помощь",
        text=(
            "Доступные команды:\n"
            "/start — главное меню\n"
            "/help — эта справка\n\n"
            "Кнопки под сообщением ведут по разделам."
        ),
    ),
    Section(
        id="site",
        title="🌐 Сайт",
        url="https://max.ru",
    ),
)

_SECTIONS_BY_ID: dict[str, Section] = {section.id: section for section in SECTIONS}


def get_section(section_id: str) -> Section | None:
    """Возвращает раздел по id или None, если такого нет."""
    return _SECTIONS_BY_ID.get(section_id)


def main_menu() -> InlineKeyboardBuilder:
    """Главное меню: по кнопке на раздел, каждая — своей строкой."""
    keyboard = InlineKeyboardBuilder()
    for section in SECTIONS:
        if section.url:
            keyboard.row(LinkButton(text=section.title, url=section.url))
        else:
            keyboard.row(
                CallbackButton(
                    text=section.title,
                    payload=MenuPayload(section=section.id).pack(),
                )
            )
    return keyboard


def back_keyboard() -> InlineKeyboardBuilder:
    """Одиночная кнопка возврата в главное меню."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(CallbackButton(text="◀️ Назад", payload=BackPayload().pack()))
    return keyboard
