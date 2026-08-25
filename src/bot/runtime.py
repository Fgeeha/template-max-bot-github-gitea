"""Патчи и обвязка над библиотекой maxapi.

Здесь собрано всё, что приходится доделывать за клиентом MAX API: троттлинг,
ретраи на 429 и подключение нестандартного CA-bundle. Держим отдельно от
`__main__`, чтобы точка входа осталась читаемой, а патчи — тестируемыми.
"""

from __future__ import annotations

import asyncio
import logging
import ssl

from aiohttp import TCPConnector
from maxapi import Bot
from maxapi.client.default import DefaultConnectionProperties
from maxapi.exceptions.max import MaxApiError

logger = logging.getLogger(__name__)

# Сколько раз повторить запрос, упавший по rate limit, прежде чем сдаться.
_MAX_RETRY = 5


class RateLimiter:
    """Sliding-window ограничитель для asyncio.

    Слот занимается при каждом запросе и освобождается ровно через `period`
    секунд — итого не более `max_calls` запросов в любом окне длиной `period`.
    В отличие от «сбрасываемого счётчика» не допускает всплеска 2×max_calls
    на стыке двух окон.
    """

    def __init__(self, max_calls: int, period: float = 1.0) -> None:
        self._sem = asyncio.Semaphore(max_calls)
        self._period = period

    async def acquire(self) -> None:
        await self._sem.acquire()
        asyncio.get_running_loop().call_later(self._period, self._sem.release)


def patch_api_rate_limit(max_rps: int) -> None:
    """Троттлит все исходящие запросы к MAX API и ретраит 429.

    Особенность платформы: при 429 MAX отдаёт `Content-Type:
    application/octet-stream` вместо `application/json`, из-за чего maxapi
    падает с `ContentTypeError` на `response.json()` — по этому исключению и
    опознаём rate limit. Ретраим с экспоненциальной задержкой, после
    исчерпания попыток поднимаем обычный MaxApiError.

    Патчится класс `BaseConnection`, а не экземпляр: maxapi создаёт соединения
    внутри себя, перехватить их иначе нельзя.
    """
    from aiohttp import ContentTypeError
    from maxapi.connection.base import BaseConnection

    limiter = RateLimiter(max_calls=max_rps)
    original_request = BaseConnection.request

    async def _request(self, method, path, model=None, *, is_return_raw=False, **kwargs):  # type: ignore[no-untyped-def]
        for attempt in range(_MAX_RETRY):
            await limiter.acquire()
            try:
                return await original_request(
                    self, method, path, model, is_return_raw=is_return_raw, **kwargs
                )
            except ContentTypeError as exc:
                status = getattr(exc, "status", 429)
                if attempt == _MAX_RETRY - 1:
                    raise MaxApiError(
                        code=status,
                        raw={"error": f"rate limit: исчерпаны {_MAX_RETRY} попыток: {exc}"},
                    ) from exc
                wait = min(2.0**attempt, 30.0)
                logger.warning(
                    "MAX API 429 (rate limit), попытка %d/%d, жду %.0f с",
                    attempt + 1,
                    _MAX_RETRY,
                    wait,
                )
                await asyncio.sleep(wait)
        raise MaxApiError(code=429, raw={"error": "unreachable"})  # type: ignore[return]

    BaseConnection.request = _request  # type: ignore[method-assign]
    logger.info("Общий лимит запросов к MAX API: %s RPS", max_rps)


def patch_message_rate_limit(bot: Bot, max_calls: int, period: float = 1.0) -> None:
    """Накладывает отдельный строгий лимит на send_message/delete_message.

    Общего троттлинга недостаточно: он спасает от HTTP 429, но у отправки и
    удаления сообщений есть свой антиспам-порог, за превышение которого
    платформа блокирует бота, а не отвечает ошибкой.

    Патчится конкретный экземпляр `bot`, чтобы не задевать другие инстансы
    (например, созданные в тестах).
    """
    limiter = RateLimiter(max_calls=max_calls, period=period)
    original_send = bot.send_message
    original_delete = bot.delete_message

    async def _send_message(*args: object, **kwargs: object) -> object:
        await limiter.acquire()
        return await original_send(*args, **kwargs)

    async def _delete_message(*args: object, **kwargs: object) -> object:
        await limiter.acquire()
        return await original_delete(*args, **kwargs)

    bot.send_message = _send_message  # type: ignore[method-assign]
    bot.delete_message = _delete_message  # type: ignore[method-assign]
    logger.info(
        "Лимит на send_message/delete_message: %s вызовов / %.0f с",
        max_calls,
        period,
    )


def build_ssl_context(ca_bundle: str | None) -> ssl.SSLContext | None:
    """Создаёт SSL-контекст с дополнительным CA-bundle.

    Возвращает None, если путь не задан — тогда aiohttp работает на системных
    сертификатах без изменений.
    """
    if not ca_bundle:
        return None
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cafile=ca_bundle)
    except (FileNotFoundError, ssl.SSLError) as exc:
        logger.error("Не удалось загрузить CA-bundle %s: %s", ca_bundle, exc)
        raise
    logger.info("SSL CA-bundle загружен: %s", ca_bundle)
    return context


def build_connection_properties(
    ssl_context: ssl.SSLContext | None,
) -> DefaultConnectionProperties | None:
    """Собирает параметры соединения maxapi с нашим CA-bundle.

    Начиная с maxapi 1.2.0 свой connector передаётся штатно через
    `Bot(default_connection=...)` — monkey-patch `Bot.ensure_session` не
    нужен. Connector создаётся один раз на процесс: сессия maxapi живёт до
    остановки бота, закрывается только в `close_session()`.

    Returns:
        None, если CA-bundle не задан (библиотека возьмёт свой CA-bundle).
    """
    if ssl_context is None:
        return None
    return DefaultConnectionProperties(connector=TCPConnector(ssl=ssl_context))
