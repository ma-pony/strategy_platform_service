"""add_trading_signals_constraints

为 trading_signals 表添加以下约束和索引：
  1. UNIQUE(strategy_id, pair, timeframe) — 支持 upsert 语义（需求 3.2）
  2. INDEX(created_at DESC) — 加速时间范围查询（需求 3.3）
  3. timeframe 列改为 NOT NULL（如当前为 NULLABLE）
  4. signal_source 列默认值确认为 'realtime'

迁移前置条件：
  - 若存在 (strategy_id, pair, timeframe) 重复记录，先保留最新一条（created_at 最大）
  - 可能需要手动清理或在 upgrade 前执行 DELETE 去重 SQL

回滚说明：
  downgrade 删除新增索引，将 timeframe 改回 NULLABLE

Revision ID: 007
Revises: 006
Create Date: 2026-03-15
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, Sequence[str], None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加唯一约束、索引，并补全 NOT NULL 约束。"""

    # 1. 清理 (strategy_id, pair, timeframe) 重复记录，保留最新一条（created_at 最大）
    #    使用 DELETE ... WHERE id NOT IN (SELECT MAX(id) ...) 语法清理旧记录
    op.execute(
        """
        DELETE FROM trading_signals
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM trading_signals
            WHERE timeframe IS NOT NULL
            GROUP BY strategy_id, pair, timeframe
        )
        AND timeframe IS NOT NULL
        """
    )

    # 2. 为 timeframe 为 NULL 的记录设置默认值 '1h'
    op.execute("UPDATE trading_signals SET timeframe = '1h' WHERE timeframe IS NULL")

    # 3. 将 timeframe 列改为 NOT NULL（需求 3.1）
    op.alter_column(
        "trading_signals",
        "timeframe",
        existing_type=sa.String(16),
        nullable=False,
    )

    # 4. 确保 signal_source 列存在，并设置默认值（如不存在则添加）
    # 注意：该列在 004 迁移中可能已通过 ORM 模型隐式存在，此处通过 SQL 检查
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'trading_signals'
                AND column_name = 'signal_source'
            ) THEN
                ALTER TABLE trading_signals
                ADD COLUMN signal_source VARCHAR(32) NOT NULL DEFAULT 'realtime';
            END IF;
        END;
        $$;
        """
    )

    # 5. 添加 UNIQUE(strategy_id, pair, timeframe) 唯一索引（需求 3.2）
    op.create_index(
        "uq_trading_signals_strategy_pair_tf",
        "trading_signals",
        ["strategy_id", "pair", "timeframe"],
        unique=True,
    )

    # 6. 添加 created_at 降序索引，加速时间范围查询（需求 3.3）
    op.create_index(
        "idx_signal_created_at",
        "trading_signals",
        [sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删除新增索引，恢复 timeframe 为 NULLABLE。"""

    # 删除 created_at 索引
    op.drop_index("idx_signal_created_at", table_name="trading_signals")

    # 删除唯一索引
    op.drop_index("uq_trading_signals_strategy_pair_tf", table_name="trading_signals")

    # 恢复 timeframe 为 NULLABLE
    op.alter_column(
        "trading_signals",
        "timeframe",
        existing_type=sa.String(16),
        nullable=True,
    )
