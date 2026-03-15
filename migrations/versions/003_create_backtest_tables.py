"""create_backtest_tables

创建回测任务表和回测结果表，含联合唯一约束和索引。

Revision ID: 003
Revises: 002
Create Date: 2026-03-14
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, Sequence[str], None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 backtest_tasks 和 backtest_results 表。"""
    # 创建 backtest_tasks 表
    op.create_table(
        "backtest_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="taskstatus"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "strategy_id",
            "scheduled_date",
            name="uq_btask_strategy_date",
        ),
    )
    op.create_index(
        "idx_btask_strategy_status",
        "backtest_tasks",
        ["strategy_id", "status"],
        unique=False,
    )

    # 创建 backtest_results 表
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("total_return", sa.Float(), nullable=False),
        sa.Column("annual_return", sa.Float(), nullable=False),
        sa.Column("sharpe_ratio", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["backtest_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_bresult_strategy_id",
        "backtest_results",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        "idx_bresult_created_at",
        "backtest_results",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """删除 backtest_results 和 backtest_tasks 表。"""
    op.drop_index("idx_bresult_created_at", table_name="backtest_results")
    op.drop_index("idx_bresult_strategy_id", table_name="backtest_results")
    op.drop_table("backtest_results")
    op.drop_index("idx_btask_strategy_status", table_name="backtest_tasks")
    op.drop_table("backtest_tasks")
    op.execute("DROP TYPE IF EXISTS taskstatus")
