"""Окружение Alembic для асинхронного движка SQLAlchemy."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from bot.config import get_settings

# Импорт моделей обязателен: без него Base.metadata пуст и autogenerate
# сгенерирует ревизию, удаляющую все таблицы.
from bot.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_database_url = get_settings().database_url
if not _database_url:
    msg = "DATABASE_URL не задан — миграции применять некуда"
    raise RuntimeError(msg)

config.set_main_option("sqlalchemy.url", _database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к БД (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Прогон миграций на уже установленном соединении."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # compare_type=True — иначе смена типа колонки не попадёт в ревизию.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Прогон миграций на async-движке."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
