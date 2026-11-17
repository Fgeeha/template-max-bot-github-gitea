"""Проверки payload'ов кнопок и сборки клавиатур."""

from __future__ import annotations

import pytest

from bot.db.models import Section
from bot.keyboards.callbacks import AdminAction, AdminPayload, PayloadError, SectionPayload
from bot.keyboards.menus import admin_keyboard, section_keyboard


def test_section_payload_roundtrip() -> None:
    assert SectionPayload.unpack(SectionPayload(section_id=42).pack()).section_id == 42


@pytest.mark.parametrize("raw", ["s:", "s:abc", "a:open:1", "menu:about"])
def test_section_payload_rejects_garbage(raw: str) -> None:
    with pytest.raises(PayloadError):
        SectionPayload.unpack(raw)


@pytest.mark.parametrize("action", list(AdminAction))
def test_admin_payload_roundtrip(action: AdminAction) -> None:
    payload = AdminPayload(action=action, target=7)
    assert AdminPayload.unpack(payload.pack()) == payload


@pytest.mark.parametrize("raw", ["a:open", "a:hack:1", "a:open:x", "s:1"])
def test_admin_payload_rejects_garbage(raw: str) -> None:
    with pytest.raises(PayloadError):
        AdminPayload.unpack(raw)


def test_prefixes_do_not_overlap() -> None:
    """Кнопка админки не должна уйти в пользовательскую навигацию и наоборот."""
    admin = AdminPayload(action=AdminAction.OPEN, target=1).pack()
    user = SectionPayload(section_id=1).pack()
    assert AdminPayload.matches(admin) and not SectionPayload.matches(admin)
    assert SectionPayload.matches(user) and not AdminPayload.matches(user)


def test_leaf_has_no_keyboard() -> None:
    root = Section(id=1, parent_id=None, title="Главное меню", text="")
    assert section_keyboard(root, []) is None


def test_admin_keyboard_root_has_no_delete() -> None:
    root = Section(id=1, parent_id=None, title="Главное меню", text="")
    payloads = [b.payload for row in admin_keyboard(root, []).payload for b in row]
    assert AdminPayload(action=AdminAction.DELETE, target=1).pack() not in payloads
    child = Section(id=2, parent_id=1, title="Раздел", text="")
    payloads = [b.payload for row in admin_keyboard(child, []).payload for b in row]
    assert AdminPayload(action=AdminAction.DELETE, target=2).pack() in payloads


def test_admin_screen_fits_max_rows() -> None:
    """При предельном числе подразделов экран админки влезает в 30 рядов MAX."""
    from bot.keyboards.menus import MAX_CHILDREN

    section = Section(id=2, parent_id=1, title="Раздел", text="")
    children = [
        Section(id=10 + i, parent_id=2, title=f"П{i}", text="") for i in range(MAX_CHILDREN)
    ]
    assert len(admin_keyboard(section, children).payload) <= 30
