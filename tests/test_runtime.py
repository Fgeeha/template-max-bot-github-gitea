"""Проверки ограничителя частоты и SSL-контекста."""

from __future__ import annotations

import asyncio
import time

import pytest

from bot.runtime import RateLimiter, build_ssl_context


async def test_rate_limiter_allows_burst_within_limit() -> None:
    """Первые max_calls запросов проходят без задержки."""
    limiter = RateLimiter(max_calls=5, period=1.0)
    start = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(5)))
    assert time.monotonic() - start < 0.1


async def test_rate_limiter_delays_over_limit() -> None:
    """Запрос сверх лимита ждёт освобождения слота."""
    limiter = RateLimiter(max_calls=2, period=0.2)
    start = time.monotonic()
    for _ in range(4):
        await limiter.acquire()
    # Четыре запроса при лимите 2/0.2с — минимум одно окно ожидания.
    assert time.monotonic() - start >= 0.2


def test_ssl_context_none_without_bundle() -> None:
    """Без MAX_CA_BUNDLE патч SSL не применяется."""
    assert build_ssl_context(None) is None
    assert build_ssl_context("") is None


def test_ssl_context_fails_loudly_on_missing_file() -> None:
    """Опечатка в пути к сертификату не должна тихо оставлять системные CA."""
    with pytest.raises(FileNotFoundError):
        build_ssl_context("/nonexistent/ca.pem")
