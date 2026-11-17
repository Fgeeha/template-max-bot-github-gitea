"""Навигация пользователя по разделам: кнопки и свободный текст."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Any

from maxapi import Dispatcher
from maxapi.enums.upload_type import UploadType
from maxapi.exceptions.max import MaxApiError
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Section
from bot.db.repositories import SectionRepository, StaffRepository, StatsRepository
from bot.db.repositories.stats import user_hash
from bot.db.session import session_scope
from bot.handlers.admin import is_owner, user_id_of
from bot.keyboards.callbacks import PayloadError, SectionPayload
from bot.keyboards.menus import section_keyboard

logger = logging.getLogger(__name__)

STALE_TEXT = "Раздел больше недоступен — открываю главное меню"

# Вложения экрана: картинка раздела (если есть) и клавиатура.
Attachments = list[AttachmentButton | AttachmentUpload]


def register(dp: Dispatcher) -> None:
    dp.message_callback()(on_callback)
    # Catch-all: регистрируется последним, иначе перехватит команды.
    dp.message_created()(on_free_text)


def render_section(section: Section, children: Sequence[Section]) -> tuple[str, Attachments]:
    """Сообщение раздела так, как его видит пользователь.

    Пустой текст MAX не отправит, поэтому без текста показываем название.
    """
    text = section.text.strip() or section.title
    keyboard = section_keyboard(section, children)
    attachments: Attachments = []
    if section.image_token:
        attachments.append(image_attachment(section.image_token))
    if keyboard:
        attachments.append(keyboard.as_markup())
    return text, attachments


async def load_root() -> tuple[str, Attachments]:
    """Главное меню: приветствие и кнопки разделов верхнего уровня.

    В статистику не попадает: меню показывается на любой текст, /start и
    устаревшую кнопку — считались бы ответы бота, а не интерес к разделам.
    Возврат в меню кнопкой «Назад» считается как обычный раздел.
    """
    async with session_scope() as session:
        repo = SectionRepository(session)
        root = await repo.root()
        return render_section(root, await repo.children(root.id))


async def load_section(
    section_id: int, viewer: int | None = None
) -> tuple[str, Attachments] | None:
    """Сообщение раздела; None — раздела нет (удалён в админке)."""
    async with session_scope() as session:
        repo = SectionRepository(session)
        section = await repo.get(section_id)
        if section is None:
            return None
        if section.url:
            # Старая кнопка раздела, который админ сделал ссылкой: его текст и
            # подразделы скрыты — показываем экран, где лежит его кнопка-ссылка.
            parent = await repo.get(section.parent_id) if section.parent_id else None
            section = parent or await repo.root()
        await count_view(session, section.id, viewer)
        return render_section(section, await repo.children(section.id))


async def count_view(session: AsyncSession, section_id: int, viewer: int | None) -> None:
    """Пишет открытие раздела в статистику; администраторов не считает."""
    settings = get_settings()
    if not settings.stats_enabled or viewer is None or is_owner(viewer):
        return
    if await StaffRepository(session).exists(viewer):
        return
    salt = settings.stats_salt or settings.max_bot_token
    await StatsRepository(session).record(section_id, user_hash(viewer, salt))


def image_attachment(token: str) -> AttachmentUpload:
    """Картинка по токену MAX — повторная отправка уже загруженного фото."""
    return AttachmentUpload(type=UploadType.IMAGE, payload=AttachmentPayload(token=token))


def without_image(attachments: Attachments) -> Attachments:
    """Те же вложения без картинки раздела."""
    return [a for a in attachments if not isinstance(a, AttachmentUpload)]


async def send_screen(
    send: Callable[..., Awaitable[Any]], text: str, attachments: Attachments
) -> None:
    """Отправляет экран; если MAX не принял картинку (4xx) — без неё.

    Картинку MAX проверяет при сохранении в админке, но токен может
    перестать действовать и позже. Отказ из-за картинки не должен ломать
    меню: пользователь получит текст и кнопки, в лог — предупреждение.
    """
    try:
        await send(text=text, attachments=attachments)
    except MaxApiError as exc:
        plain = without_image(attachments)
        if exc.code >= 500 or plain == attachments:
            raise
        logger.warning("MAX не принял картинку раздела, отправляю без неё: %s", exc)
        await send(text=text, attachments=plain)


async def send_root(event: MessageCreated) -> None:
    """Главное меню в ответ на сообщение."""
    text, attachments = await load_root()
    await send_screen(event.message.answer, text, attachments)


async def show_in_place(
    event: MessageCallback,
    text: str,
    attachments: Attachments,
    notification: str | None = None,
) -> None:
    """Заменяет сообщение с нажатой кнопкой новым экраном — чат не растёт.

    Пустой список вложений убирает клавиатуру (None оставил бы старую).
    Правка и подтверждение нажатия — один вызов MAX, поэтому при неудаче
    нажатие подтверждаем отдельно, иначе кнопка «зависнет» и пропадёт
    уведомление. Новое сообщение — только когда править нечего или MAX
    отказал (4xx). На 5xx maxapi уже повторял запрос и правка могла пройти —
    второе сообщение засорило бы чат. Сетевые ошибки не ловим: запасная
    отправка упала бы так же.
    """
    try:

        async def edit(*, text: str, attachments: Attachments) -> None:
            await event.answer(notification=notification, new_text=text, attachments=attachments)

        # Отказ мог быть из-за картинки — send_screen повторит правку без неё.
        # Если и без картинки не вышло, ниже уйдёт новое сообщение с исходными
        # вложениями: картинка могла быть ни при чём (например, старое сообщение).
        await send_screen(edit, text, attachments)
        return
    except ValueError:
        # maxapi: исходного сообщения нет — править нечего.
        logger.info("Нечего править, отправляю экран новым сообщением")
    except MaxApiError as exc:
        if exc.code >= 500:
            logger.warning("MAX не ответил на правку сообщения: %s", exc)
            return
        logger.info("MAX отказал в правке сообщения, отправляю новое: %s", exc)

    try:
        await event.ack(notification=notification)
    except MaxApiError as exc:
        logger.info("Не удалось подтвердить нажатие: %s", exc)
    if event.message is not None:
        await send_screen(event.message.answer, text, attachments)
    else:
        await send_screen(
            partial(event.bot.send_message, user_id=event.callback.user.user_id),
            text,
            attachments,
        )


async def on_callback(event: MessageCallback) -> None:
    """Нажатие кнопки раздела: экран меняется в том же сообщении."""
    payload = event.callback.payload or ""
    viewer = user_id_of(event)
    try:
        view = await load_section(SectionPayload.unpack(payload).section_id, viewer)
    except PayloadError:
        # Payload из старой версии клавиатуры или подделанный.
        logger.info("Неизвестный payload callback: %r", payload)
        view = None
    notification = None
    if view is None:
        # Раздел (или вся ветка вместе с ним) удалён в админке, а кнопка — в
        # том числе «Назад» — осталась в старом сообщении. Не оставляем
        # пользователя в тупике: сразу даём главное меню.
        notification = STALE_TEXT
        view = await load_root()
    text, attachments = view
    await show_in_place(event, text, attachments, notification)


async def on_free_text(event: MessageCreated) -> None:
    """На произвольный текст в личке — главное меню."""
    from maxapi.enums.chat_type import ChatType

    # В группах на каждое сообщение не отвечаем: бот превратился бы в спамера.
    if event.message.recipient.chat_type != ChatType.DIALOG:
        return
    await send_root(event)
