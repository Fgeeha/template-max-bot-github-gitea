"""Админка разделов: /admin в личке с ботом.

Экран раздела показывает его текст и подразделы; кнопки — добавить
подраздел, переименовать, сменить текст, картинку, задать ссылку, сдвинуть, удалить,
посмотреть глазами пользователя. Название и текст администратор присылает следующим
сообщением — бот ждёт ввода, пока не нажата любая кнопка админки.
"""

from __future__ import annotations

import logging
from typing import Any

from maxapi import Dispatcher, F
from maxapi.enums.chat_type import ChatType
from maxapi.exceptions.max import MaxApiError
from maxapi.filters.command import Command
from maxapi.filters.filter import BaseFilter
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot.db.models import Section
from bot.db.repositories import AuditRepository, SectionRepository
from bot.db.session import session_scope
from bot.handlers import tools
from bot.handlers.admin import admin_only, is_admin, user_id_of
from bot.handlers.inputs import (
    CLEAR,
    TITLE_MAX_LEN,
    attachments_of,
    image_token_of,
    parse_link,
    validate_text,
    validate_title,
)
from bot.handlers.menu import image_attachment, render_section, send_screen
from bot.handlers.pending import waiting
from bot.handlers.screens import SCREEN_TEXT_PREVIEW, audit_text, build_screen, name
from bot.keyboards.callbacks import AdminAction, AdminPayload, PayloadError
from bot.keyboards.menus import (
    MAX_CHILDREN,
    cancel_keyboard,
    confirm_delete_keyboard,
    link_keyboard,
)

logger = logging.getLogger(__name__)

# Кто какой ввод сейчас должен прислать (общее с инструментами, см. pending).
_pending = waiting
# Ввод, который приходит вложением, а не текстом.
_ATTACHMENT_INPUT = (AdminAction.IMAGE, AdminAction.IMPORT)


class PendingInput(BaseFilter):
    """Сообщение в личке — ожидаемый ввод админки (команды не перехватываем).

    Сообщения из групп не берём: иначе реплика админа в общем чате стала бы
    текстом раздела, а экран админки ушёл бы всем участникам.
    """

    async def __call__(self, event: Any) -> bool:
        user_id = user_id_of(event)
        pending = _pending.get(user_id) if user_id is not None else None
        if pending is None:
            return False
        if event.message.recipient.chat_type != ChatType.DIALOG:
            return False
        if not await is_admin(user_id):
            # Доступ отозвали, пока бот ждал ввода: забываем ожидание, иначе
            # все сообщения бывшего админа молча уходили бы в этот хендлер.
            _pending.pop(user_id, None)
            return False
        # Картинка приходит без текста — для неё вводом считается любое
        # вложение: фото сохранится, а на файл или стикер бот объяснит, что
        # нужна картинка, вместо того чтобы молча показать главное меню.
        if pending[0] in _ATTACHMENT_INPUT and attachments_of(event.message):
            return True
        body = event.message.body
        text = body.text if body else None
        if not text:
            return False
        return not text.startswith("/")


def register(dp: Dispatcher) -> None:
    dp.message_created(Command("admin"))(on_admin_command)
    dp.message_callback(F.callback.payload.startswith(f"{AdminPayload.prefix}:"))(on_admin_callback)
    dp.message_created(PendingInput())(on_admin_input)


@admin_only
async def on_admin_command(event: MessageCreated) -> None:
    # В группе экран админки увидели бы все участники.
    if event.message.recipient.chat_type != ChatType.DIALOG:
        return
    user_id = user_id_of(event)
    if user_id is not None:
        _pending.pop(user_id, None)
    async with session_scope() as session:
        repo = SectionRepository(session)
        text, keyboard = await build_screen(repo, await repo.root())
    await event.message.answer(text=text, attachments=[keyboard.as_markup()])


async def on_admin_callback(event: MessageCallback) -> None:
    user_id = user_id_of(event)
    if user_id is None or not await is_admin(user_id):
        await event.answer(notification="Недоступно")
        return
    try:
        payload = AdminPayload.unpack(event.callback.payload or "")
    except PayloadError:
        await event.answer(notification="Кнопка устарела, откройте /admin заново")
        return

    # Любая кнопка админки отменяет ожидание ввода.
    _pending.pop(user_id, None)

    if payload.action in tools.TOOL_ACTIONS:
        await tools.dispatch(event, payload.action, payload.target, user_id)
        return

    async with session_scope() as session:
        repo = SectionRepository(session)
        if payload.action is AdminAction.HOME:
            section: Section | None = await repo.root()
        else:
            section = await repo.get(payload.target)
        if section is None:
            await event.answer(notification="Раздел уже удалён, откройте /admin заново")
            return
        await _dispatch(event, repo, AuditRepository(session), section, payload.action, user_id)


