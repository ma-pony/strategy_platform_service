"""create_trading_signals

创建交易信号表，含复合索引。

Revision ID: 004
Revises: 003
Create Date: 2026-03-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, Sequence[str], None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 trading_signals 表。"""
    op.create_table(
        "trading_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("buy", "sell", "hold", name="signaldirection"),
            nullable=False,
        ),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_signal_strategy_at",
        "trading_signals",
        ["strategy_id", sa.text("signal_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """删除 trading_signals 表。"""
    op.drop_index("idx_signal_strategy_at", table_name="trading_signals")
    op.drop_table("trading_signals")
    op.execute("DROP TYPE IF EXISTS signaldirection")
