"""Статистика открытий разделов (таблица section_views)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Section, SectionView


def user_hash(user_id: int, salt: str) -> str:
    """Необратимый идентификатор посетителя: HMAC-SHA256, первые 32 hex-символа."""
    digest = hmac.new(salt.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return digest[:32]


@dataclass(frozen=True)
class SectionStat:
    title: str | None  # None — раздел удалён
    opens: int
    users: int


@dataclass(frozen=True)
class StatsReport:
    days: int
    opens: int
    users: int
    top: list[SectionStat]


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, section_id: int, visitor: str) -> None:
        self._session.add(SectionView(section_id=section_id, user_hash=visitor))
        await self._session.flush()

    async def report(self, days: int, top: int) -> StatsReport:
        since = datetime.now(UTC) - timedelta(days=days)
        period = SectionView.created_at >= since
        totals = (
            await self._session.execute(
                select(
                    func.count(SectionView.id), func.count(distinct(SectionView.user_hash))
                ).where(period)
            )
        ).one()
        opens = func.count(SectionView.id).label("opens")
        rows = await self._session.execute(
            select(Section.title, opens, func.count(distinct(SectionView.user_hash)))
            .select_from(SectionView)
            .outerjoin(Section, Section.id == SectionView.section_id)
            .where(period)
            # Удалённые разделы (section_id = NULL) сливаются в одну строку.
            .group_by(SectionView.section_id, Section.title)
            .order_by(opens.desc())
            .limit(top)
        )
        return StatsReport(
            days=days,
            opens=totals[0],
            users=totals[1],
            top=[SectionStat(title=t, opens=o, users=u) for t, o, u in rows.all()],
        )
