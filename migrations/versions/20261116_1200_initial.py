"""Начальная схема: разделы меню, администраторы, статистика, журнал

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-16 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Демонстрационное наполнение — дальше правится через /admin.
# Узел: (название, текст, ссылка, подразделы).
SEED = (
    "Главное меню",
    "👋 Здравствуйте!\n\n"
    "Это шаблон бота-визитки для мессенджера MAX. Тексты, кнопки, картинки "
    "и ссылки меняются в админке: команда /admin в личке с ботом.\n\n"
    "Выберите раздел 👇",
    None,
    [
        (
            "ℹ️ О нас",
            "Расскажите здесь, чем вы занимаетесь и чем можете помочь.",
            None,
            [],
        ),
        (
            "📞 Контакты",
            "Телефон: +7 (000) 000-00-00\nE-mail: info@example.ru\nАдрес: …",
            None,
            [],
        ),
        (
            "❓ Помощь",
            "Команды:\n/start — главное меню\n/id — ваш MAX user ID\n\n"
            "Кнопки под сообщением ведут по разделам.",
            None,
            [],
        ),
        ("🌐 Сайт", "", "https://max.ru", []),
    ],
)


def upgrade() -> None:
    big_id = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    sections = op.create_table(
        "sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("sections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("image_token", sa.Text(), nullable=True),
    )
    op.create_index("ix_sections_parent_id", "sections", ["parent_id"])

    op.create_table(
        "staff",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "section_views",
        sa.Column("id", big_id, primary_key=True),
        sa.Column(
            "section_id",
            sa.Integer(),
            sa.ForeignKey("sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_hash", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_section_views_section_id", "section_views", ["section_id"])
    op.create_index("ix_section_views_created_at", "section_views", ["created_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", big_id, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # id не задаём явно: иначе sequence не сдвинется и первая вставка из
    # админки упадёт на дубликате ключа.
    conn = op.get_bind()

    def insert(node: tuple, parent_id: int | None, position: int) -> None:
        title, text, url, children = node
        new_id = conn.execute(
            sa.insert(sections)
            .values(parent_id=parent_id, title=title, text=text, url=url, position=position)
            .returning(sections.c.id)
        ).scalar_one()
        for index, child in enumerate(children):
            insert(child, new_id, index)

    insert(SEED, None, 0)


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("section_views")
    op.drop_table("staff")
    op.drop_index("ix_sections_parent_id", table_name="sections")
    op.drop_table("sections")
