"""Инструменты админки: администраторы, статистика, экспорт/импорт, журнал.

Заглушки событий — из tests/fakes, фикстура db — из conftest.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from maxapi.enums.attachment import AttachmentType

from bot.handlers import editor, tools
from bot.handlers.inputs import EXPORT_FORMAT, EXPORT_VERSION, parse_tree
from bot.handlers.pending import waiting
from bot.keyboards.callbacks import AdminAction, AdminPayload
from tests.fakes import (
    ADMIN,
    STRANGER,
    FakeCallback,
    FakeMessage,
    Replies,
    buttons,
    navigate,
    press,
    send,
)

HELPER = 3


def _tool(action: AdminAction, target: int = 0) -> str:
    return AdminPayload(action=action, target=target).pack()


async def _admin_root(user_id: int = ADMIN) -> dict[str, Any]:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(user_id, "/admin", replies))
    return replies.last


async def test_owner_adds_and_revokes_admin(db) -> None:
    # До добавления помощник админку не видит.
    _, edits = await press(HELPER, _tool(AdminAction.HOME))
    assert edits.last == {"notification": "Недоступно"}

    await press(ADMIN, _tool(AdminAction.STAFF_ADD))
    error = await send(ADMIN, "не число")
    assert error.last["text"].startswith("⚠️")
    added = await send(ADMIN, str(HELPER))
    assert "Администратор добавлен" in added.last["text"]
    assert str(HELPER) in added.last["text"]

    # Теперь помощник — администратор, но управлять списком не может.
    root = await _admin_root(HELPER)
    assert "⚙️ Админка" in root["text"]
    _, edits = await press(HELPER, _tool(AdminAction.STAFF_ADD))
    assert edits.last["notification"].startswith("Только для владельца")
    _, edits = await press(HELPER, _tool(AdminAction.STAFF))
    assert "➕ Добавить администратора" not in buttons(edits.last)

    # Отзыв — с подтверждением; доступ пропадает сразу.
    _, edits = await press(ADMIN, buttons(added.last)[f"🗑 {HELPER}"])
    _, edits = await press(ADMIN, buttons(edits.last)["✅ Да, отозвать"])
    assert edits.last["notification"] == "Доступ отозван"
    _, edits = await press(HELPER, _tool(AdminAction.HOME))
    assert edits.last == {"notification": "Недоступно"}


async def test_owner_id_is_not_added_to_staff(db) -> None:
    await press(ADMIN, _tool(AdminAction.STAFF_ADD))
    reply = await send(ADMIN, str(ADMIN))
    assert "владелец" in reply.last["text"]
    assert ADMIN in waiting  # ждём другой id


async def test_stats_count_users_but_not_admins(db) -> None:
    root = await _admin_root()
    await press(ADMIN, buttons(root)["➕ Добавить подраздел"])
    await send(ADMIN, "Цены")

    # Показ меню в ответ на текст — не открытие раздела.
    menu_screen = await send(STRANGER, "привет")
    prices = buttons(menu_screen.last)["Цены"]
    await navigate(STRANGER, prices)
    await navigate(STRANGER, prices)
    await navigate(ADMIN, prices)  # админ не считается

    _, edits = await press(ADMIN, _tool(AdminAction.STATS, 7))
    text = edits.last["new_text"]
    assert "Открытий разделов: 2" in text
    assert "Пользователей: 1" in text
    assert "1. Цены — 2 / 1" in text


async def test_stats_disabled_records_nothing(db, env) -> None:
    env(ADMIN_IDS=str(ADMIN), STATS_ENABLED="false")
    await send(STRANGER, "привет")
    _, edits = await press(ADMIN, _tool(AdminAction.STATS, 30))
    assert "Открытий разделов: 0" in edits.last["new_text"]
    assert "Сбор выключен" in edits.last["new_text"]


async def test_deleted_section_stats_kept(db) -> None:
    root = await _admin_root()
    await press(ADMIN, buttons(root)["➕ Добавить подраздел"])
    added = await send(ADMIN, "Цены")
    menu_screen = await send(STRANGER, "привет")
    await navigate(STRANGER, buttons(menu_screen.last)["Цены"])

    _, edits = await press(ADMIN, buttons(added.last)["🗑 Удалить"])
    await press(ADMIN, buttons(edits.last)["✅ Да, удалить"])
    _, edits = await press(ADMIN, _tool(AdminAction.STATS, 30))
    assert "удалённые разделы — 1 / 1" in edits.last["new_text"]


class FileCapture:
    """message.answer, который читает отправленный JSON до удаления временного файла."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.names: list[str] = []

    async def answer(self, **kwargs: Any) -> None:
        for item in kwargs.get("attachments") or []:
            path = getattr(item, "path", None)
            if path:
                self.names.append(Path(path).name)
                self.docs.append(json.loads(Path(path).read_text(encoding="utf-8")))


async def _press_capture(user_id: int, payload: str) -> tuple[FileCapture, Replies]:
    capture, edits = FileCapture(), Replies()
    event_obj = FakeCallback(user_id, payload, Replies(), edits)
    event_obj.message = SimpleNamespace(answer=capture.answer)
    await editor.on_admin_callback(event_obj)
    return capture, edits


def _file_message(user_id: int, replies: Replies) -> FakeMessage:
    event_obj = FakeMessage(user_id, "", replies)
    event_obj.message.body.text = None
    event_obj.message.body.attachments = [
        SimpleNamespace(
            type=AttachmentType.FILE,
            filename="sections.json",
            payload=SimpleNamespace(url="https://files.example/sections.json"),
        )
    ]
    return event_obj


