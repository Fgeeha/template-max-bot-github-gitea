"""Инструменты главного экрана админки.

👥 администраторы (добавляет и отзывает только владелец из ADMIN_IDS),
📊 статистика открытий разделов, 📦 выгрузка и загрузка дерева разделов
JSON-файлом, 📜 журнал изменений. Вызываются из bot.handlers.editor: там
общая проверка прав и разбор payload.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from maxapi.types.input_media import InputMedia
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.repositories import (
    AuditRepository,
    SectionRepository,
    StaffRepository,
    StatsRepository,
)
from bot.db.session import session_scope
from bot.handlers.admin import is_owner
from bot.handlers.inputs import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    IMPORT_MAX_BYTES,
    file_of,
    parse_tree,
    parse_user_id,
)
from bot.handlers.pending import waiting
from bot.handlers.screens import build_screen
from bot.keyboards.callbacks import AdminAction
from bot.keyboards.menus import (
    STATS_PERIODS,
    cancel_keyboard,
    confirm_staff_delete_keyboard,
    home_row,
    staff_keyboard,
    stats_keyboard,
    transfer_keyboard,
)
from bot.runtime import build_ssl_context

logger = logging.getLogger(__name__)

TOOL_ACTIONS = frozenset(
    {
        AdminAction.STAFF,
        AdminAction.STAFF_ADD,
        AdminAction.STAFF_DEL,
        AdminAction.STAFF_DEL_CONFIRM,
        AdminAction.STATS,
        AdminAction.TRANSFER,
        AdminAction.EXPORT,
        AdminAction.IMPORT,
        AdminAction.LOG,
    }
)
# Действия, после которых бот ждёт следующее сообщение администратора.
INPUT_ACTIONS = frozenset({AdminAction.STAFF_ADD, AdminAction.IMPORT})
OWNER_ONLY = frozenset(
    {AdminAction.STAFF_ADD, AdminAction.STAFF_DEL, AdminAction.STAFF_DEL_CONFIRM}
)

LOG_LIMIT = 30
STATS_TOP = 20


def local_time(moment: datetime, fmt: str = "%d.%m %H:%M") -> str:
    """Время для админа со смещением DISPLAY_UTC_OFFSET (naive из SQLite — это UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    zone = timezone(timedelta(hours=get_settings().display_utc_offset))
    return moment.astimezone(zone).strftime(fmt)


async def dispatch(event: MessageCallback, action: AdminAction, arg: int, user_id: int) -> None:
    """Кнопка инструмента; права администратора уже проверены."""
    if action in OWNER_ONLY and not is_owner(user_id):
        await event.answer(notification="Только для владельца (ADMIN_IDS)")
        return

    if action is AdminAction.STAFF_ADD:
        waiting[user_id] = (action, 0)
        await event.answer(
            new_text=(
                "Пришлите числовой MAX user ID нового администратора.\n\n"
                "Узнать его: пусть человек напишет боту /id."
            ),
            attachments=[cancel_keyboard(action=AdminAction.STAFF).as_markup()],
        )
        return

    if action is AdminAction.STAFF_DEL:
        await event.answer(
            new_text=f"🚫 Отозвать доступ к админке у {arg}?",
            attachments=[confirm_staff_delete_keyboard(arg).as_markup()],
        )
        return

    if action is AdminAction.EXPORT:
        await _send_export(event, "⬇️ Разделы бота. Загрузить обратно — «📦 Файл → ⬆️ Загрузить».")
        await event.answer(notification="Файл — сообщением ниже")
        return

    if action is AdminAction.IMPORT:
        # Копия текущего дерева — до замены: откатиться можно, загрузив её.
        await _send_export(event, "💾 Резервная копия текущих разделов — на случай отката.")
        waiting[user_id] = (action, 0)
        await event.answer(
            new_text=(
                "⬆️ Пришлите JSON-файл экспорта (файлом, не текстом).\n\n"
                "⚠️ Все разделы заменятся разделами из файла. Старые кнопки в "
                "чатах пользователей перестанут вести в разделы, статистика "
                "по ним уйдёт в «удалённые разделы». Копия текущих — выше."
            ),
            attachments=[cancel_keyboard(action=AdminAction.TRANSFER).as_markup()],
        )
        return

    notification = None
    async with session_scope() as session:
        if action is AdminAction.STAFF_DEL_CONFIRM:
            removed = await StaffRepository(session).remove(arg)
            if removed:
                await AuditRepository(session).log(user_id, f"отозвал администратора {arg}")
                logger.info("owner %s отозвал администратора %s", user_id, arg)
            notification = "Доступ отозван" if removed else "Его уже нет в списке"
            action = AdminAction.STAFF
        text, keyboard = await _screen(session, action, arg, user_id)
    await event.answer(notification=notification, new_text=text, attachments=[keyboard.as_markup()])


async def _screen(
    session: AsyncSession, action: AdminAction, arg: int, user_id: int
) -> tuple[str, InlineKeyboardBuilder]:
    """Текст и клавиатура экрана инструмента."""
    if action is AdminAction.STAFF:
        return await _staff_screen(session, user_id)
    if action is AdminAction.STATS:
        return await _stats_screen(session, arg)
    if action is AdminAction.LOG:
        entries = await AuditRepository(session).recent(LOG_LIMIT)
        lines = [f"📜 Последние изменения (до {LOG_LIMIT})", ""]
        lines += [f"{local_time(e.created_at)} · {e.user_id} · {e.details}" for e in entries]
        if not entries:
            lines.append("Изменений пока не было.")
        return "\n".join(lines), home_row(InlineKeyboardBuilder())
    text = (
        "📦 Разделы файлом\n\n"
        "⬇️ Скачать — всё дерево разделов (тексты, ссылки, картинки) JSON-файлом: "
        "резервная копия или перенос в другого бота на этом шаблоне.\n"
        "⬆️ Загрузить — заменить все разделы разделами из такого файла.\n\n"
        "Картинки в файле — токены MAX: в другом боте они могут не открыться, "
        "тогда раздел покажется без картинки."
    )
    return text, transfer_keyboard()


async def _staff_screen(session: AsyncSession, user_id: int) -> tuple[str, InlineKeyboardBuilder]:
    staff = await StaffRepository(session).all()
    owners = ", ".join(str(i) for i in sorted(get_settings().admin_ids_set)) or "—"
    lines = ["👥 Администраторы", "", f"Владельцы (ADMIN_IDS в .env): {owners}", ""]
    if staff:
        lines.append("Добавлены через админку:")
        lines += [f"• {s.user_id} — с {local_time(s.created_at, '%d.%m.%Y')}" for s in staff]
    else:
        lines.append("Через админку никого не добавляли.")
    can_edit = is_owner(user_id)
    if not can_edit:
        lines += ["", "Добавлять и отзывать администраторов может только владелец."]
    return "\n".join(lines), staff_keyboard([s.user_id for s in staff], can_edit)


async def _stats_screen(session: AsyncSession, days: int) -> tuple[str, InlineKeyboardBuilder]:
    if days not in STATS_PERIODS:
        days = STATS_PERIODS[1]
    report = await StatsRepository(session).report(days, STATS_TOP)
    lines = [f"📊 Статистика за {days} дн.", ""]
    if not get_settings().stats_enabled:
        lines += ["⚠️ Сбор выключен (STATS_ENABLED=false в .env).", ""]
    lines += [f"Открытий разделов: {report.opens}", f"Пользователей: {report.users}", ""]
    if report.top:
        lines.append("Популярные разделы (открытий / пользователей):")
        for index, item in enumerate(report.top, 1):
            title = item.title or "удалённые разделы"
            lines.append(f"{index}. {title} — {item.opens} / {item.users}")
    lines += ["", "Нажатия администраторов не учитываются."]
    return "\n".join(lines), stats_keyboard()


async def _send_export(event: MessageCallback, caption: str) -> None:
    """Отправляет дерево разделов файлом под сообщением с кнопкой."""
    async with session_scope() as session:
        tree = await SectionRepository(session).export_tree()
    now = datetime.now(UTC)
    doc = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": now.isoformat(timespec="seconds"),
        "root": tree,
    }
    # У буфера maxapi подбирает расширение по сигнатуре, у файла с диска берёт
    # имя как есть — поэтому через временный файл.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"sections-{now:%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        media = [InputMedia(path=str(path))]
        if event.message is not None:
            await event.message.answer(text=caption, attachments=media)
        else:
            # Исходное сообщение с кнопкой недоступно — пишем админу напрямую.
            user_id = event.callback.user.user_id
            await event.bot.send_message(user_id=user_id, text=caption, attachments=media)


