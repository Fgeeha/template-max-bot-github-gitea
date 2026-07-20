"""Конфигурация бота: единый источник правды для всех настроек.

Все параметры читаются из переменных окружения (или из .env в корне проекта).
Хардкод значений в коде запрещён — добавляя настройку, объявляйте её здесь и
описывайте в .env.example.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Абсолютный путь к .env от корня проекта (src/bot/config.py → ../../.env).
# Относительный env_file=".env" ищет файл от cwd процесса — это ненадёжно при
# запуске из другой директории. В Docker .env не монтируется: переменные
# приходят через docker-compose env_file уже как переменные окружения,
# поэтому отсутствие файла — не ошибка, а штатная ситуация.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

logger = logging.getLogger(__name__)


class BotMode(StrEnum):
    """Режим получения апдейтов от платформы MAX."""

    POLLING = "polling"
    WEBHOOK = "webhook"


class Settings(BaseSettings):
    """Настройки приложения.

    Имена полей в snake_case соответствуют переменным окружения в UPPER_CASE:
    `max_bot_token` ← `MAX_BOT_TOKEN`.
    """

    # ---- Платформа MAX -----------------------------------------------------
    # Токен бота. Единственная обязательная переменная — без неё старт невозможен.
    max_bot_token: str
    # Базовый URL API MAX. Менять только при смене домена платформой.
    max_api_base_url: str = "https://platform-api2.max.ru"
    # Путь к PEM-файлу с дополнительным CA-bundle (например, корневой сертификат
    # Минцифры РФ). Если не задан — используются системные сертификаты.
    max_ca_bundle: str | None = None
    # Общий лимит исходящих запросов к API (запросов в секунду). Реальный лимит
    # платформы ~30 RPS — держим запас.
    max_api_rps: int = 25
    # Отдельный, более строгий лимит на send_message/delete_message. Общий
    # троттлинг защищает от HTTP 429, но у отправки сообщений есть свой
    # антиспам-порог: его превышение приводит к блокировке бота платформой.
    max_api_message_rps: int = 2

    # ---- Режим работы ------------------------------------------------------
    bot_mode: BotMode = BotMode.POLLING
    # Публичный https-адрес бота без пути, напр. https://bot.example.ru.
    # Обязателен при BOT_MODE=webhook (см. _validate_webhook).
    webhook_host: str | None = None
    # Путь маршрута FastAPI, на который MAX присылает апдейты.
    webhook_path: str = "/webhook"
    # Секрет для проверки заголовка X-Max-Bot-Api-Secret. Обязателен при
    # webhook: без него эндпоинт принимает любой POST без аутентификации.
    webhook_secret: str | None = None
    # Порт webhook-сервера. В режиме polling не используется.
    port: int = 8081
    # Обрабатывать апдейты в фоне (asyncio.create_task), не блокируя ACK
    # платформе. Снижает риск «таймаут → retry» на медленных хендлерах, но не
    # устраняет дубли: дедупликации по update_id в шаблоне нет.
    webhook_use_create_task: bool = False

    # ---- Логирование -------------------------------------------------------
    # debug/info/warning/error — регистр не важен.
    log_level: str = "info"

    # ---- Доступ ------------------------------------------------------------
    # PROD=true  — бот открыт для всех.
    # PROD=false — maintenance-режим: отвечает только ADMIN_IDS (дефолт,
    # чтобы недонастроенный бот не ушёл к пользователям случайно).
    prod: bool = False
    # Список user_id через запятую: "123, 456". Разбор — в admin_ids_set.
    admin_ids: str = ""

    # ---- Хранилище (опционально, extra `db`) -------------------------------
    # DSN вида postgresql+asyncpg://user:pass@host:5432/dbname.
    # None — бот работает без БД (stateless), слой bot.db не инициализируется.
    database_url: str | None = None

    # ---- Метрики (опционально, extra `metrics`) ----------------------------
    # Включает HTTP-сервер Prometheus на METRICS_ADDR.
    metrics_enabled: bool = False
    metrics_addr: str = ":9090"

    # ---- Служебное ---------------------------------------------------------
    # Тег текущей сборки, подставляется при деплое из IMAGE_TAG
    # (см. docker/docker-compose.prod.yml). Показывается командой /v.
    build_tag: str = ""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_webhook(self) -> Settings:
        """Запрещает заведомо сломанную конфигурацию webhook.

        Ошибка на старте лучше, чем открытый эндпоинт без аутентификации или
        подписка, зарегистрированная на пустой адрес.
        """
        if self.bot_mode is not BotMode.WEBHOOK:
            return self
        if not self.webhook_host:
            msg = (
                "BOT_MODE=webhook требует WEBHOOK_HOST "
                "(публичный https-адрес без пути, напр. https://bot.example.ru)."
            )
            raise ValueError(msg)
        if not self.webhook_secret:
            msg = (
                "BOT_MODE=webhook задан без WEBHOOK_SECRET — публичный эндпоинт "
                "принимал бы любые запросы без проверки подлинности. "
                "Сгенерируйте секрет: openssl rand -hex 32"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_database(self) -> Settings:
        """Проверяет, что DSN асинхронный — синхронный драйвер молча не заработает."""
        if self.database_url and "+asyncpg" not in self.database_url:
            msg = (
                "DATABASE_URL должен использовать async-драйвер: "
                "postgresql+asyncpg://user:pass@host:5432/dbname"
            )
            raise ValueError(msg)
        return self

    @property
    def use_webhook(self) -> bool:
        return self.bot_mode is BotMode.WEBHOOK

    @property
    def is_maintenance(self) -> bool:
        """True, если бот отвечает только администраторам."""
        return not self.prod

    @property
    def admin_ids_set(self) -> frozenset[int]:
        """Разобранное множество admin user_id из ADMIN_IDS."""
        result: set[int] = set()
        for part in self.admin_ids.split(","):
            stripped = part.strip()
            if stripped.isdigit():
                result.add(int(stripped))
        return frozenset(result)

    @property
    def webhook_url(self) -> str:
        """Полный URL подписки: WEBHOOK_HOST + WEBHOOK_PATH."""
        if not self.webhook_host:
            msg = "WEBHOOK_HOST не задан"
            raise ValueError(msg)
        base = self.webhook_host.rstrip("/")
        path = self.webhook_path if self.webhook_path.startswith("/") else f"/{self.webhook_path}"
        return f"{base}{path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает singleton настроек.

    Ленивое создание (в отличие от модульного `settings = Settings()`) позволяет
    тестам подменить переменные окружения до первого обращения и сбросить кэш
    через `get_settings.cache_clear()`.
    """
    settings = Settings()  # type: ignore[call-arg]
    if not _ENV_FILE.exists():
        logger.info(
            "config: .env не найден по пути %s — используются только переменные окружения",
            _ENV_FILE,
        )
    return settings
