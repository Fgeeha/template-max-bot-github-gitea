"""Проверки payload'ов и сборки клавиатур."""

from __future__ import annotations

import pytest

from bot.keyboards.callbacks import (
    MAX_PAYLOAD_LEN,
    BackPayload,
    MenuPayload,
    PayloadError,
)
from bot.keyboards.menus import SECTIONS, get_section, main_menu


def test_menu_payload_roundtrip() -> None:
    packed = MenuPayload(section="about").pack()
    assert MenuPayload.unpack(packed).section == "about"


def test_menu_payload_rejects_foreign_prefix() -> None:
    with pytest.raises(PayloadError):
        MenuPayload.unpack("back")


def test_menu_payload_rejects_empty_section() -> None:
    with pytest.raises(PayloadError):
        MenuPayload.unpack("menu:")


def test_long_payload_rejected() -> None:
    """Платформа обрезает длинный payload молча — ловим это при сборке кнопки."""
    with pytest.raises(PayloadError):
        MenuPayload(section="x" * MAX_PAYLOAD_LEN).pack()


def test_back_payload_matches_itself() -> None:
    assert BackPayload.matches(BackPayload().pack())
    assert not MenuPayload.matches(BackPayload().pack())


def test_all_sections_have_unique_ids() -> None:
    ids = [section.id for section in SECTIONS]
    assert len(ids) == len(set(ids))


def test_every_section_payload_resolves() -> None:
    """Каждая callback-кнопка меню должна вести в существующий раздел."""
    for section in SECTIONS:
        if section.url:
            continue
        packed = MenuPayload(section=section.id).pack()
        assert get_section(MenuPayload.unpack(packed).section) is not None


def test_main_menu_builds() -> None:
    assert main_menu().as_markup() is not None