async def download(url: str) -> bytes:
    """Скачивает присланный файл; больше IMPORT_MAX_BYTES не читает.

    Упрощение: адрес не проверяется на внутренние сети — его выдаёт MAX, а
    файл присылает только администратор. Для недоверенных отправителей нужна
    проверка, что хост не резолвится во внутренние сети.
    """
    if not url.startswith("https://"):
        msg = "MAX прислал файл не по https"
        raise ValueError(msg)
    ssl_context = build_ssl_context(get_settings().max_ca_bundle)
    timeout = aiohttp.ClientTimeout(total=60)
    async with (
        aiohttp.ClientSession(timeout=timeout) as http,
        http.get(url, ssl=ssl_context or True) as resp,
    ):
        resp.raise_for_status()
        data = bytearray()
        async for chunk in resp.content.iter_chunked(65536):
            data += chunk
            # +1 байт сверх предела достаточно, чтобы parse_tree отказал по размеру.
            if len(data) > IMPORT_MAX_BYTES:
                break
        return bytes(data)


async def handle_input(event: MessageCreated, action: AdminAction, user_id: int) -> None:
    """Сообщение администратора в ответ на STAFF_ADD или IMPORT."""
    if action is AdminAction.STAFF_ADD:
        await _input_staff(event, user_id)
    else:
        await _input_import(event, user_id)


