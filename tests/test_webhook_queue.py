"""Тесты приёма апдейтов вебхука вне HTTP-запроса (bot/webhook.py).

Проверяем главное свойство ради которого всё делалось: ответ MAX не ждёт
обработку апдейта, а очередь обработки ограничена — при переполнении маршрут
отвечает 503, а не копит соединения до исчерпания дескрипторов.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI

from bot.webhook import BackgroundDispatcher, register_webhook_route


class FakeWebhook:
    """Заглушка FastAPIMaxWebhook: считает вызовы и умеет «зависать»."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.fail = False

    async def _dispatch(self, event_json: dict[str, Any]) -> bool:
        self.calls.append(event_json)
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("обработка упала")
        return True


def _client(app: FastAPI) -> httpx.AsyncClient:
    """HTTP-клиент поверх ASGI-приложения (без реальной сети)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _build(max_pending: int = 2, secret: str | None = None) -> tuple[FastAPI, FakeWebhook, Any]:
    webhook = FakeWebhook()
    dispatcher = BackgroundDispatcher(webhook, max_pending=max_pending)
    app = FastAPI()
    register_webhook_route(app, dispatcher, path="/webhook", secret=secret)
    return app, webhook, dispatcher


async def test_route_answers_before_handler_finishes() -> None:
    """Ответ 200 приходит, пока обработка ещё идёт."""
    app, webhook, dispatcher = _build()
    async with _client(app) as client:
        response = await client.post("/webhook", json={"update_type": "message_created"})
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # Обработка началась, но не завершилась: ответ её не ждал.
        await asyncio.wait_for(webhook.started.wait(), timeout=1)
        assert dispatcher.pending == 1
        webhook.release.set()
        await dispatcher.drain(timeout_seconds=1)
    assert dispatcher.pending == 0
    assert webhook.calls == [{"update_type": "message_created"}]


async def test_route_rejects_when_queue_is_full() -> None:
    """Сверх max_pending апдейты получают 503, а не копятся."""
    app, webhook, dispatcher = _build(max_pending=2)
    async with _client(app) as client:
        for _ in range(2):
            assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 200
        overflow = await client.post("/webhook", json={"update_type": "x"})
        assert overflow.status_code == 503
        assert dispatcher.pending == 2
        webhook.release.set()
        await dispatcher.drain(timeout_seconds=1)
    # Отклонённый апдейт до обработки не дошёл — MAX повторит доставку.
    assert len(webhook.calls) == 2


async def test_queue_frees_slot_after_handler_finishes() -> None:
    """Слот освобождается по завершении обработки."""
    app, webhook, dispatcher = _build(max_pending=1)
    async with _client(app) as client:
        assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 200
        assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 503
        webhook.release.set()
        await dispatcher.drain(timeout_seconds=1)
        assert dispatcher.pending == 0
        assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 200
        await dispatcher.drain(timeout_seconds=1)
    assert len(webhook.calls) == 2


async def test_wrong_secret_is_rejected() -> None:
    """Без правильного заголовка апдейт не принимается (как в maxapi)."""
    app, webhook, dispatcher = _build(secret="s3cret")
    async with _client(app) as client:
        assert (await client.post("/webhook", json={})).status_code == 403
        bad = await client.post("/webhook", json={}, headers={"X-Max-Bot-Api-Secret": "nope"})
        assert bad.status_code == 403
        good = await client.post("/webhook", json={}, headers={"X-Max-Bot-Api-Secret": "s3cret"})
        assert good.status_code == 200
        webhook.release.set()
        await dispatcher.drain(timeout_seconds=1)
    assert len(webhook.calls) == 1


async def test_broken_json_is_rejected() -> None:
    """Битое тело не должно попадать в обработку."""
    app, webhook, dispatcher = _build()
    async with _client(app) as client:
        response = await client.post(
            "/webhook",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 400
    assert webhook.calls == []
    assert dispatcher.pending == 0


async def test_handler_error_does_not_break_queue() -> None:
    """Исключение в обработке освобождает слот и не роняет приём."""
    app, webhook, dispatcher = _build(max_pending=1)
    webhook.fail = True
    async with _client(app) as client:
        assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 200
        webhook.release.set()
        await dispatcher.drain(timeout_seconds=1)
        assert dispatcher.pending == 0
        assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 200
        await dispatcher.drain(timeout_seconds=1)


async def test_drain_cancels_tasks_after_timeout() -> None:
    """Зависшая обработка не держит остановку бота вечно."""
    app, webhook, dispatcher = _build()
    async with _client(app) as client:
        assert (await client.post("/webhook", json={"update_type": "x"})).status_code == 200
        await asyncio.wait_for(webhook.started.wait(), timeout=1)
        await dispatcher.drain(timeout_seconds=0.05)  # release так и не выставлен
    # drain дожидается отмены, поэтому по возвращении задач уже не осталось.
    assert dispatcher.pending == 0