async def _dispatch(
    event: MessageCallback,
    repo: SectionRepository,
    audit: AuditRepository,
    section: Section,
    action: AdminAction,
    user_id: int,
) -> None:
    """Выполняет действие кнопки админки внутри открытой транзакции."""
    notification: str | None = None

    if action is AdminAction.ADD:
        if len(await repo.children(section.id)) >= MAX_CHILDREN:
            await event.answer(notification=f"Не больше {MAX_CHILDREN} подразделов")
            return
        await _ask(
            event,
            user_id,
            action,
            section,
            f"Пришлите название нового подраздела в «{section.title}» "
            f"(это подпись кнопки, до {TITLE_MAX_LEN} символов).",
        )
        return

    if action is AdminAction.TITLE:
        await _ask(
            event,
            user_id,
            action,
            section,
            f"Сейчас: {section.title}\n\nПришлите новое название (до {TITLE_MAX_LEN} символов).",
        )
        return

    if action is AdminAction.TEXT:
        current = section.text.strip() or "— не задан —"
        await _ask(
            event,
            user_id,
            action,
            section,
            f"Сейчас:\n{current[:SCREEN_TEXT_PREVIEW]}\n\n"
            "Пришлите новый текст одним сообщением. Эмодзи и переносы строк сохраняются.",
        )
        return

    if action is AdminAction.IMAGE:
        current = "есть" if section.image_token else "нет"
        await _ask(
            event,
            user_id,
            action,
            section,
            f"Картинка сейчас: {current}.\n\n"
            f"Пришлите одну картинку как обычное фото — она будет над текстом раздела "
            f"«{section.title}». Из альбома возьму первую, подпись к фото не "
            f"сохраняется. Чтобы убрать картинку, пришлите «{CLEAR}».",
        )
        return

    if action is AdminAction.LINK:
        if section.parent_id is None:
            await event.answer(notification="У главного меню ссылки нет")
            return
        current = section.url or "— не задана —"
        await _ask(
            event,
            user_id,
            action,
            section,
            f"Сейчас: {current}\n\n"
            "Пришлите ссылку (https://…) — кнопка «"
            f"{section.title}» будет открывать её вместо текста.\n"
            f"Чтобы убрать ссылку, пришлите «{CLEAR}».",
        )
        return

    if action is AdminAction.DELETE:
        if section.parent_id is None:
            await event.answer(notification="Главное меню удалить нельзя")
            return
        nested = await repo.count_descendants(section.id)
        warning = f"\nВместе с ним удалятся вложенные разделы: {nested}." if nested else ""
        await event.answer(
            new_text=f"🗑 Удалить раздел «{section.title}»?{warning}\n\nОтменить удаление нельзя.",
            attachments=[confirm_delete_keyboard(section).as_markup()],
        )
        return

    if action is AdminAction.DELETE_CONFIRM:
        parent = await repo.get(section.parent_id) if section.parent_id else None
        if parent is None:
            await event.answer(notification="Главное меню удалить нельзя")
            return
        nested = await repo.count_descendants(section.id)
        await repo.delete(section.id)
        logger.info("admin %s удалил раздел %s «%s»", user_id, section.id, section.title)
        extra = f" вместе с вложенными ({nested})" if nested else ""
        await audit.log(user_id, f"удалил раздел {name(section)}{extra}")
        section, notification = parent, "Раздел удалён"

    elif action in (AdminAction.UP, AdminAction.DOWN):
        moved = await repo.move(section, -1 if action is AdminAction.UP else 1)
        notification = "Перемещено" if moved else "Дальше двигать некуда"
        if moved:
            where = "выше" if action is AdminAction.UP else "ниже"
            await audit.log(user_id, f"сдвинул {name(section)} {where}")

    elif action is AdminAction.PREVIEW:
        if section.url:
            # Экрана у раздела-ссылки нет — показываем саму кнопку, её можно нажать.
            text = f"У пользователя кнопка «{section.title}» сразу открывает ссылку:"
            attachments = [link_keyboard(section).as_markup()]
        else:
            text, attachments = render_section(section, await repo.children(section.id))
        await send_screen(event.message.answer, text, attachments)
        await event.answer(notification="Так раздел увидит пользователь — сообщение ниже")
        return

    # OPEN и всё, что после действия возвращается на экран раздела.
    text, keyboard = await build_screen(repo, section)
    await event.answer(notification=notification, new_text=text, attachments=[keyboard.as_markup()])


