"""Модели SQLAlchemy.

Все модели должны быть импортированы к моменту вызова alembic autogenerate,
иначе их таблицы не попадут в Base.metadata и ревизия выйдет пустой
(см. migrations/env.py).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый класс моделей."""


class Section(Base):
    """Раздел меню — узел дерева.

    Корень (parent_id IS NULL) один: его text — приветствие на /start, а
    дочерние разделы — кнопки главного меню. У любого раздела text
    отправляется при нажатии на его кнопку; если есть подразделы, под текстом
    появляются их кнопки. Раздел со ссылкой (url) — кнопка-ссылка наружу.
    """

    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ON DELETE CASCADE: удаление раздела удаляет всю ветку на стороне БД,
    # без обхода дерева в коде.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True, default=None
    )
    # Подпись кнопки. 64 — потолок длины текста кнопки в MAX.
    title: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, default="")
    # Порядок кнопок среди соседей.
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Задана — кнопка раздела открывает эту ссылку (LinkButton), а текст и
    # подразделы пользователь не видит. 2048 — потолок длины ссылки в MAX.
    url: Mapped[str | None] = mapped_column(String(2048), default=None)
    # Токен картинки MAX: присылается над текстом раздела. Это токен входящего
    # фото из админки — MAX разрешает отправлять то же вложение повторно, файл
    # бот не хранит.
    image_token: Mapped[str | None] = mapped_column(Text, default=None)


# BigInteger-ключ в SQLite (тесты) не автоинкрементируется — там нужен INTEGER.
_BigId = BigInteger().with_variant(Integer, "sqlite")


class Staff(Base):
    """Администратор, добавленный владельцем через админку.

    Владельцы — ADMIN_IDS из .env — сюда не пишутся: их права не зависят от БД,
    поэтому без админов бот не остаётся никогда.
    """

    __tablename__ = "staff"

    # user_id MAX выходит за пределы int32.
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SectionView(Base):
    """Открытие раздела пользователем — для статистики.

    user_hash — HMAC от user_id (см. db.repositories.stats), сам id не хранится.
    Удаление раздела не стирает его открытия (SET NULL): итоги за период не
    меняются задним числом, в отчёте они идут строкой «удалённые разделы».
    """

    __tablename__ = "section_views"

    id: Mapped[int] = mapped_column(_BigId, primary_key=True)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), index=True, default=None
    )
    user_hash: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AuditEntry(Base):
    """Запись журнала изменений: кто, что и когда поменял в админке.

    details — готовая строка для показа («текст «Контакты» #5»): раздел мог
    быть удалён, поэтому название сохраняется на момент правки.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(_BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