async def test_export_import_roundtrip(db, monkeypatch: pytest.MonkeyPatch) -> None:
    root = await _admin_root()
    await press(ADMIN, buttons(root)["➕ Добавить подраздел"])
    added = await send(ADMIN, "Прайс")
    await press(ADMIN, buttons(added.last)["📝 Текст"])
    await send(ADMIN, "Стрижка — 500 ₽")

    capture, edits = await _press_capture(ADMIN, _tool(AdminAction.EXPORT))
    assert edits.last["notification"] == "Файл — сообщением ниже"
    doc = capture.docs[0]
    assert capture.names[0].startswith("sections-") and capture.names[0].endswith(".json")
    assert doc["format"] == EXPORT_FORMAT
    assert doc["root"]["children"][0]["text"] == "Стрижка — 500 ₽"

    # Правим файл и загружаем обратно: дерево заменяется целиком.
    doc["root"]["children"][0]["title"] = "Услуги"
    payload = json.dumps(doc, ensure_ascii=False).encode()

    async def fake_download(url: str) -> bytes:
        return payload

    monkeypatch.setattr(tools, "download", fake_download)
    capture, edits = await _press_capture(ADMIN, _tool(AdminAction.IMPORT))
    assert len(capture.docs) == 1, "перед загрузкой — резервная копия"
    assert "заменятся" in edits.last["new_text"]

    replies = Replies()
    event_obj = _file_message(ADMIN, replies)
    assert await editor.PendingInput()(event_obj)
    await editor.on_admin_input(event_obj)
    assert "Разделы загружены" in replies.last["text"]
    assert ADMIN not in waiting

    user = await send(STRANGER, "привет")
    screen = await navigate(STRANGER, buttons(user.last)["Услуги"])
    assert screen["text"] == "Стрижка — 500 ₽"


async def test_import_rejects_text_instead_of_file(db) -> None:
    await _press_capture(ADMIN, _tool(AdminAction.IMPORT))
    reply = await send(ADMIN, "вот текст")
    assert reply.last["text"].startswith("⚠️")
    assert ADMIN in waiting


async def test_audit_log_shows_changes(db) -> None:
    root = await _admin_root()
    await press(ADMIN, buttons(root)["➕ Добавить подраздел"])
    added = await send(ADMIN, "Акции")
    await press(ADMIN, buttons(added.last)["📝 Текст"])
    await send(ADMIN, "Скидка 10%")

    _, edits = await press(ADMIN, _tool(AdminAction.LOG))
    text = edits.last["new_text"]
    assert "добавил раздел «Акции»" in text
    assert "изменил текст «Акции»" in text
    # Новые записи — сверху.
    assert text.index("изменил текст") < text.index("добавил раздел")


def _doc(root: dict[str, Any]) -> bytes:
    return json.dumps({"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "root": root}).encode()


def _node(title: str = "Раздел", **extra: Any) -> dict[str, Any]:
    return {"title": title, "text": "", "url": None, "image_token": None, "children": [], **extra}


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"not json", "не JSON"),
        (json.dumps({"root": {}}).encode(), "format/version"),
        (_doc(_node(children=[_node("x" * 65)])), "длиннее 64"),
        (_doc(_node(children=[_node(url="javascript:alert(1)")])), "https://"),
        (_doc(_node(children=[_node(str(i)) for i in range(25)])), "не больше 24"),
        (_doc(_node(text=123)), "строкой"),
    ],
)
def test_parse_tree_rejects(data: bytes, error: str) -> None:
    tree, message = parse_tree(data)
    assert tree is None
    assert error in (message or "")


def test_parse_tree_normalizes() -> None:
    tree, error = parse_tree(
        _doc(_node(url="https://root.ru", children=[_node(" Сайт ", url="https://пример.рф")]))
    )
    assert error is None and tree is not None
    assert tree["url"] is None, "у главного меню ссылки не бывает"
    assert tree["children"][0]["title"] == "Сайт"
    assert tree["children"][0]["url"] == "https://xn--e1afmkfd.xn--p1ai"


async def test_revoked_admin_pending_input_goes_to_menu(db) -> None:
    await press(ADMIN, _tool(AdminAction.STAFF_ADD))
    added = await send(ADMIN, str(HELPER))
    root = await _admin_root(HELPER)
    await press(HELPER, buttons(root)["➕ Добавить подраздел"])
    assert HELPER in waiting

    _, edits = await press(ADMIN, buttons(added.last)[f"🗑 {HELPER}"])
    await press(ADMIN, buttons(edits.last)["✅ Да, отозвать"])

    # Ожидание снято, бывший админ получает обычное меню, а не тишину.
    reply = await send(HELPER, "Цены")
    assert HELPER not in waiting
    assert reply.last["text"] == "Выберите раздел 👇"


async def test_export_without_original_message_goes_to_user(db) -> None:
    capture, edits = FileCapture(), Replies()
    event_obj = FakeCallback(ADMIN, _tool(AdminAction.EXPORT), Replies(), edits)
    event_obj.message = None
    event_obj.callback.user = SimpleNamespace(user_id=ADMIN)
    sent: list[int] = []

    async def send_message(user_id: int, **kwargs: Any) -> None:
        sent.append(user_id)
        await capture.answer(**kwargs)

    event_obj.bot = SimpleNamespace(send_message=send_message)
    await editor.on_admin_callback(event_obj)
    assert sent == [ADMIN]
    assert capture.docs[0]["format"] == EXPORT_FORMAT
