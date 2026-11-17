"""Репозиторий разделов меню (дерево `sections`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Section


class SectionRepository:
    """Чтение и правка дерева разделов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, section_id: int) -> Section | None:
        return await self._session.get(Section, section_id)

    async def root(self) -> Section:
        """Корень дерева.

        Штатно его создаёт миграция со стартовым наполнением; запасной корень
        нужен, только если таблицу очистили вручную, — иначе /start упал бы.
        """
        result = await self._session.execute(
            select(Section).where(Section.parent_id.is_(None)).order_by(Section.id).limit(1)
        )
        root = result.scalar_one_or_none()
        if root is None:
            root = Section(parent_id=None, title="Главное меню", text="Выберите раздел 👇")
            self._session.add(root)
            await self._session.flush()
        return root

    async def children(self, parent_id: int) -> list[Section]:
        result = await self._session.execute(
            select(Section)
            .where(Section.parent_id == parent_id)
            .order_by(Section.position, Section.id)
        )
        return list(result.scalars().all())

    async def count_descendants(self, section_id: int) -> int:
        """Сколько разделов уйдёт вместе с этим при удалении."""
        total = 0
        stack = [section_id]
        while stack:
            result = await self._session.execute(
                select(Section.id).where(Section.parent_id == stack.pop())
            )
            ids = list(result.scalars().all())
            total += len(ids)
            stack.extend(ids)
        return total

    async def path(self, section: Section) -> list[Section]:
        """Цепочка от корня до раздела включительно."""
        chain = [section]
        while chain[-1].parent_id is not None:
            parent = await self.get(chain[-1].parent_id)
            if parent is None:
                break
            chain.append(parent)
        return chain[::-1]

    async def add(self, parent_id: int, title: str) -> Section:
        """Добавляет подраздел последним среди соседей."""
        result = await self._session.execute(
            select(func.coalesce(func.max(Section.position), -1)).where(
                Section.parent_id == parent_id
            )
        )
        section = Section(
            parent_id=parent_id, title=title, text="", position=result.scalar_one() + 1
        )
        self._session.add(section)
        await self._session.flush()
        return section

    async def delete(self, section_id: int) -> None:
        """Удаляет раздел вместе с веткой (каскад на стороне БД)."""
        await self._session.execute(delete(Section).where(Section.id == section_id))

    async def move(self, section: Section, step: int) -> bool:
        """Сдвигает раздел на одну позицию: step=-1 — выше, +1 — ниже.

        Возвращает False, если двигать некуда (раздел уже крайний).
        """
        if section.parent_id is None:
            return False
        siblings = await self.children(section.parent_id)
        index = next(i for i, s in enumerate(siblings) if s.id == section.id)
        target = index + step
        if not 0 <= target < len(siblings):
            return False
        siblings[index], siblings[target] = siblings[target], siblings[index]
        # Перенумеровываем всех соседей: так порядок остаётся однозначным,
        # даже если позиции когда-то совпали.
        for position, sibling in enumerate(siblings):
            sibling.position = position
        await self._session.flush()
        return True

    async def export_tree(self) -> dict[str, Any]:
        """Дерево от корня как словарь — формат файла экспорта (см. inputs.parse_tree)."""
        return await self._dump(await self.root())

    async def _dump(self, section: Section) -> dict[str, Any]:
        return {
            "title": section.title,
            "text": section.text,
            "url": section.url,
            "image_token": section.image_token,
            "children": [await self._dump(child) for child in await self.children(section.id)],
        }

    async def replace_tree(self, tree: dict[str, Any]) -> Section:
        """Заменяет всё дерево присланным; возвращает новый корень.

        Узлы получают новые id, поэтому старые кнопки в чатах перестают
        вести в разделы (пользователь получит главное меню), а открытия в
        статистике уходят в «удалённые разделы».
        """
        await self._session.execute(delete(Section))
        return await self._load(tree, None, 0)

    async def _load(self, node: dict[str, Any], parent_id: int | None, position: int) -> Section:
        section = Section(
            parent_id=parent_id,
            title=node["title"],
            text=node["text"],
            url=node["url"],
            image_token=node["image_token"],
            position=position,
        )
        self._session.add(section)
        await self._session.flush()
        for index, child in enumerate(node["children"]):
            await self._load(child, section.id, index)
        return section
