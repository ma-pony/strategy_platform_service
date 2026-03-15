"""add_strategy_pair_metrics

创建 strategy_pair_metrics 表，用于持久化每个"策略 × 币种 × 周期"组合的绩效指标。
- upgrade(): 创建 datasource ENUM 类型，创建 strategy_pair_metrics 表及约束和索引
- downgrade(): 按相反顺序删除索引、表和 ENUM 类型

Revision ID: 006
Revises: 55d489f35f93
Create Date: 2026-03-15

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "55d489f35f93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 datasource ENUM 类型和 strategy_pair_metrics 表。"""
    # 创建 datasource ENUM 类型（与 taskstatus / signaldirection 命名风格一致）
    datasource_enum = postgresql.ENUM("backtest", "live", name="datasource", create_type=False)
    datasource_enum.create(op.get_bind(), checkfirst=True)

    # 创建 strategy_pair_metrics 表
    op.create_table(
        "strategy_pair_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        # 绩效指标字段（均可空，支持 COALESCE upsert 语义）
        sa.Column("total_return", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        # 元数据字段（使用 postgresql.ENUM 引用已创建的类型，不重复创建）
        sa.Column(
            "data_source",
            postgresql.ENUM("backtest", "live", name="datasource", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # 外键约束：strategy_id → strategies.id (ON DELETE CASCADE)
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            ondelete="CASCADE",
        ),
        # 主键约束
        sa.PrimaryKeyConstraint("id"),
        # (strategy_id, pair, timeframe) 三元唯一约束（需求 1.2）
        sa.UniqueConstraint(
            "strategy_id",
            "pair",
            "timeframe",
            name="uq_spm_strategy_pair_tf",
        ),
    )

    # 创建索引
    op.create_index(
        "idx_spm_strategy_id",
        "strategy_pair_metrics",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        "idx_spm_strategy_pair_tf",
        "strategy_pair_metrics",
        ["strategy_id", "pair", "timeframe"],
        unique=False,
    )
    op.create_index(
        "idx_spm_last_updated_at",
        "strategy_pair_metrics",
        ["last_updated_at"],
        unique=False,
    )


def downgrade() -> None:
    """按相反顺序删除索引、表和 ENUM 类型。"""
    # 删除索引
    op.drop_index("idx_spm_last_updated_at", table_name="strategy_pair_metrics")
    op.drop_index("idx_spm_strategy_pair_tf", table_name="strategy_pair_metrics")
    op.drop_index("idx_spm_strategy_id", table_name="strategy_pair_metrics")

    # 删除表
    op.drop_table("strategy_pair_metrics")

    # 删除 datasource ENUM 类型
    op.execute("DROP TYPE IF EXISTS datasource")
