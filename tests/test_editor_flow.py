"""Сценарий админки целиком: добавить раздел, задать текст, увидеть, удалить.

Хендлеры вызываются напрямую с заглушками событий MAX; БД — SQLite в памяти
(фикстура sessionmaker в conftest) вместо Postgres.
"""

from __future__ import annotations

from maxapi.enums.chat_type import ChatType
from maxapi.exceptions.max import MaxApiError

from bot.db.repositories import SectionRepository
from bot.handlers import editor, menu
from bot.handlers.inputs import CLEAR, TITLE_MAX_LEN
from bot.handlers.pending import waiting
from bot.keyboards.callbacks import AdminAction, AdminPayload, SectionPayload
from bot.keyboards.menus import BACK_TEXT
from tests.fakes import (
    ADMIN,
    STRANGER,
    FailingEdit,
    FakeMessage,
    Replies,
    buttons,
    navigate,
    press,
    send,
)


async def test_admin_builds_section_and_user_sees_it(db) -> None:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    add_payload = buttons(replies.last)["➕ Добавить подраздел"]

    _, edits = await press(ADMIN, add_payload)
    assert "название" in edits.last["new_text"]
    added = await send(ADMIN, "Техосмотр")
    assert "Подраздел добавлен" in added.last["text"]

    _, edits = await press(ADMIN, buttons(added.last)["📝 Текст"])
    saved = await send(ADMIN, "🛠️ Мототранспорт\nСтоимость ТО – 378 руб")
    assert "Текст сохранён" in saved.last["text"]

    # Пользователь: главное меню → кнопка → текст без кнопок.
    root = await send(STRANGER, "привет")
    assert root.last["text"] == "Выберите раздел 👇"
    screen = await navigate(STRANGER, buttons(root.last)["Техосмотр"])
    assert screen["text"] == "🛠️ Мототранспорт\nСтоимость ТО – 378 руб"
    # Под текстом только «Назад»; она возвращает в главное меню.
    assert list(buttons(screen)) == [BACK_TEXT]
    back = await navigate(STRANGER, buttons(screen)[BACK_TEXT])
    assert back["text"] == "Выберите раздел 👇"

    # Удаление с подтверждением; старая кнопка у пользователя гаснет.
    _, edits = await press(ADMIN, buttons(saved.last)["🗑 Удалить"])
    _, edits = await press(ADMIN, buttons(edits.last)["✅ Да, удалить"])
    assert edits.last["notification"] == "Раздел удалён"
    stale = await navigate(STRANGER, buttons(root.last)["Техосмотр"])
    assert stale["notification"] == menu.STALE_TEXT
    assert stale["text"] == "Выберите раздел 👇"


async def test_invalid_title_keeps_waiting(db) -> None:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["➕ Добавить подраздел"])

    error = await send(ADMIN, "x" * (TITLE_MAX_LEN + 1))
    assert error.last["text"].startswith("⚠️")
    ok = await send(ADMIN, "Тарифы")
    assert "Подраздел добавлен" in ok.last["text"]


async def test_stranger_cannot_use_admin(db) -> None:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(STRANGER, "/admin", replies))
    assert replies.items == []

    payload = AdminPayload(action=AdminAction.ADD, target=1).pack()
    _, edits = await press(STRANGER, payload)
    assert edits.last == {"notification": "Недоступно"}
    assert STRANGER not in waiting


async def test_command_is_not_swallowed_as_input(db) -> None:
    """/start во время ожидания ввода — команда, а не название раздела."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["➕ Добавить подраздел"])
    assert not await editor.PendingInput()(FakeMessage(ADMIN, "/start", Replies()))


async def test_unknown_section_payload_is_stale(db) -> None:
    stale = await navigate(STRANGER, SectionPayload(section_id=999).pack())
    assert stale["notification"] == menu.STALE_TEXT
    assert stale["text"] == "Выберите раздел 👇"


async def test_group_message_is_not_taken_as_input(db) -> None:
    """Реплика админа в группе не должна стать текстом раздела."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["➕ Добавить подраздел"])
    group_message = FakeMessage(ADMIN, "всем привет", Replies(), chat_type=ChatType.CHAT)
    assert not await editor.PendingInput()(group_message)


