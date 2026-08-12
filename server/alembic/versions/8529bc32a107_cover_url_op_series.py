"""cover_url op series

De officiële omslag van een bron (M5/M7), voor wanneer "pagina 1 van het
eerste boek" niet klopt — bij scanlaties staat daar vaak een credits-pagina
van de vertaalgroep over de echte omslag heen.

Revision ID: 8529bc32a107
Revises: ecc70982777c
Create Date: 2026-08-11 14:28:09.791770

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8529bc32a107"
down_revision: str | Sequence[str] | None = "ecc70982777c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.drop_column("cover_url")
