"""Инлайн-клавиатуры бота."""

from bot.keyboards.callbacks import AdminAction, AdminPayload, SectionPayload
from bot.keyboards.menus import admin_keyboard, section_keyboard

__all__ = [
    "AdminAction",
    "AdminPayload",
    "SectionPayload",
    "admin_keyboard",
    "section_keyboard",
]
