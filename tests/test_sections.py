"""Дерево разделов: репозиторий, отображение и проверки ввода админки.

Репозиторий гоняется на SQLite в памяти (фикстура sessionmaker в conftest).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import Section
from bot.db.repositories import SectionRepository
from bot.handlers.inputs import TITLE_MAX_LEN, parse_link, validate_text, validate_title
from bot.handlers.menu import render_section
from bot.keyboards.menus import BACK_TEXT


@pytest.fixture
async def repo(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[SectionRepository]:
    async with sessionmaker() as session:
        yield SectionRepository(session)


async def _titles(repo: SectionRepository, parent: Section) -> list[str]:
    return [s.title for s in await repo.children(parent.id)]


async def test_root_created_once(repo: SectionRepository) -> None:
    first = await repo.root()
    assert first.parent_id is None
    assert (await repo.root()).id == first.id


async def test_add_appends_in_order(repo: SectionRepository) -> None:
    root = await repo.root()
    for title in ("Тарифы", "Техосмотр", "Эвакуация"):
        await repo.add(root.id, title)
    assert await _titles(repo, root) == ["Тарифы", "Техосмотр", "Эвакуация"]


async def test_move_up_and_down(repo: SectionRepository) -> None:
    root = await repo.root()
    a = await repo.add(root.id, "A")
    await repo.add(root.id, "B")
    c = await repo.add(root.id, "C")

    assert await repo.move(c, -1)
    assert await _titles(repo, root) == ["A", "C", "B"]
    assert await repo.move(a, 1)
    assert await _titles(repo, root) == ["C", "A", "B"]
    # Крайние позиции: двигать некуда, порядок не меняется.
    assert not await repo.move(c, -1)
    assert not await repo.move(root, 1)
    assert await _titles(repo, root) == ["C", "A", "B"]


async def test_delete_removes_branch(repo: SectionRepository) -> None:
    root = await repo.root()
    utilities = await repo.add(root.id, "Тарифы")
    water = await repo.add(utilities.id, "Вода")
    await repo.add(water.id, "Холодная")
    keep = await repo.add(root.id, "Техосмотр")

    assert await repo.count_descendants(utilities.id) == 2
    await repo.delete(utilities.id)
    assert await _titles(repo, root) == ["Техосмотр"]
    # Без каскада «Вода» осталась бы висеть с parent_id удалённого раздела.
    assert await repo.children(utilities.id) == []
    assert await repo.children(water.id) == []
    assert await repo.count_descendants(root.id) == 1
    assert await repo.get(keep.id) is not None


async def test_path_from_root(repo: SectionRepository) -> None:
    root = await repo.root()
    utilities = await repo.add(root.id, "Тарифы")
    water = await repo.add(utilities.id, "Вода")
    assert [s.title for s in await repo.path(water)] == ["Главное меню", "Тарифы", "Вода"]


def _button_texts(attachments: list[AttachmentButton]) -> list[str]:
    return [
        b.text
        for markup in attachments
        if hasattr(markup.payload, "buttons")
        for row in markup.payload.buttons
        for b in row
    ]


def test_leaf_renders_text_with_back_only() -> None:
    leaf = Section(id=5, parent_id=2, title="Холодное водоснабжение", text="💧 36,01 руб./м3")
    text, attachments = render_section(leaf, [])
    assert text == "💧 36,01 руб./м3"
    assert _button_texts(attachments) == [BACK_TEXT]


def test_root_has_no_back_button() -> None:
    root = Section(id=1, parent_id=None, title="Главное меню", text="Выберите раздел 👇")
    assert render_section(root, []) == ("Выберите раздел 👇", [])
    child = Section(id=2, parent_id=1, title="Техосмотр", text="")
    _, attachments = render_section(root, [child])
    assert _button_texts(attachments) == ["Техосмотр"]


def test_section_without_text_falls_back_to_title() -> None:
    """Пустое сообщение MAX не примет — показываем название раздела."""
    menu = Section(id=2, parent_id=1, title="Эвакуация или хранение", text="  ")
    child = Section(id=3, parent_id=2, title="Эвакуация", text="")
    text, attachments = render_section(menu, [child])
    assert text == "Эвакуация или хранение"
    # Подразделы сверху, «Назад» — последней строкой.
    assert _button_texts(attachments) == ["Эвакуация", BACK_TEXT]


def test_title_validation() -> None:
    assert validate_title("Техосмотр") is None
    assert validate_title("") is not None
    assert validate_title("x" * (TITLE_MAX_LEN + 1)) is not None


def test_text_validation() -> None:
    assert validate_text("Стоимость ТО – 378 руб") is None
    assert validate_text("x" * 4001) is not None


def test_link_child_renders_as_link_button() -> None:
    root = Section(id=1, parent_id=None, title="Главное меню", text="Выберите раздел 👇")
    link = Section(id=2, parent_id=1, title="О комитете", text="", url="https://urt.volgograd.ru")
    _, attachments = render_section(root, [link])
    (button,) = [
        b
        for markup in attachments
        if hasattr(markup.payload, "buttons")
        for row in markup.payload.buttons
        for b in row
    ]
    assert button.text == "О комитете"
    assert button.url == "https://urt.volgograd.ru"
    assert not hasattr(button, "payload") or button.payload is None


@pytest.mark.parametrize(
    "url",
    ["https://max.ru/id3444134770_gos/", "https://urt.volgograd.ru", "http://example.ru/a?b=1"],
)
def test_valid_urls(url: str) -> None:
    assert parse_link(url) == (url, None)


@pytest.mark.parametrize(
    "url",
    [
        "urt.volgograd.ru",
        "ftp://example.ru",
        "https://",
        "https://exa mple.ru",
        "javascript:alert(1)",
        "https://e.ru/" + "x" * 2048,
    ],
)
def test_invalid_urls(url: str) -> None:
    link, error = parse_link(url)
    assert link is None and error


def test_cyrillic_domain_becomes_punycode() -> None:
    assert parse_link("https://урт.рф/о-нас") == ("https://xn--p1aeb.xn--p1ai/о-нас", None)


def test_image_goes_above_keyboard() -> None:
    leaf = Section(id=5, parent_id=2, title="Техосмотр", text="Стоимость ТО", image_token="tok")
    _, attachments = render_section(leaf, [])
    assert [type(a).__name__ for a in attachments] == ["AttachmentUpload", "AttachmentButton"]
    assert attachments[0].payload.token == "tok"
