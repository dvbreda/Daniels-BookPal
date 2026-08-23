"""publicatiedatum per deel

Revision ID: 7c1e4b2a9d33
Revises: 3f2f0c9e6a1b
Create Date: 2026-08-23 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c1e4b2a9d33'
down_revision: str | Sequence[str] | None = '3f2f0c9e6a1b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('book', schema=None) as batch_op:
        batch_op.add_column(sa.Column('published_year', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('published_month', sa.Integer(), nullable=True))
        batch_op.create_index('ix_book_published_year', ['published_year'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('book', schema=None) as batch_op:
        batch_op.drop_index('ix_book_published_year')
        batch_op.drop_column('published_month')
        batch_op.drop_column('published_year')
