"""Типизированные payload'ы callback-кнопок.

MAX передаёт payload кнопки строкой ограниченной длины, поэтому кодируем его
компактно: `<префикс>:<значение>`. Разбор вынесен в классы, чтобы формат был
описан в одном месте — иначе рассинхрон между кнопкой и её обработчиком
обнаруживается только в рантайме.
"""

from __future__ import annotations

from dataclasses import dataclass

# Предел длины payload на стороне платформы. Значение с запасом: длинный
# payload платформа обрежет молча, и кнопка перестанет работать.
MAX_PAYLOAD_LEN = 128


class PayloadError(ValueError):
    """Payload не соответствует ожидаемому формату."""


@dataclass(frozen=True)
class MenuPayload:
    """Переход в раздел меню."""

    prefix = "menu"
    section: str

    def pack(self) -> str:
        packed = f"{self.prefix}:{self.section}"
        if len(packed) > MAX_PAYLOAD_LEN:
            msg = f"payload длиннее {MAX_PAYLOAD_LEN} символов: {packed!r}"
            raise PayloadError(msg)
        return packed

    @classmethod
    def unpack(cls, raw: str) -> MenuPayload:
        prefix, _, section = raw.partition(":")
        if prefix != cls.prefix or not section:
            msg = f"не payload меню: {raw!r}"
            raise PayloadError(msg)
        return cls(section=section)

    @classmethod
    def matches(cls, raw: str) -> bool:
        return raw.startswith(f"{cls.prefix}:")


@dataclass(frozen=True)
class BackPayload:
    """Возврат в главное меню."""

    prefix = "back"

    def pack(self) -> str:
        return self.prefix

    @classmethod
    def matches(cls, raw: str) -> bool:
        return raw == cls.prefix
