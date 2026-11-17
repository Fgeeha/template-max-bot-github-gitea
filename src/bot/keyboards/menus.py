"""Сборка клавиатур из дерева разделов.

Разделы хранятся в БД (`bot.db.models.Section`) и правятся через админку,
поэтому клавиатуры строятся по переданным разделам, а не по константам.
"""

from __future__ import annotations

from collections.abc import Sequence

from maxapi.types.attachments.buttons.callback_button import CallbackButton
from maxapi.types.attachments.buttons.link_button import LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.db.models import Section
from bot.keyboards.callbacks import AdminAction, AdminPayload, SectionPayload

# Периоды отчёта статистики, дней.
STATS_PERIODS = (7, 30, 90)
STATS_DEFAULT_DAYS = 30

# Клавиатура MAX вмещает до 30 рядов. Под кнопки админки уходит до 6 рядов,
# у пользователя — один ряд «Назад»; остальное отдаём подразделам.
MAX_CHILDREN = 24
BACK_TEXT = "◀️ Назад"


def section_keyboard(section: Section, children: Sequence[Section]) -> InlineKeyboardBuilder | None:
    """Кнопки подразделов, каждая своей строкой, и «Назад» к родителю.

    «Назад» — обычная кнопка раздела-родителя (`s:<parent_id>`), поэтому
    отдельный обработчик не нужен. У главного меню её нет; None — кнопок нет
    совсем.
    """
    if not children and section.parent_id is None:
        return None
    keyboard = InlineKeyboardBuilder()
    for child in children:
        if child.url:
            # Ссылку открывает клиент MAX — бот нажатия не получает.
            keyboard.row(LinkButton(text=child.title, url=child.url))
        else:
            keyboard.row(
                CallbackButton(text=child.title, payload=SectionPayload(section_id=child.id).pack())
            )
    if section.parent_id is not None:
        keyboard.row(
            CallbackButton(
                text=BACK_TEXT, payload=SectionPayload(section_id=section.parent_id).pack()
            )
        )
    return keyboard


def link_keyboard(section: Section) -> InlineKeyboardBuilder:
    """Одна кнопка-ссылка раздела — для предпросмотра в админке."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(LinkButton(text=section.title, url=section.url))
    return keyboard


def _button(text: str, action: AdminAction, target: int = 0) -> CallbackButton:
    return CallbackButton(text=text, payload=AdminPayload(action=action, target=target).pack())


def admin_keyboard(section: Section, children: Sequence[Section]) -> InlineKeyboardBuilder:
    """Экран раздела в админке: подразделы и действия над разделом."""
    keyboard = InlineKeyboardBuilder()
    for child in children:
        # В админке и раздел-ссылка открывается экраном правки, а не сайтом.
        title = f"🔗 {child.title}" if child.url else child.title
        keyboard.row(_button(title[:64], AdminAction.OPEN, child.id))

    is_root = section.parent_id is None
    keyboard.row(_button("➕ Добавить подраздел", AdminAction.ADD, section.id))
    if is_root:
        keyboard.row(
            _button("📝 Текст", AdminAction.TEXT, section.id),
            _button("🖼 Картинка", AdminAction.IMAGE, section.id),
        )
        # Инструменты — одним рядом: 24 подраздела + 4 ряда корня = 28 из 30.
        keyboard.row(
            _button("👥 Админы", AdminAction.STAFF),
            _button("📊 Статистика", AdminAction.STATS, STATS_DEFAULT_DAYS),
            _button("📦 Файл", AdminAction.TRANSFER),
            _button("📜 Журнал", AdminAction.LOG),
        )
    else:
        # Все правки — одним рядом: при 24 подразделах рядов ровно 30, предел MAX.
        keyboard.row(
            _button("✏️ Название", AdminAction.TITLE, section.id),
            _button("📝 Текст", AdminAction.TEXT, section.id),
            _button("🖼 Картинка", AdminAction.IMAGE, section.id),
            _button("🔗 Ссылка", AdminAction.LINK, section.id),
        )
        keyboard.row(
            _button("⬆️ Выше", AdminAction.UP, section.id),
            _button("⬇️ Ниже", AdminAction.DOWN, section.id),
        )
    keyboard.row(_button("👁 Как видит пользователь", AdminAction.PREVIEW, section.id))
    if not is_root:
        keyboard.row(_button("🗑 Удалить", AdminAction.DELETE, section.id))
        keyboard.row(_button(BACK_TEXT, AdminAction.OPEN, section.parent_id))
    return keyboard


def confirm_delete_keyboard(section: Section) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        _button("✅ Да, удалить", AdminAction.DELETE_CONFIRM, section.id),
        _button("❌ Отмена", AdminAction.OPEN, section.id),
    )
    return keyboard


def cancel_keyboard(
    section_id: int = 0, action: AdminAction = AdminAction.OPEN
) -> InlineKeyboardBuilder:
    """Кнопка отмены ввода: возвращает на экран и снимает ожидание."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(_button("❌ Отмена", action, section_id))
    return keyboard


def home_row(keyboard: InlineKeyboardBuilder) -> InlineKeyboardBuilder:
    """Добавляет «Назад» на главный экран админки."""
    keyboard.row(_button(BACK_TEXT, AdminAction.HOME))
    return keyboard


def staff_keyboard(staff_ids: Sequence[int], can_edit: bool) -> InlineKeyboardBuilder:
    """Список администраторов; править его может только владелец."""
    keyboard = InlineKeyboardBuilder()
    if can_edit:
        for user_id in staff_ids[:MAX_CHILDREN]:
            keyboard.row(_button(f"🗑 {user_id}", AdminAction.STAFF_DEL, user_id))
        keyboard.row(_button("➕ Добавить администратора", AdminAction.STAFF_ADD))
    return home_row(keyboard)


def confirm_staff_delete_keyboard(user_id: int) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        _button("✅ Да, отозвать", AdminAction.STAFF_DEL_CONFIRM, user_id),
        _button("❌ Отмена", AdminAction.STAFF),
    )
    return keyboard


def stats_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(*(_button(f"{d} дн.", AdminAction.STATS, d) for d in STATS_PERIODS))
    return home_row(keyboard)


def transfer_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        _button("⬇️ Скачать", AdminAction.EXPORT),
        _button("⬆️ Загрузить", AdminAction.IMPORT),
    )
    return home_row(keyboard)
