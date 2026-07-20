# Multi-stage сборка: base (зависимости) → test / runtime.
#
# Все внешние источники параметризованы через ARG. По умолчанию — зеркала
# закрытого контура; для сборки с доступом в интернет переопределите:
#   docker build \
#     --build-arg BASE_IMAGE=python:3.12-slim-bookworm \
#     --build-arg UV_IMAGE=ghcr.io/astral-sh/uv:latest \
#     --build-arg USE_NEXUS_APT=0 \
#     -f docker/Dockerfile .

# ARG до первого FROM — иначе их нельзя подставить в сам FROM.
ARG BASE_IMAGE="harbor.volganet.ru/dockerhub-proxy/python:3.12-slim-bookworm"
ARG UV_IMAGE="harbor.volganet.ru/github-proxy/astral-sh/uv:latest"

FROM ${UV_IMAGE} AS uvbin

# ---------------------------------------------------------------------------
# base — зависимости и код, общая основа для test и runtime
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS base

# INDEX_URL содержит пароль к Nexus — НИКОГДА не выводить его в echo и не
# писать в ENV: значение осело бы в метаданных образа в открытом виде.
ARG INDEX_URL=""
# Дополнительные extras: "--extra db", "--extra metrics" или оба.
ARG INSTALL_EXTRAS=""
ARG NEXUS_URL="https://nexus.volganet.ru"
# 1 — APT через Nexus Debian-proxy (закрытый контур); 0 — штатные репозитории.
ARG USE_NEXUS_APT="1"
# UID/GID процесса внутри контейнера. При bind-mount ./logs должны совпадать
# с пользователем на хосте, иначе бот не сможет писать логи.
ARG UID=10001
ARG GID=10001

COPY --from=uvbin /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# Переключение APT на Nexus и обновление пакетов базового образа: закрывает
# те OS-CVE, для которых уже вышел фикс в bookworm-security.
RUN set -eux; \
    if [ "${USE_NEXUS_APT}" = "1" ]; then \
        BASE="${NEXUS_URL%/}"; \
        rm -f /etc/apt/sources.list; \
        rm -rf /etc/apt/sources.list.d/*; \
        printf '%s\n' \
          "deb ${BASE}/repository/debian/ bookworm main contrib non-free" \
          "deb ${BASE}/repository/debian-security/ bookworm-security main contrib non-free" \
          "deb ${BASE}/repository/debian/ bookworm-updates main contrib non-free" \
          > /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get -y upgrade; \
    apt-get -y dist-upgrade; \
    apt-get -y autoremove --purge; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Дополнительные корневые сертификаты (например, УЦ Минцифры РФ), если файлы
# лежат в certs/. Каталога может не быть — COPY создаст пустой,
# update-ca-certificates идемпотентен и сборку не ломает.
COPY certs/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates || true

RUN groupadd --system --gid ${GID} appuser \
    && useradd --system --uid ${UID} --gid appuser --no-create-home appuser \
    && mkdir -p /app/logs \
    && chown appuser:appuser /app/logs

# Слой 1 — только зависимости: пересобирается лишь при изменении
# pyproject.toml/uv.lock, а не на каждую правку кода.
COPY pyproject.toml uv.lock* ./
RUN if [ -n "${INDEX_URL}" ]; then \
        UV_DEFAULT_INDEX="${INDEX_URL}" \
          uv sync --no-install-project --no-dev ${INSTALL_EXTRAS} \
          --default-index "${INDEX_URL}" --python /usr/local/bin/python3; \
    else \
        uv sync --no-install-project --no-dev ${INSTALL_EXTRAS} \
          --python /usr/local/bin/python3; \
    fi

# Слой 2 — исходники.
COPY . .
RUN if [ -n "${INDEX_URL}" ]; then \
        UV_DEFAULT_INDEX="${INDEX_URL}" \
          uv sync --no-dev ${INSTALL_EXTRAS} \
          --default-index "${INDEX_URL}" --python /usr/local/bin/python3; \
    else \
        uv sync --no-dev ${INSTALL_EXTRAS} --python /usr/local/bin/python3; \
    fi

ENV PATH="/app/.venv/bin:$PATH"

# ---------------------------------------------------------------------------
# test — доставляет dev-зависимости и гоняет проверки (цель для CI)
# ---------------------------------------------------------------------------
FROM base AS test
ARG INDEX_URL=""
ARG INSTALL_EXTRAS=""
RUN if [ -n "${INDEX_URL}" ]; then \
        UV_DEFAULT_INDEX="${INDEX_URL}" uv sync ${INSTALL_EXTRAS} \
          --default-index "${INDEX_URL}"; \
    else \
        uv sync ${INSTALL_EXTRAS}; \
    fi
CMD ["sh", "-c", "ruff check src tests && ruff format --check . && pytest -q"]

# ---------------------------------------------------------------------------
# runtime — прод-образ: без dev-зависимостей, от непривилегированного пользователя
# ---------------------------------------------------------------------------
FROM base AS runtime
ARG BUILD_TAG=""
ENV BUILD_TAG=${BUILD_TAG}
USER appuser
# Порт слушается только при BOT_MODE=webhook; в polling EXPOSE — просто
# декларация для оркестратора.
EXPOSE 8081
CMD ["python", "-m", "bot"]
