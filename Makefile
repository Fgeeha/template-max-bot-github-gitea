# Единая точка входа для всех операций проекта.
# Зависимости ставятся только через uv — не pip и не poetry.

.DEFAULT_GOAL := help
COMPOSE ?= docker compose

# --- Источники образов и пакетов -------------------------------------------
# Дефолты — зеркала закрытого контура. Для сборки с доступом в интернет:
#
#   BASE_IMAGE=python:3.12-slim-bookworm \
#   UV_IMAGE=ghcr.io/astral-sh/uv:latest \
#   POSTGRES_IMAGE=postgres:16-alpine \
#   USE_NEXUS_APT=0 \
#   make up-local
#
# Движок тоже переопределяется: COMPOSE='podman compose' make up-local
BASE_IMAGE ?= harbor.volganet.ru/dockerhub-proxy/python:3.12-slim-bookworm
UV_IMAGE ?= harbor.volganet.ru/github-proxy/astral-sh/uv:latest
POSTGRES_IMAGE ?= harbor.volganet.ru/dockerhub-proxy/postgres:16-alpine
USE_NEXUS_APT ?= 1
# Дополнительные extras для сборки образа: "--extra db --extra metrics"
INSTALL_EXTRAS ?=
export BASE_IMAGE UV_IMAGE POSTGRES_IMAGE USE_NEXUS_APT INSTALL_EXTRAS

DC_LOCAL := $(COMPOSE) --env-file .env -f docker/docker-compose.local.yml
DC_PROD  := $(COMPOSE) --env-file .env -f docker/docker-compose.prod.yml
GITEA_URL := https://gitea.volganet.ru

.PHONY: help init install install-all run lint format test check \
        precommit up-local down-local restart-local logs \
        up-prod down-prod migrate migration dump restore clean

help: ## Показать список целей
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Разработка -------------------------------------------------------------

init: ## Создать новый проект из шаблона (интерактивно)
	uv run python scripts/init_project.py

install: ## Установить базовые зависимости
	uv sync

install-all: ## Установить зависимости со всеми extras (db, metrics)
	uv sync --all-extras

run: ## Запустить бота локально
	uv run python -m bot

lint: ## Проверить код (ruff check)
	uv run ruff check src tests

format: ## Отформатировать код и починить импорты
	uv run ruff check --fix src tests
	uv run ruff format .

test: ## Прогнать тесты
	uv run pytest

check: lint test ## Полная проверка перед коммитом
	uv run ruff format --check .

precommit: ## Установить и прогнать pre-commit
	@if curl -fsS --max-time 3 $(GITEA_URL) >/dev/null 2>&1; then \
		echo "Gitea доступна — использую внутреннее зеркало"; \
		cp .pre-commit-config.gitea.yaml .pre-commit-config.yaml; \
	else \
		echo "Gitea недоступна — использую GitHub"; \
		cp .pre-commit-config.github.yaml .pre-commit-config.yaml; \
	fi
	uv run pre-commit install
	uv run pre-commit run --all-files

# --- Docker -----------------------------------------------------------------
# --env-file .env обязателен: без него Compose ищет .env рядом с самим
# compose-файлом (то есть в docker/), и подстановка ${PORT} в ports: молча
# берёт дефолт. env_file: внутри compose — другой механизм, он передаёт
# переменные в контейнер и подстановку в YAML не заменяет.

up-local: ## Поднять бота локально в Docker
	$(DC_LOCAL) up -d --build

up-local-db: ## Поднять бота вместе с Postgres (профиль db)
	$(DC_LOCAL) --profile db up -d --build

down-local: ## Остановить локальный стек
	$(DC_LOCAL) --profile db down

restart-local: ## Пересобрать и перезапустить локальный стек
	$(DC_LOCAL) down
	$(DC_LOCAL) up -d --build

logs: ## Логи бота в реальном времени
	$(DC_LOCAL) logs -f bot

up-prod: ## Поднять прод-конфигурацию
	$(DC_PROD) up -d

down-prod: ## Остановить прод-конфигурацию
	$(DC_PROD) down

# --- База данных (только при extra `db`) ------------------------------------

migrate: ## Применить миграции
	uv run alembic upgrade head

migration: ## Создать ревизию: make migration m="описание"
	@test -n "$(m)" || { echo "Укажите описание: make migration m=\"добавил users\""; exit 1; }
	uv run alembic revision --autogenerate -m "$(m)"

dump: ## Дамп локальной БД: make dump [f=backup.dump]
	$(DC_LOCAL) exec -T db sh -c 'pg_dump -Fc -U "$$POSTGRES_USER" "$$POSTGRES_DB"' \
		> $(or $(f),dump_local_$(shell date +%Y%m%d_%H%M%S).dump)

restore: ## Восстановить БД из дампа: make restore f=backup.dump
	@test -n "$(f)" || { echo "Укажите файл: make restore f=backup.dump"; exit 1; }
	$(DC_LOCAL) exec -T db sh -c \
		'pg_restore --clean --if-exists --no-owner -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < $(f)

# --- Прочее -----------------------------------------------------------------

clean: ## Удалить кэши и временные артефакты
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
