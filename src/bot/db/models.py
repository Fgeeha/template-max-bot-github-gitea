"""Модели SQLAlchemy.

Все модели должны быть импортированы к моменту вызова alembic autogenerate,
иначе их таблицы не попадут в Base.metadata и ревизия выйдет пустой
(см. migrations/env.py).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый класс моделей."""


class User(Base):
    """Пользователь бота.

    Демонстрационная модель — замените своей предметной областью.
    """

    __tablename__ = "users"

    # user_id платформы MAX. BigInteger, а не Integer: идентификаторы
    # выходят за пределы int32.
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