async def test_children_limit_checked_when_title_arrives(db) -> None:
    """Лимит кнопок проверяется и при сохранении: другой админ мог успеть добавить."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["➕ Добавить подраздел"])

    async with db() as session:
        repo = SectionRepository(session)
        root = await repo.root()
        for i in range(editor.MAX_CHILDREN):
            await repo.add(root.id, f"Раздел {i}")
        await session.commit()

    error = await send(ADMIN, "Лишний")
    assert error.last["text"].startswith("⚠️")
    async with db() as session:
        repo = SectionRepository(session)
        assert len(await repo.children((await repo.root()).id)) == editor.MAX_CHILDREN


async def test_back_returns_to_previous_step(db) -> None:
    """Главное меню → раздел → подраздел → «Назад» → снова выбор подраздела."""
    async with db() as session:
        repo = SectionRepository(session)
        root = await repo.root()
        evacuation = await repo.add(root.id, "Эвакуация и хранение")
        evacuation.text = "Эвакуация или хранение?"
        storage = await repo.add(evacuation.id, "Хранение")
        storage.text = "▪️ хранение категории А - 39,53 руб."
        await session.commit()

    root_reply = await send(STRANGER, "привет")
    choice = await navigate(STRANGER, buttons(root_reply.last)["Эвакуация и хранение"])
    assert list(buttons(choice)) == ["Хранение", BACK_TEXT]

    leaf = await navigate(STRANGER, buttons(choice)["Хранение"])
    back = await navigate(STRANGER, buttons(leaf)[BACK_TEXT])
    assert back["text"] == "Эвакуация или хранение?"
    assert list(buttons(back)) == ["Хранение", BACK_TEXT]

    home = await navigate(STRANGER, buttons(back)[BACK_TEXT])
    assert home["text"] == "Выберите раздел 👇"
    assert list(buttons(home)) == ["Эвакуация и хранение"]


async def test_foreign_payload_falls_back_to_root(db) -> None:
    stale = await navigate(STRANGER, "menu:about")
    assert stale["notification"] == menu.STALE_TEXT
    assert stale["text"] == "Выберите раздел 👇"


async def test_refused_edit_falls_back_to_new_message(db) -> None:
    """MAX отказал в правке (4xx): нажатие подтверждено, экран пришёл новым."""
    stub = FailingEdit(MaxApiError(code=400, raw="edit refused"))
    await menu.on_callback(stub.event)
    assert stub.acks.last == {"notification": menu.STALE_TEXT}
    assert stub.replies.last["text"] == "Выберите раздел 👇"


async def test_no_original_message_sends_to_user(db) -> None:
    """Исходного сообщения нет — пишем пользователю напрямую."""
    stub = FailingEdit(ValueError("исходное сообщение отсутствует"), message=False)
    await menu.on_callback(stub.event)
    assert stub.sent.last["user_id"] == STRANGER
    assert stub.sent.last["text"] == "Выберите раздел 👇"


async def test_server_error_does_not_duplicate(db) -> None:
    """5xx: правка могла пройти — второе сообщение не шлём."""
    stub = FailingEdit(MaxApiError(code=502, raw="bad gateway"))
    await menu.on_callback(stub.event)
    assert stub.replies.items == [] and stub.sent.items == [] and stub.acks.items == []


async def test_admin_makes_link_button(db) -> None:
    """Админ превращает раздел в кнопку-ссылку и обратно."""
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    await press(ADMIN, buttons(replies.last)["➕ Добавить подраздел"])
    added = await send(ADMIN, "О комитете")

    _, edits = await press(ADMIN, buttons(added.last)["🔗 Ссылка"])
    assert "Пришлите ссылку" in edits.last["new_text"]
    bad = await send(ADMIN, "urt.volgograd.ru")
    assert bad.last["text"].startswith("⚠️")
    saved = await send(ADMIN, "https://urt.volgograd.ru")
    assert "Ссылка сохранена" in saved.last["text"]
    assert "🔗 Кнопка открывает ссылку: https://urt.volgograd.ru" in saved.last["text"]

    # У пользователя — link-кнопка с адресом, а не callback.
    root = await send(STRANGER, "привет")
    assert buttons(root.last)["О комитете"] == "https://urt.volgograd.ru"
    # В админке раздел-ссылка помечен и открывается экраном правки.
    admin_root = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", admin_root))
    assert AdminPayload.matches(buttons(admin_root.last)["🔗 О комитете"])

    _, _ = await press(ADMIN, buttons(saved.last)["🔗 Ссылка"])
    cleared = await send(ADMIN, CLEAR)
    assert "Ссылка убрана" in cleared.last["text"]
    root = await send(STRANGER, "привет")
    assert SectionPayload.matches(buttons(root.last)["О комитете"])


async def test_root_has_no_link_action(db) -> None:
    replies = Replies()
    await editor.on_admin_command(FakeMessage(ADMIN, "/admin", replies))
    assert "🔗 Ссылка" not in buttons(replies.last)


async def test_stale_button_of_link_section_shows_parent(db) -> None:
    """Старая кнопка раздела, ставшего ссылкой, не открывает его скрытый текст."""
    async with db() as session:
        repo = SectionRepository(session)
        root = await repo.root()
        about = await repo.add(root.id, "О комитете")
        about.text = "скрытый текст"
        await session.commit()
        about_id = about.id

    old_menu = await send(STRANGER, "привет")
    old_payload = buttons(old_menu.last)["О комитете"]
    async with db() as session:
        section = await SectionRepository(session).get(about_id)
        section.url = "https://urt.volgograd.ru"
        await session.commit()

    screen = await navigate(STRANGER, old_payload)
    assert screen["text"] == "Выберите раздел 👇"
    assert buttons(screen)["О комитете"] == "https://urt.volgograd.ru"


async def test_preview_of_link_section_shows_link_button(db) -> None:
    async with db() as session:
        repo = SectionRepository(session)
        root = await repo.root()
        link = await repo.add(root.id, "О комитете")
        link.url = "https://urt.volgograd.ru"
        await session.commit()
        link_id = link.id

    replies, _ = await press(ADMIN, AdminPayload(action=AdminAction.PREVIEW, target=link_id).pack())
    assert "сразу открывает ссылку" in replies.last["text"]
    assert buttons(replies.last) == {"О комитете": "https://urt.volgograd.ru"}


async def test_link_input_crash_guard(db) -> None:
    """Невалидный адрес вроде http://[ не роняет обработчик, ожидание остаётся."""
    async with db() as session:
        repo = SectionRepository(session)
        link_id = (await repo.add((await repo.root()).id, "Сайт")).id
        await session.commit()
    await press(ADMIN, AdminPayload(action=AdminAction.LINK, target=link_id).pack())
    error = await send(ADMIN, "http://[")
    assert error.last["text"].startswith("⚠️")
    assert ADMIN in waiting
