"""cover_page_index: handmatige paginakeuze voor de omslag

"Pagina 1" is niet altijd de omslag, en niet elke serie heeft een bron met
een schone versie ernaast. Wint van cover_url zodra gezet.

Revision ID: 6dab0ba1797f
Revises: 8529bc32a107
Create Date: 2026-08-11 14:54:19.827859

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6dab0ba1797f"
down_revision: str | Sequence[str] | None = "8529bc32a107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover_page_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.drop_column("cover_page_index")
