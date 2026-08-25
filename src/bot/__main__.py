"""Точка входа бота: выбор polling / webhook по BOT_MODE.

Запуск: `python -m bot` (или `make run`).
"""

from __future__ import annotations

import asyncio
import logging
import signal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from maxapi import Bot, Dispatcher
from maxapi.enums.update import UpdateType
from maxapi.exceptions.max import MaxApiError

from bot.config import Settings, get_settings
from bot.runtime import (
    build_connection_properties,
    build_ssl_context,
    patch_api_rate_limit,
    patch_message_rate_limit,
)
from bot.webhook import BackgroundDispatcher, register_webhook_route

logger = logging.getLogger(__name__)

# Типы апдейтов, на которые подписываемся в режиме webhook. В polling maxapi
# получает всё подряд; здесь список нужен явный — платформа шлёт только
# перечисленное. Добавляя хендлер на новый тип события, дополните список.
_WEBHOOK_UPDATE_TYPES = [
    UpdateType.MESSAGE_CREATED,
    UpdateType.MESSAGE_CALLBACK,
    UpdateType.BOT_STARTED,
]


def setup_logging(level: str) -> None:
    """Настраивает корневой логгер по уровню из LOG_LEVEL."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_dispatcher() -> Dispatcher:
    """Создаёт диспетчер и регистрирует в нём всё middleware и хендлеры."""
    from bot.handlers import register_all

    dispatcher = Dispatcher()
    register_all(dispatcher)
    return dispatcher


def build_bot(settings: Settings) -> Bot:
    """Собирает клиента MAX API со всеми применёнными патчами."""
    ssl_context = build_ssl_context(settings.max_ca_bundle)
    bot = Bot(
        token=settings.max_bot_token,
        default_connection=build_connection_properties(ssl_context),
    )
    # Домен API задаётся отдельно: конструктор Bot использует зашитый в
    # библиотеке адрес, который может отставать от актуального.
    bot.set_api_url(settings.max_api_base_url)
    patch_message_rate_limit(bot, max_calls=settings.max_api_message_rps)

    logger.info("MAX API URL: %s", settings.max_api_base_url)
    return bot


def build_webhook_app(
    bot: Bot, dispatcher: Dispatcher, settings: Settings
) -> tuple[FastAPI, BackgroundDispatcher]:
    """Собирает FastAPI-приложение с маршрутом webhook и health-check.

    Маршрут регистрируем свой (bot.webhook), а не `FastAPIMaxWebhook.setup()`:
    штатный маршрут выполняет `dp.handle` прямо внутри HTTP-запроса и держит
    соединение MAX открытым на всё время обработки — на всплеске сообщений
    это упирается в лимит файловых дескрипторов. От библиотеки берём только
    lifespan — он поднимает диспетчер.
    """
    from maxapi.webhook.fastapi import FastAPIMaxWebhook

    webhook = FastAPIMaxWebhook(dp=dispatcher, bot=bot, secret=settings.webhook_secret)
    app = FastAPI(title="max-bot", lifespan=webhook.lifespan)
    background = BackgroundDispatcher(webhook, max_pending=settings.webhook_max_pending_updates)
    register_webhook_route(
        app,
        background,
        path=settings.webhook_path,
        secret=settings.webhook_secret,
    )

    @app.exception_handler(MaxApiError)
    async def _handle_api_error(request: Request, exc: MaxApiError) -> JSONResponse:
        if exc.code == 429:
            # 429 в ответ — сигнал платформе повторить апдейт позже.
            logger.warning("Rate limit MAX API при обработке webhook — MAX повторит попытку")
            return JSONResponse({"error": "rate_limit"}, status_code=429)
        logger.error("MaxApiError в webhook: code=%s raw=%s", exc.code, exc.raw)
        return JSONResponse({"error": "api_error"}, status_code=500)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Ошибки самой обработки апдейта сюда не доходят: она идёт в фоновой
        # задаче (bot.webhook.BackgroundDispatcher), там своё логирование.
        # Остаются ошибки маршрута — отвечаем 200 намеренно: на 5xx платформа
        # будет ретраить заведомо битый апдейт, получим бесконечный цикл
        # вместо одной записи в логе.
        logger.exception(
            "Необработанное исключение в webhook: %s %s", request.method, request.url.path
        )
        return JSONResponse({"ok": False}, status_code=200)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Проба живости для оркестратора и деплой-пайплайна."""
        return JSONResponse(
            {
                "status": "ok",
                "build": settings.build_tag,
                # Держится у потолка WEBHOOK_MAX_PENDING_UPDATES — обработка
                # не успевает за потоком апдейтов.
                "pending_updates": background.pending,
            }
        )

    return app, background


