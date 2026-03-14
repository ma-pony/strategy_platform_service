"""create_research_reports

创建研报表和研报关联币种表，含时间索引。

Revision ID: 005
Revises: 004
Create Date: 2026-03-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, Sequence[str], None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 research_reports 和 report_coins 表。"""
    # 创建 research_reports 表
    op.create_table(
        "research_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_report_generated_at",
        "research_reports",
        ["generated_at"],
        unique=False,
    )

    # 创建 report_coins 表
    op.create_table(
        "report_coins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("coin_symbol", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["research_reports.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_reportcoin_report_id",
        "report_coins",
        ["report_id"],
        unique=False,
    )


def downgrade() -> None:
    """删除 report_coins 和 research_reports 表。"""
    op.drop_index("idx_reportcoin_report_id", table_name="report_coins")
    op.drop_table("report_coins")
    op.drop_index("idx_report_generated_at", table_name="research_reports")
    op.drop_table("research_reports")
