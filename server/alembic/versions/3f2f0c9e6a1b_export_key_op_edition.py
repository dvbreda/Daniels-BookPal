"""export_key op edition

Revision ID: 3f2f0c9e6a1b
Revises: 080c8a8d2034
Create Date: 2026-08-16 13:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3f2f0c9e6a1b'
down_revision: str | Sequence[str] | None = '080c8a8d2034'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('edition', schema=None) as batch_op:
        batch_op.add_column(sa.Column('export_key', sa.String(length=60), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('edition', schema=None) as batch_op:
        batch_op.drop_column('export_key')
