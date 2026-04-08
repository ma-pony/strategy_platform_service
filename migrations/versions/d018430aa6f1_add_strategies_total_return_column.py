"""add strategies.total_return column

Revision ID: d018430aa6f1
Revises: 007
Create Date: 2026-04-08 09:03:25.665718

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d018430aa6f1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("strategies", sa.Column("total_return", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("strategies", "total_return")
