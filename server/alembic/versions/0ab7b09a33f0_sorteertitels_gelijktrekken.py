"""sorteertitels gelijktrekken

Revision ID: 0ab7b09a33f0
Revises: 6f74486915ef
Create Date: 2026-08-12 16:55:39.671059

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0ab7b09a33f0'
down_revision: str | Sequence[str] | None = '6f74486915ef'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Spiegelt bookpal/metadata/filename.py::sort_title. Bewust hier herhaald: een
# migratie hoort niet mee te veranderen als die functie later opschuift.
_ARTICLES = ("de ", "het ", "een ", "the ", "a ", "an ", "l\'", "le ", "la ", "les ")


def _sort_title(title: str) -> str:
    lowered = title.strip()
    for article in _ARTICLES:
        if lowered.lower().startswith(article):
            return (lowered[len(article) :].strip() or lowered).lower()
    return lowered.lower()


def upgrade() -> None:
    """Sorteertitels gelijktrekken.

    De scanner bewaarde ze met hoofdletters, het volgen van een bron zonder.
    SQLite sorteert op tekencode, dus "Claire" kwam vóór "crayon" en viel de
    bibliotheeklijst in tweeën uiteen — in de web-app, in Lite en in OPDS.
    """
    bind = op.get_bind()
    rijen = bind.execute(sa.text("SELECT id, title FROM series")).fetchall()
    for series_id, titel in rijen:
        bind.execute(
            sa.text("UPDATE series SET sort_title = :sort WHERE id = :id"),
            {"sort": _sort_title(titel or ""), "id": series_id},
        )


def downgrade() -> None:
    """Niets terug te draaien: dit is een afgeleide waarde."""
