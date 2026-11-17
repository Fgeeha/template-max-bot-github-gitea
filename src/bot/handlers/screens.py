"""Экраны админки разделов: текст и клавиатура, подписи для журнала."""

from __future__ import annotations

from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.db.models import Section
from bot.db.repositories import SectionRepository
from bot.keyboards.callbacks import AdminAction
from bot.keyboards.menus import admin_keyboard

# Сколько текста раздела показывать на экране админки: экран — тоже
# сообщение, и вместе с шапкой должен уложиться в 4000.
SCREEN_TEXT_PREVIEW = 3000


async def build_screen(
    repo: SectionRepository, section: Section
) -> tuple[str, InlineKeyboardBuilder]:
    """Экран раздела в админке."""
    path = await repo.path(section)
    children = await repo.children(section.id)

    body = section.text.strip() or "— не задан —"
    if len(body) > SCREEN_TEXT_PREVIEW:
        body = body[:SCREEN_TEXT_PREVIEW] + "…"

    lines = ["⚙️ Админка", "📂 " + " › ".join(s.title for s in path), ""]
    if section.parent_id is None:
        lines.append("📝 Приветствие на /start:")
    else:
        siblings = await repo.children(section.parent_id)
        index = next(i for i, s in enumerate(siblings) if s.id == section.id)
        lines.insert(2, f"Позиция кнопки: {index + 1} из {len(siblings)}")
        if section.url:
            # Текст и подразделы при этом сохраняются: уберут ссылку — вернутся.
            # Ссылку укорачиваем: экран вместе с текстом должен влезть в 4000.
            shown = section.url if len(section.url) <= 200 else section.url[:200] + "…"
            lines += [
                f"🔗 Кнопка открывает ссылку: {shown}",
                "Текст и подразделы пользователь не видит, пока ссылка задана.",
                "",
                "📝 Текст (сохранён, вернётся, если убрать ссылку):",
            ]
        else:
            lines.append("📝 Текст, который придёт по кнопке:")
    lines += [
        body,
        "",
        f"🖼 Картинка: {_image_status(section)}",
        f"Подразделов (кнопок под текстом): {len(children)}",
    ]
    return "\n".join(lines), admin_keyboard(section, children)


def _image_status(section: Section) -> str:
    if not section.image_token:
        return "нет"
    if section.url:
        # У раздела-ссылки нет экрана — картинку пользователь не увидит.
        return "сохранена, появится, если убрать ссылку"
    return "есть — видна в «👁 Как видит пользователь»"


def name(section: Section) -> str:
    return f"«{section.title}» #{section.id}"


def audit_text(action: AdminAction, section: Section, old_title: str) -> str:
    """Строка журнала для правки через ввод."""
    if action is AdminAction.ADD:
        return f"добавил раздел {name(section)}"
    if action is AdminAction.TITLE:
        return f"переименовал «{old_title}» → {name(section)}"
    if action is AdminAction.LINK:
        return f"{'задал' if section.url else 'убрал'} ссылку {name(section)}"
    if action is AdminAction.IMAGE:
        return f"{'сменил' if section.image_token else 'убрал'} картинку {name(section)}"
    return f"изменил текст {name(section)}"