async def _ask(
    event: MessageCallback, user_id: int, action: AdminAction, section: Section, prompt: str
) -> None:
    """Переводит админа в ожидание ввода и показывает подсказку."""
    _pending[user_id] = (action, section.id)
    await event.answer(new_text=prompt, attachments=[cancel_keyboard(section.id).as_markup()])


async def _check_image(event: MessageCreated, token: str) -> str | None:
    """Присылает картинку админу: так MAX проверяет токен до сохранения.

    Без этой проверки отказ MAX всплыл бы только у пользователей, где меню
    молча показывается без картинки.
    """
    try:
        await event.message.answer(
            text="🖼 Так картинка будет выглядеть:", attachments=[image_attachment(token)]
        )
    except MaxApiError as exc:
        if exc.code >= 500:
            raise
        logger.warning("MAX не принял картинку из админки: %s", exc)
        return "MAX не принял эту картинку — пришлите другую."
    return None


async def on_admin_input(event: MessageCreated) -> None:
    """Название, текст, ссылка или картинка, присланные после кнопки админки."""
    user_id = user_id_of(event)
    if user_id is None or user_id not in _pending or not await is_admin(user_id):
        return
    action, section_id = _pending[user_id]
    if action in tools.INPUT_ACTIONS:
        await tools.handle_input(event, action, user_id)
        return
    raw = (event.message.body.text if event.message.body else None) or ""
    value = raw.strip()

    async with session_scope() as session:
        repo = SectionRepository(session)
        section = await repo.get(section_id)
        if section is None:
            _pending.pop(user_id, None)
            await event.message.answer(text="Раздел уже удалён. Откройте /admin заново.")
            return

        image: str | None = None
        if action is AdminAction.IMAGE:
            image = image_token_of(event.message)
            if image:
                error = await _check_image(event, image)
            elif value == CLEAR:
                error = None
            else:
                error = "Нужна картинка — пришлите её как фото, не файлом и не стикером."
        elif action is AdminAction.TEXT:
            error = validate_text(value)
        elif action is AdminAction.LINK:
            link, error = (None, None) if value == CLEAR else parse_link(value)
        else:
            error = validate_title(value)
        if (
            not error
            and action is AdminAction.ADD
            and len(await repo.children(section.id)) >= MAX_CHILDREN
        ):
            # Лимит проверяется и при нажатии «➕», но между нажатием и вводом
            # подраздел мог добавить другой админ.
            error = f"В разделе уже {MAX_CHILDREN} подразделов — больше MAX не покажет."
        if error:
            # Ожидание не снимаем: админ просто присылает исправленный вариант.
            await event.message.answer(
                text=f"⚠️ {error}", attachments=[cancel_keyboard(section.id).as_markup()]
            )
            return
        _pending.pop(user_id, None)

        old_title = section.title
        if action is AdminAction.ADD:
            section = await repo.add(section.id, value)
            done = (
                "Подраздел добавлен. Задайте ему текст кнопкой «📝 Текст» "
                "или сделайте кнопкой-ссылкой через «🔗 Ссылка»."
            )
        elif action is AdminAction.TITLE:
            section.title = value
            done = "Название сохранено."
        elif action is AdminAction.LINK:
            section.url = link
            done = "Ссылка сохранена." if section.url else "Ссылка убрана."
        elif action is AdminAction.IMAGE:
            section.image_token = image
            done = "Картинка сохранена." if image else "Картинка убрана."
        else:
            section.text = value
            done = "Текст сохранён."
            if image_token_of(event.message):
                done += " Картинку из сообщения я не сохранил — для неё есть «🖼 Картинка»."
        logger.info("admin %s: %s раздела %s", user_id, action.value, section.id)
        await AuditRepository(session).log(user_id, audit_text(action, section, old_title))
        text, keyboard = await build_screen(repo, section)

    await event.message.answer(text=f"✅ {done}\n\n{text}", attachments=[keyboard.as_markup()])
