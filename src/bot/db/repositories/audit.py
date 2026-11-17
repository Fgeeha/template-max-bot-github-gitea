"""Журнал изменений админки (таблица audit_log)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AuditEntry


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, user_id: int, details: str) -> None:
        # Запись в той же транзакции, что и правка: откатится правка — откатится и запись.
        self._session.add(AuditEntry(user_id=user_id, details=details))
        await self._session.flush()

    async def recent(self, limit: int) -> list[AuditEntry]:
        result = await self._session.execute(
            select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
        )
        return list(result.scalars().all())
