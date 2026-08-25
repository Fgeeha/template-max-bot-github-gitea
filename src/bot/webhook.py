"""Приём апдейтов MAX без удержания HTTP-соединения на время обработки.

Штатный маршрут maxapi (`FastAPIMaxWebhook.setup`) выполняет `dp.handle(event)`
прямо внутри обработчика POST-запроса, то есть TCP-соединение от MAX живёт
столько, сколько работает хендлер. Если обработка медленная (троттлинг
исходящих запросов, ретраи, синхронная работа с БД), на всплеске сообщений
соединения копятся, MAX по таймауту переотправляет апдейты новыми
соединениями — и процесс упирается в лимит файловых дескрипторов
(`OSError: [Errno 24] Too many open files` в `socket.accept()`).

Здесь маршрут отвечает MAX сразу, а обработка уходит в фоновую задачу:
очередь копится в памяти (её видно через `/healthz`, можно ограничить), а не в
открытых сокетах. При переполнении апдейт не принимается — MAX повторит
доставку позже, это честнее тихого накопления.

Ссылки на задачи хранятся в множестве: без этого сборщик мусора может забрать
задачу до её завершения (`asyncio.create_task` держит лишь слабую ссылку).
"""

from __future__ import annotations

import asyncio
import logging
from secrets import compare_digest
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from maxapi.webhook.fastapi import FastAPIMaxWebhook

logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Max-Bot-Api-Secret"


class BackgroundDispatcher:
    """Обрабатывает апдейты вне HTTP-запроса, не больше `max_pending` разом.

    `max_pending` ограничивает не скорость обработки (за неё отвечают лимиты
    исходящих запросов в `bot.runtime`), а размер накопленного хвоста: при
    переполнении `submit` возвращает False и апдейт отклоняется.
    """

    def __init__(self, webhook: FastAPIMaxWebhook, max_pending: int) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending должен быть больше 0")
        self._webhook = webhook
        self._max_pending = max_pending
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def pending(self) -> int:
        """Сколько апдейтов сейчас в обработке."""
        return len(self._tasks)

    def submit(self, event_json: dict[str, Any]) -> bool:
        """Ставит апдейт в обработку. False — очередь переполнена."""
        if len(self._tasks) >= self._max_pending:
            logger.error(
                "Очередь обработки апдейтов переполнена (%d), апдейт отклонён: %s",
                self._max_pending,
                event_json.get("update_type"),
            )
            return False
        # _dispatch — точка входа maxapi: разбирает JSON в типизированное
        # событие и передаёт диспетчеру. Единственное место, где мы опираемся
        # на непубличный метод библиотеки.
        task = asyncio.create_task(self._webhook._dispatch(event_json))
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return True

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """Убирает задачу из набора и логирует исключение, если оно было."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Необработанное исключение при обработке апдейта: %r", exc)

    async def drain(self, timeout_seconds: float) -> None:
        """Ждёт завершения принятых апдейтов при остановке бота."""
        if not self._tasks:
            return
        logger.info("Жду завершения обработки %d апдейтов...", len(self._tasks))
        pending = list(self._tasks)
        _, unfinished = await asyncio.wait(pending, timeout=timeout_seconds)
        if unfinished:
            logger.warning("Не дождался %d апдейтов, отменяю", len(unfinished))
            for task in unfinished:
                task.cancel()
            # Дожидаемся самой отмены: иначе метод вернётся, а задачи ещё живы,
            # и следом их оборвёт закрытие event loop.
            await asyncio.gather(*unfinished, return_exceptions=True)


def register_webhook_route(
    app: FastAPI,
    dispatcher: BackgroundDispatcher,
    *,
    path: str,
    secret: str | None,
) -> None:
    """Регистрирует POST-маршрут вебхука с быстрым ответом MAX.

    Проверка секрета повторяет поведение maxapi (заголовок
    `X-Max-Bot-Api-Secret`, сравнение через `compare_digest`), но маршрут наш:
    только так можно ответить 503 при переполнении очереди — штатный маршрут
    библиотеки всегда возвращает 200.
    """

    @app.post(path)
    async def _webhook_route(request: Request) -> JSONResponse:
        if secret is not None:
            provided = request.headers.get(SECRET_HEADER)
            if provided is None or not compare_digest(provided, secret):
                return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            event_json = await request.json()
        except ValueError:
            logger.warning("Апдейт с некорректным JSON отклонён")
            return JSONResponse({"error": "bad_request"}, status_code=400)
        if not dispatcher.submit(event_json):
            # 503 — сигнал MAX повторить доставку позже.
            return JSONResponse({"error": "overloaded"}, status_code=503)
        return JSONResponse({"ok": True}, status_code=200)
