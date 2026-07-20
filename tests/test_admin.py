"""Проверки служебных команд и форматирования сообщений."""

from __future__ import annotations

from bot.handlers.admin import MAX_MESSAGE_LEN, build_status_text, split_message


def test_short_text_not_split() -> None:
    assert split_message("короткий текст") == ["короткий текст"]


def test_long_text_split_within_limit() -> None:
    text = "\n".join(f"строка номер {i}" for i in range(1000))
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_MESSAGE_LEN for chunk in chunks)


def test_split_preserves_content() -> None:
    """Разбиение не должно терять или дублировать строки."""
    lines = [f"строка {i}" for i in range(500)]
    chunks = split_message("\n".join(lines))
    assert "\n".join(chunks).split("\n") == lines


def test_split_does_not_break_lines() -> None:
    lines = [f"строка {i}" for i in range(500)]
    for chunk in split_message("\n".join(lines)):
        for line in chunk.split("\n"):
            assert line in lines


def test_status_hides_secrets(env) -> None:
    """Отчёт о статусе не должен раскрывать токен или пароль от БД."""
    env(
        MAX_BOT_TOKEN="super-secret-token",
        DATABASE_URL="postgresql+asyncpg://bot:secret-password@db:5432/bot",
    )
    text = build_status_text()
    assert "super-secret-token" not in text
    assert "secret-password" not in text
    assert "подключена" in text
