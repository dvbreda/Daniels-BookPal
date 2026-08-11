"""vertaalgroep per hoofdstuk en voorkeur per abonnement

Een bron kan dezelfde aflevering meerdere keren hebben, vertaald door
verschillende groepen. Welke dat is, is het enige onderscheid — nummer, volume
en paginatelling zijn gelijk. Daarom staat de groep nu op het hoofdstuk, en kan
per abonnement een voorkeur worden vastgelegd.

Revision ID: 0f9237d2a144
Revises: 9638a53a3591
Create Date: 2026-08-11 09:28:01.690608

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f9237d2a144"
down_revision: str | Sequence[str] | None = "9638a53a3591"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("book", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_group_id", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("source_group_name", sa.String(length=200), nullable=True))

    with op.batch_alter_table("subscription", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preferred_group_id", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column(
                "available_groups",
                sa.JSON(),
                nullable=False,
                # Zonder server-default kan deze kolom niet bij bestaande
                # abonnementen: die zouden NULL krijgen op een NOT NULL-kolom.
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("subscription", schema=None) as batch_op:
        batch_op.drop_column("available_groups")
        batch_op.drop_column("preferred_group_id")

    with op.batch_alter_table("book", schema=None) as batch_op:
        batch_op.drop_column("source_group_name")
        batch_op.drop_column("source_group_id")
