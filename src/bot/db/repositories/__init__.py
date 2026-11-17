"""Репозитории: весь SQL живёт здесь.

Хендлеры и сервисы работают с репозиториями, а не с сессией напрямую —
иначе запросы расползаются по слоям и их невозможно ни переиспользовать,
ни протестировать отдельно.
"""

from bot.db.repositories.audit import AuditRepository
from bot.db.repositories.sections import SectionRepository
from bot.db.repositories.staff import StaffRepository
from bot.db.repositories.stats import StatsRepository

__all__ = ["AuditRepository", "SectionRepository", "StaffRepository", "StatsRepository"]
