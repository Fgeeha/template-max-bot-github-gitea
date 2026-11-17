"""Картинки разделов: установка в админке, отказ MAX и откат на экран без фото."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from maxapi.enums.attachment import AttachmentType
from maxapi.enums.upload_type import UploadType
from maxapi.exceptions.max import MaxApiError

from bot.db.repositories import SectionRepository
from bot.handlers import editor, menu
from bot.handlers.inputs import CLEAR
from bot.handlers.pending import waiting
from bot.keyboards.callbacks import SectionPayload
from bot.keyboards.menus import BACK_TEXT
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


def _images(reply: dict[str, Any]) -> list[str]:
    """Токены картинок среди вложений сообщения."""
    return [
        a.payload.token
        for a in reply.get("attachments") or []
        if getattr(a, "type", None) == UploadType.IMAGE
    ]


async def test_admin_sets_image_on_main_menu_and_section(db) -> None:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    _, edits = await press(ADMIN, buttons(replies.last)["🖼 Картинка"])
    assert "Пришлите одну картинку" in edits.last["new_text"]

    # Текст вместо фото — ошибка, ожидание остаётся.
    wrong = await send(ADMIN, "картинка")
    assert wrong.last["text"].startswith("⚠️")
    saved = await send(ADMIN, "", image_token="root-photo")
    assert "Картинка сохранена" in saved.last["text"]
    assert "🖼 Картинка: есть" in saved.last["text"]

    # Подраздел без картинки.
    await press(ADMIN, buttons(saved.last)["➕ Добавить подраздел"])
    await send(ADMIN, "Техосмотр")

    # Пользователь: картинка над главным меню, в разделе без картинки её нет.
    root = await send(STRANGER, "привет")
    assert _images(root.last) == ["root-photo"]
    screen = await navigate(STRANGER, buttons(root.last)["Техосмотр"])
    assert _images(screen) == []
    back = await navigate(STRANGER, buttons(screen)[BACK_TEXT])
    assert _images(back) == ["root-photo"]

    # Убрать картинку — «-».
    admin_root = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", admin_root))
    await press(ADMIN, buttons(admin_root.last)["🖼 Картинка"])
    cleared = await send(ADMIN, CLEAR)
    assert "Картинка убрана" in cleared.last["text"]
    assert _images((await send(STRANGER, "привет")).last) == []


async def test_photo_is_input_only_for_image_action(db) -> None:
    """Фото без подписи — ввод только для «🖼 Картинка», не для текста."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["📝 Текст"])
    photo = FakeMessage(ADMIN, "", Replies(), image_token="tok")
    assert not await editor.PendingInput()(photo)
    await press(ADMIN, buttons(replies.last)["🖼 Картинка"])
    assert await editor.PendingInput()(photo)


async def test_rejected_image_falls_back_to_plain_screen(db) -> None:
    """MAX не принял токен картинки — меню приходит без неё, а не ломается."""
    async with db() as session:
        root = await SectionRepository(session).root()
        root.image_token = "expired"
        await session.commit()

    calls: list[dict[str, Any]] = []

    async def send(**kwargs: Any) -> None:
        calls.append(kwargs)
        if _images(kwargs):
            raise MaxApiError(code=400, raw={"code": "attachment.invalid"})

    text, attachments = await menu.load_root()
    await menu.send_screen(send, text, attachments)
    assert len(calls) == 2 and _images(calls[-1]) == []

    async def broken(**_kwargs: Any) -> None:
        raise MaxApiError(code=503, raw="down")

    with pytest.raises(MaxApiError):
        await menu.send_screen(broken, text, attachments)


async def test_edit_retries_without_rejected_image(db) -> None:
    """Правка экрана с картинкой, которую MAX не принял, повторяется без неё."""
    async with db() as session:
        root = await SectionRepository(session).root()
        root.image_token = "expired"
        await session.commit()

    edits: list[dict[str, Any]] = []

    async def answer(**kwargs: Any) -> None:
        edits.append(kwargs)
        if _images(kwargs):
            raise MaxApiError(code=400, raw={"code": "attachment.invalid"})

    replies = Replies()
    event_obj = FakeCallback(STRANGER, SectionPayload(section_id=999).pack(), replies, Replies())
    event_obj.answer = answer
    await menu.on_callback(event_obj)
    assert len(edits) == 2 and _images(edits[-1]) == []
    assert edits[-1]["new_text"] == "Выберите раздел 👇"
    assert replies.items == []


async def test_refused_edit_keeps_image_in_new_message(db) -> None:
    """MAX отказал в правке не из-за картинки: новое сообщение — с картинкой."""
    async with db() as session:
        root = await SectionRepository(session).root()
        root.image_token = "good-photo"
        await session.commit()

    async def answer(**_kwargs: Any) -> None:
        raise MaxApiError(code=400, raw={"code": "message.too.old"})

    replies = Replies()
    event_obj = FakeCallback(STRANGER, SectionPayload(section_id=999).pack(), replies, Replies())
    event_obj.answer = answer
    event_obj.ack = Replies().answer
    await menu.on_callback(event_obj)
    assert _images(replies.last) == ["good-photo"]


async def test_image_rejected_by_max_is_not_saved(db) -> None:
    """Картинку, которую MAX не может показать, бот не сохраняет."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["🖼 Картинка"])

    answers = Replies()

    async def answer(**kwargs: Any) -> None:
        if _images(kwargs):
            raise MaxApiError(code=400, raw={"code": "attachment.invalid"})
        await answers.answer(**kwargs)

    photo = FakeMessage(ADMIN, "", Replies(), image_token="bad")
    photo.message.answer = answer
    await editor.on_admin_input(photo)
    assert answers.last["text"].startswith("⚠️ MAX не принял")
    assert ADMIN in waiting
    async with db() as session:
        assert (await SectionRepository(session).root()).image_token is None


async def test_file_instead_of_photo_gets_explained(db) -> None:
    """Файл вместо фото: бот объясняет, а не показывает главное меню."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["🖼 Картинка"])

    file_msg = FakeMessage(ADMIN, "", Replies())
    file_msg.message.body.attachments = [
        SimpleNamespace(type=AttachmentType.FILE, payload=SimpleNamespace(token="f"))
    ]
    assert await editor.PendingInput()(file_msg)
    out = Replies()
    file_msg.message.answer = out.answer
    await editor.on_admin_input(file_msg)
    assert "как фото, не файлом" in out.last["text"]


async def test_caption_saved_as_text_warns_about_photo(db) -> None:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["📝 Текст"])
    saved = await send(ADMIN, "Новое приветствие", image_token="tok")
    assert "Картинку из сообщения я не сохранил" in saved.last["text"]


async def test_link_section_image_status_is_honest(db) -> None:
    async with db() as session:
        repo = SectionRepository(session)
        link = await repo.add((await repo.root()).id, "О комитете")
        link.url, link.image_token = "https://urt.volgograd.ru", "tok"
        await session.commit()
        text, _ = await editor.build_screen(repo, link)
    assert "сохранена, появится, если убрать ссылку" in text
