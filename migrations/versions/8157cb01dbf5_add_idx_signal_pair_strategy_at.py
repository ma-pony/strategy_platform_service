"""add_idx_signal_pair_strategy_at

Revision ID: 8157cb01dbf5
Revises: 008
Create Date: 2026-04-15 21:22:49.629808

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "8157cb01dbf5"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "008"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_signal_pair_strategy_at",
        "trading_signals",
        ["pair", "strategy_id", "signal_at"],
        postgresql_ops={"signal_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_signal_pair_strategy_at", table_name="trading_signals")