async def register_webhook_subscription(bot: Bot, settings: Settings) -> None:
    """Регистрирует подписку бота на апдейты в MAX."""
    try:
        await bot.subscribe_webhook(
            settings.webhook_url,
            update_types=_WEBHOOK_UPDATE_TYPES,
            secret=settings.webhook_secret,
        )
        logger.info("Подписка на webhook зарегистрирована")
    except Exception as exc:
        # Не падаем: подписка может уже существовать с прошлого запуска, а
        # сервер поднять всё равно нужно.
        logger.error("Не удалось зарегистрировать webhook: %s", exc)


async def serve_webhook(app: FastAPI, settings: Settings) -> None:
    """Запускает uvicorn с ограничениями на приём соединений.

    limit_concurrency/backlog/timeout_keep_alive заданы явно вместо значений
    по умолчанию (backlog 2048): лишние соединения лучше отбить сразу, чем
    держать открытыми до исчерпания дескрипторов.
    """
    import uvicorn

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        limit_concurrency=settings.webhook_limit_concurrency,
        backlog=settings.webhook_backlog,
        timeout_keep_alive=settings.webhook_keepalive_timeout,
    )
    logger.info(
        "Режим webhook: 0.0.0.0:%s%s (лимит запросов %s, очередь апдейтов %s)",
        settings.port,
        settings.webhook_path,
        settings.webhook_limit_concurrency,
        settings.webhook_max_pending_updates,
    )
    await uvicorn.Server(config).serve()


async def run_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    """Запускает long polling, предварительно сняв webhook-подписку."""
    try:
        await bot.delete_webhook()
    except Exception as exc:
        # Подписки могло не быть — это нормально.
        logger.debug("delete_webhook пропущен: %s", exc)
    logger.info("Режим polling")
    await dispatcher.start_polling(bot)


async def _run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info(
        "Старт: BOT_MODE=%s PROD=%s DB=%s METRICS=%s BUILD_TAG=%s",
        settings.bot_mode.value,
        settings.prod,
        "on" if settings.database_url else "off",
        "on" if settings.metrics_enabled else "off",
        settings.build_tag or "-",
    )
    if settings.is_maintenance:
        logger.warning("PROD=false — maintenance-режим, бот отвечает только ADMIN_IDS")
    if settings.is_maintenance and not settings.admin_ids_set:
        logger.warning("ADMIN_IDS пуст в maintenance-режиме — бот не ответит никому")

    if settings.metrics_enabled:
        from bot.metrics import start_metrics_server

        start_metrics_server(settings.metrics_addr)

    patch_api_rate_limit(settings.max_api_rps)
    bot = build_bot(settings)
    dispatcher = build_dispatcher()

    # Graceful shutdown: по SIGINT/SIGTERM останавливаем runner и закрываем
    # сессии, чтобы не терять апдейт «на полпути» и не оставлять соединения.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # Windows
            pass

    background: BackgroundDispatcher | None = None
    if settings.use_webhook:
        app, background = build_webhook_app(bot, dispatcher, settings)
        await register_webhook_subscription(bot, settings)
        runner = asyncio.create_task(serve_webhook(app, settings))
    else:
        runner = asyncio.create_task(run_polling(bot, dispatcher))

    # Если runner завершился сам (успешно или с ошибкой) — выходим тоже,
    # иначе процесс висел бы живым с мёртвым ботом.
    runner.add_done_callback(lambda _: stop_event.set())
    await stop_event.wait()
    logger.info("Получен сигнал остановки, завершаюсь...")

    if not settings.use_webhook:
        await dispatcher.stop_polling()
    runner.cancel()
    try:
        await runner
    except asyncio.CancelledError:
        pass

    # Сервер больше не принимает запросы — доводим до конца уже принятые
    # апдейты, иначе сообщения потерялись бы между ACK и обработкой.
    if background is not None:
        await background.drain(settings.webhook_drain_timeout)

    await bot.close_session()
    if settings.database_url:
        from bot.db.session import dispose_engine

        await dispose_engine()
    logger.info("Остановлено")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
