"""Prometheus-метрики (опционально, extra `metrics`).

Включается флагом METRICS_ENABLED. Сервер поднимается на отдельном порту и
наружу не публикуется — его забирает Prometheus изнутри сети.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _counters():  # type: ignore[no-untyped-def]
    """Ленивая инициализация счётчиков.

    prometheus_client — необязательная зависимость, поэтому импортируем его
    внутри функции: без extra `metrics` модуль всё равно должен импортироваться.
    """
    from prometheus_client import Counter

    return {
        "updates": Counter(
            "bot_updates_total",
            "Количество обработанных апдейтов",
            labelnames=("type",),
        ),
        "errors": Counter(
            "bot_errors_total",
            "Количество ошибок при обработке апдейтов",
            labelnames=("kind",),
        ),
    }


_METRICS: dict[str, object] | None = None


def get_metrics() -> dict[str, object]:
    """Возвращает singleton набора счётчиков."""
    global _METRICS
    if _METRICS is None:
        _METRICS = _counters()
    return _METRICS


def parse_metrics_port(metrics_addr: str) -> int:
    """Извлекает порт из строки вида ':9090' или 'host:9090'."""
    return int(metrics_addr.rsplit(":", 1)[-1])


def start_metrics_server(metrics_addr: str) -> None:
    """Поднимает HTTP-сервер метрик в отдельном потоке."""
    from prometheus_client import start_http_server

    port = parse_metrics_port(metrics_addr)
    get_metrics()
    start_http_server(port)
    logger.info("Prometheus-метрики доступны на порту %s", port)
