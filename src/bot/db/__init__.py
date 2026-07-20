"""Слой хранилища (опционально, extra `db`).

Подключается только когда задан DATABASE_URL. Если бот stateless — каталог
можно удалить целиком вместе с `migrations/`, `alembic.ini` и extra `db`
в pyproject.toml; остальной код на него не ссылается напрямую.

Импорты внутри пакета намеренно ленивые (внутри функций `bot.__main__`),
чтобы отсутствие sqlalchemy/asyncpg не ломало запуск бота без БД.
"""

from bot.db.session import dispose_engine, get_session, session_scope

__all__ = [
    "dispose_engine",
    "get_session",
    "session_scope",
]
