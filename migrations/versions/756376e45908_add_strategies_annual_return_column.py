"""add strategies.annual_return column

Revision ID: 756376e45908
Revises: d018430aa6f1
Create Date: 2026-04-08 09:18:11.247013

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "756376e45908"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d018430aa6f1"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("strategies", sa.Column("annual_return", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("strategies", "annual_return")
