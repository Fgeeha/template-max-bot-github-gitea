"""Инлайн-клавиатуры бота."""

from bot.keyboards.callbacks import BackPayload, MenuPayload
from bot.keyboards.menus import back_keyboard, main_menu

__all__ = [
    "BackPayload",
    "MenuPayload",
    "back_keyboard",
    "main_menu",
]
