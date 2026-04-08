"""partial_unique_trading_signals_realtime

把 trading_signals 的 (strategy_id, pair, timeframe) 唯一索引改为
partial unique index，只约束 signal_source='realtime'，允许
signal_source='backtest' 追加多条历史信号（回测一次会生成上千笔 trade，
每笔都要落 trading_signals 做溯源，不能被 realtime 唯一约束挡住）。

Realtime 侧的 upsert 会在同一迁移里把 ON CONFLICT 子句加上
`WHERE signal_source = 'realtime'` 匹配这个 partial index。

Revision ID: 008
Revises: 756376e45908
Create Date: 2026-04-08
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, Sequence[str], None] = "756376e45908"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """丢弃旧的 full unique index，新建 partial unique index。"""
    # 1. 删除旧的全表唯一索引
    op.drop_index("uq_trading_signals_strategy_pair_tf", table_name="trading_signals")

    # 2. 新建 partial unique index，仅 realtime 信号受唯一性约束
    op.execute(
        """
        CREATE UNIQUE INDEX uq_trading_signals_strategy_pair_tf
        ON trading_signals (strategy_id, pair, timeframe)
        WHERE signal_source = 'realtime'
        """
    )


def downgrade() -> None:
    """回滚为全表唯一索引（需要先清理 backtest 重复数据）。"""
    # 先删除 partial index
    op.drop_index("uq_trading_signals_strategy_pair_tf", table_name="trading_signals")

    # 清理重复 backtest 记录（保留每组最新一条）
    op.execute(
        """
        DELETE FROM trading_signals
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM trading_signals
            GROUP BY strategy_id, pair, timeframe
        )
        """
    )

    # 恢复为全表 unique index
    op.create_index(
        "uq_trading_signals_strategy_pair_tf",
        "trading_signals",
        ["strategy_id", "pair", "timeframe"],
        unique=True,
    )
