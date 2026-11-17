"""Слой хранилища: SQLAlchemy async + Alembic.

Разделы меню и их тексты хранятся в Postgres и правятся через админку,
поэтому БД обязательна. Весь SQL — в `bot.db.repositories`.
"""

from bot.db.session import dispose_engine, get_session, session_scope

__all__ = [
    "dispose_engine",
    "get_session",
    "session_scope",
]