async def _input_staff(event: MessageCreated, user_id: int) -> None:
    raw = ((event.message.body.text if event.message.body else None) or "").strip()
    new_id, error = parse_user_id(raw)
    if new_id is not None and is_owner(new_id):
        error = "Это владелец из ADMIN_IDS — у него и так есть доступ."
    if error or new_id is None:
        retry = cancel_keyboard(action=AdminAction.STAFF).as_markup()
        await event.message.answer(text=f"⚠️ {error}", attachments=[retry])
        return
    waiting.pop(user_id, None)
    async with session_scope() as session:
        added = await StaffRepository(session).add(new_id, added_by=user_id)
        if added:
            await AuditRepository(session).log(user_id, f"добавил администратора {new_id}")
            logger.info("owner %s добавил администратора %s", user_id, new_id)
        text, keyboard = await _staff_screen(session, user_id)
    done = "Администратор добавлен." if added else "Он уже администратор."
    await event.message.answer(text=f"✅ {done}\n\n{text}", attachments=[keyboard.as_markup()])


async def _input_import(event: MessageCreated, user_id: int) -> None:
    retry = cancel_keyboard(action=AdminAction.TRANSFER).as_markup()
    attachment = file_of(event.message)
    if attachment is None:
        await event.message.answer(
            text="⚠️ Нужен JSON-файл — пришлите его вложением-файлом.", attachments=[retry]
        )
        return
    try:
        data = await download(attachment.payload.url)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        # В лог — только тип ошибки: в URL вложения бывает токен доступа.
        logger.warning("Не удалось скачать файл импорта: %s", type(exc).__name__)
        await event.message.answer(
            text="⚠️ Не удалось скачать файл. Пришлите его ещё раз.", attachments=[retry]
        )
        return
    tree, error = parse_tree(data)
    if error or tree is None:
        await event.message.answer(text=f"⚠️ {error}", attachments=[retry])
        return
    waiting.pop(user_id, None)

    name = getattr(attachment, "filename", None) or "без имени"
    async with session_scope() as session:
        repo = SectionRepository(session)
        root = await repo.replace_tree(tree)
        await AuditRepository(session).log(user_id, f"загрузил разделы из файла «{name}»")
        logger.info("admin %s заменил дерево разделов из файла", user_id)
        text, keyboard = await build_screen(repo, root)
    await event.message.answer(
        text=f"✅ Разделы загружены.\n\n{text}", attachments=[keyboard.as_markup()]
    )
