"""Репозиторий администраторов, добавленных через админку (таблица staff)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Staff


class StaffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, user_id: int) -> bool:
        return await self._session.get(Staff, user_id) is not None

    async def all(self) -> list[Staff]:
        result = await self._session.execute(select(Staff).order_by(Staff.created_at))
        return list(result.scalars().all())

    async def add(self, user_id: int, added_by: int) -> bool:
        """False — такой администратор уже есть."""
        if await self.exists(user_id):
            return False
        self._session.add(Staff(user_id=user_id, added_by=added_by))
        await self._session.flush()
        return True

    async def remove(self, user_id: int) -> bool:
        """False — такого администратора не было."""
        result = await self._session.execute(delete(Staff).where(Staff.user_id == user_id))
        return bool(result.rowcount)
