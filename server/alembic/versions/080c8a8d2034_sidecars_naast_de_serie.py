"""sidecars naast de serie

Waar de sidecars van een serie staan wordt voortaan onthouden in plaats van
elke keer uitgerekend. Een serie kan verhuizen — van een download naar je eigen
map, of naar een andere root — en dan zou een uitgerekend pad ineens ergens
anders uitkomen. Alles wat daar stond (vertalingen, ingekleurde pagina's, en
dat is geld) zou dan onvindbaar zijn, zonder foutmelding.

Leeg voor bestaande series: die krijgen hun plek bij het eerste gebruik, of
door de eenmalige verhuizing bij het opstarten.

Revision ID: 080c8a8d2034
Revises: ab35d0415c2b
Create Date: 2026-08-13 21:11:07.324877

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "080c8a8d2034"
down_revision: str | Sequence[str] | None = "ab35d0415c2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("series", sa.Column("sidecar_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("series", "sidecar_path")
