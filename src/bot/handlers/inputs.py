"""Проверка того, что администратор присылает в админку.

Лимиты — от MAX: подпись кнопки до 64 символов, сообщение до 4000, ссылка
link-кнопки до 2048. Ошибки — готовый текст для админа.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from maxapi.enums.attachment import AttachmentType

from bot.keyboards.menus import MAX_CHILDREN

TITLE_MAX_LEN = 64
TEXT_MAX_LEN = 4000
URL_MAX_LEN = 2048
# Ответ «убрать» на запрос ссылки или картинки.
CLEAR = "-"


def validate_title(title: str) -> str | None:
    """Текст ошибки или None, если название годится."""
    if not title:
        return "Название не может быть пустым."
    if len(title) > TITLE_MAX_LEN:
        return f"Название длиннее {TITLE_MAX_LEN} символов ({len(title)}). Сократите."
    return None


def parse_link(raw: str) -> tuple[str | None, str | None]:
    """Ссылка для link-кнопки: (нормализованный адрес, None) или (None, ошибка).

    Проверка строгая: MAX отклонит сообщение целиком, если ему не понравится
    одна link-кнопка, — и под ударом главное меню и /start у всех. Поэтому
    только http(s), адрес сайта с точкой, без логина и управляющих символов.
    Кириллический домен переводится в punycode.
    """
    error = "Нужна ссылка вида https://example.ru — с http:// или https:// и без пробелов."
    if not raw.isprintable() or any(c.isspace() for c in raw):
        return None, error
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return None, error
    if parts.scheme not in ("http", "https") or "." not in host.strip(".") or "@" in parts.netloc:
        return None, error
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None, error
    netloc = ascii_host + (f":{port}" if port else "")
    url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    if len(url) > URL_MAX_LEN:
        return None, f"Ссылка длиннее {URL_MAX_LEN} символов ({len(url)})."
    return url, None


def validate_text(text: str) -> str | None:
    """Текст ошибки или None, если текст раздела укладывается в лимит MAX."""
    if len(text) > TEXT_MAX_LEN:
        return f"Текст длиннее {TEXT_MAX_LEN} символов ({len(text)}). Сократите."
    return None


def attachments_of(message: Any) -> list[Any]:
    """Вложения входящего сообщения (maxapi Message; в тестах — заглушка)."""
    body = message.body
    return list((body.attachments if body else None) or [])


def file_of(message: Any) -> Any | None:
    """Первое вложение-файл (не фото) входящего сообщения или None."""
    for attachment in attachments_of(message):
        if attachment.type == AttachmentType.FILE and attachment.payload is not None:
            return attachment
    return None


def image_token_of(message: Any) -> str | None:
    """Токен первой картинки во входящем сообщении или None.

    MAX позволяет отправить то же вложение повторно по этому токену, поэтому
    файл не скачивается и не хранится. Из альбома берётся первая картинка.
    """
    for attachment in attachments_of(message):
        if attachment.type == AttachmentType.IMAGE and attachment.payload is not None:
            return attachment.payload.token or None
    return None


def parse_user_id(raw: str) -> tuple[int | None, str | None]:
    """Числовой MAX user ID: (id, None) или (None, ошибка)."""
    if not raw.isdigit() or int(raw) <= 0:
        return None, "Нужен числовой MAX user ID, например 123456789. Его покажет команда /id."
    return int(raw), None


# Файл экспорта: {"format": EXPORT_FORMAT, "version": 1, "root": узел}, где
# узел — {"title", "text", "url", "image_token", "children": [узлы]}.
EXPORT_FORMAT = "max-bot-sections"
EXPORT_VERSION = 1
# Пределы импорта: защита от случайно присланного огромного или зацикленного файла.
IMPORT_MAX_BYTES = 1_000_000
IMPORT_MAX_NODES = 1000
IMPORT_MAX_DEPTH = 20


class TreeError(ValueError):
    """Файл импорта не годится; текст — для администратора."""


def parse_tree(data: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """Корень дерева из файла экспорта: (узел, None) или (None, ошибка).

    Названия, тексты и ссылки проверяются теми же правилами, что и ввод в
    админке: файл, собранный вручную, не должен положить меню у всех
    пользователей. Токены картинок не проверяются (только тип) — если MAX
    их не примет, раздел покажется без картинки (см. menu.send_screen).
    """
    if len(data) > IMPORT_MAX_BYTES:
        return None, f"Файл больше {IMPORT_MAX_BYTES // 1000} КБ."
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "Это не JSON. Пришлите файл, который бот выдал кнопкой «⬇️ Скачать»."
    if (
        not isinstance(doc, dict)
        or doc.get("format") != EXPORT_FORMAT
        or doc.get("version") != EXPORT_VERSION
    ):
        return None, "Это не файл экспорта разделов этого бота (нет format/version)."
    counter = [0]
    try:
        return _node(doc.get("root"), "Главное меню", 0, counter), None
    except TreeError as exc:
        return None, str(exc)


def _node(raw: Any, where: str, depth: int, counter: list[int]) -> dict[str, Any]:
    counter[0] += 1
    if counter[0] > IMPORT_MAX_NODES:
        raise TreeError(f"Разделов больше {IMPORT_MAX_NODES}.")
    if depth > IMPORT_MAX_DEPTH:
        raise TreeError(f"Вложенность глубже {IMPORT_MAX_DEPTH} уровней.")
    if not isinstance(raw, dict):
        raise TreeError(f"{where}: раздел должен быть объектом.")
    title, text, url, image = (raw.get(k) for k in ("title", "text", "url", "image_token"))
    children = raw.get("children", [])
    if not isinstance(title, str) or (error := validate_title(title.strip())):
        raise TreeError(f"{where}: {error or 'нет названия.'}")
    where = f"«{title.strip()}»"
    if not isinstance(text, str) or (error := validate_text(text)):
        raise TreeError(f"{where}: {error or 'текст должен быть строкой.'}")
    if url is not None and depth > 0:
        url, error = parse_link(url) if isinstance(url, str) else (None, "битая ссылка.")
        if error:
            raise TreeError(f"{where}: {error}")
    if image is not None and not isinstance(image, str):
        raise TreeError(f"{where}: image_token должен быть строкой.")
    if not isinstance(children, list) or len(children) > MAX_CHILDREN:
        raise TreeError(f"{where}: подразделов должно быть не больше {MAX_CHILDREN}.")
    return {
        "title": title.strip(),
        "text": text,
        # У главного меню ссылки не бывает — её кнопку некуда поставить.
        "url": url if depth > 0 else None,
        "image_token": image or None,
        "children": [_node(child, where, depth + 1, counter) for child in children],
    }
