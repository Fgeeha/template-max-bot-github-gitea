"""Репозиторий пользователей — образец для остальных репозиториев."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User


class UserRepository:
    """Доступ к таблице users."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def upsert(self, user_id: int, username: str | None = None) -> None:
        """Создаёт пользователя или обновляет время последнего визита.

        Реализовано через INSERT ... ON CONFLICT, а не «прочитать и решить»:
        два одновременных события от одного пользователя иначе гонятся за
        вставку и один из запросов падает на нарушении первичного ключа.
        """
        statement = (
            insert(User)
            .values(user_id=user_id, username=username)
            .on_conflict_do_update(
                index_elements=[User.user_id],
                set_={"username": username},
            )
        )
        await self._session.execute(statement)

    async def count(self) -> int:
        result = await self._session.execute(select(User.user_id))
        return len(result.scalars().all())
