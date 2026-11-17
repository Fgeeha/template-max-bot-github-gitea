"""Типизированные payload'ы callback-кнопок.

MAX передаёт payload кнопки строкой ограниченной длины, поэтому кодируем его
компактно: `<префикс>:<значение>`. Разбор вынесен в классы, чтобы формат был
описан в одном месте — иначе рассинхрон между кнопкой и её обработчиком
обнаруживается только в рантайме.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Предел длины payload на стороне платформы. Значение с запасом: длинный
# payload платформа обрежет молча, и кнопка перестанет работать.
MAX_PAYLOAD_LEN = 128


class PayloadError(ValueError):
    """Payload не соответствует ожидаемому формату."""


def _parse_id(raw: str, value: str) -> int:
    if not value.isdigit():
        msg = f"битый id раздела в payload: {raw!r}"
        raise PayloadError(msg)
    return int(value)


@dataclass(frozen=True)
class SectionPayload:
    """Пользователь открывает раздел."""

    prefix = "s"
    section_id: int

    def pack(self) -> str:
        return f"{self.prefix}:{self.section_id}"

    @classmethod
    def unpack(cls, raw: str) -> SectionPayload:
        prefix, _, value = raw.partition(":")
        if prefix != cls.prefix:
            msg = f"не payload раздела: {raw!r}"
            raise PayloadError(msg)
        return cls(section_id=_parse_id(raw, value))

    @classmethod
    def matches(cls, raw: str) -> bool:
        return raw.startswith(f"{cls.prefix}:")


class AdminAction(StrEnum):
    """Действия админки над разделом."""

    OPEN = "open"
    ADD = "add"
    TITLE = "title"
    TEXT = "text"
    LINK = "link"
    IMAGE = "img"
    UP = "up"
    DOWN = "down"
    DELETE = "del"
    DELETE_CONFIRM = "delok"
    PREVIEW = "view"
    # Главный экран админки; цель не нужна (0).
    HOME = "home"
    # Инструменты (bot.handlers.tools). Цель — аргумент действия: user_id
    # администратора, число дней отчёта или 0.
    STAFF = "staff"
    STAFF_ADD = "staffadd"
    STAFF_DEL = "staffdel"
    STAFF_DEL_CONFIRM = "staffdelok"
    STATS = "stats"
    TRANSFER = "io"
    EXPORT = "export"
    IMPORT = "import"
    LOG = "log"


@dataclass(frozen=True)
class AdminPayload:
    """Кнопка админки: действие и его цель (id раздела или аргумент инструмента)."""

    prefix = "a"
    action: AdminAction
    target: int

    def pack(self) -> str:
        packed = f"{self.prefix}:{self.action.value}:{self.target}"
        if len(packed) > MAX_PAYLOAD_LEN:
            msg = f"payload длиннее {MAX_PAYLOAD_LEN} символов: {packed!r}"
            raise PayloadError(msg)
        return packed

    @classmethod
    def unpack(cls, raw: str) -> AdminPayload:
        parts = raw.split(":")
        if len(parts) != 3 or parts[0] != cls.prefix:
            msg = f"не payload админки: {raw!r}"
            raise PayloadError(msg)
        try:
            action = AdminAction(parts[1])
        except ValueError as exc:
            msg = f"неизвестное действие админки: {raw!r}"
            raise PayloadError(msg) from exc
        return cls(action=action, target=_parse_id(raw, parts[2]))

    @classmethod
    def matches(cls, raw: str) -> bool:
        return raw.startswith(f"{cls.prefix}:")
