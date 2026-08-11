"""sort_volume voor correcte leesvolgorde, en authors op Series

Zonder sort_volume sorteert een reeks puur op hoofdstuknummer, en dat nummer
telt meestal opnieuw per deel: hoofdstuk 1 van deel 1, deel 2, deel 10 kwamen
zo naast elkaar te staan in scan-volgorde in plaats van leesvolgorde.

``authors`` stond al in elke format-parser (ComicInfo, epub-OPF,
pdf-metadata), maar niets bewaarde het — nodig voor de titel+auteur-matching
die Goodreads' CSV-import gebruikt (M7).

Revision ID: ecc70982777c
Revises: 0f9237d2a144
Create Date: 2026-08-11 14:11:13.203712

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ecc70982777c"
down_revision: str | Sequence[str] | None = "0f9237d2a144"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalise(raw: str | None) -> float:
    """Zelfde regel als bookpal.metadata.filename.normalise_number, hier
    zelfstandig: een migratie moet blijven werken ook als die functie later
    verandert."""
    if raw is None:
        return float("inf")
    try:
        return float(raw)
    except ValueError:
        match = re.search(r"\d+(?:\.\d+)?", raw)
        return float(match.group()) if match else float("inf")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("book", schema=None) as batch_op:
        # Server-default nodig: zonder dat kan een NOT NULL-kolom niet bij
        # bestaande boeken. inf ("geen deel") is de default die de code ook
        # gebruikt voor een boek zonder volume — zie normalise_number.
        #
        # Let op: DEFAULT 'inf' zou een tekststring opleveren (SQLite herkent
        # dat woord niet als getal), en dat sorteert anders dan de echte
        # IEEE-754 oneindig die Python's float("inf") wegschrijft. 1e999 loopt
        # over tot diezelfde REAL-oneindig — geverifieerd, geen aanname.
        batch_op.add_column(
            sa.Column(
                "sort_volume", sa.Float(), nullable=False, server_default=sa.text("1e999")
            )
        )
        batch_op.drop_index(batch_op.f("ix_book_series_sort"))
        batch_op.create_index(
            "ix_book_series_sort", ["series_id", "sort_volume", "sort_number"], unique=False
        )

    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("authors", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )

    # Backfill: de server-default hierboven geldt alleen voor nieuwe rijen.
    # Bestaande boeken met een volume moeten dat volume ook echt in
    # sort_volume terugkrijgen, anders blijven ze op "geen deel" staan.
    connection = op.get_bind()
    book = sa.table("book", sa.column("id", sa.Integer), sa.column("volume", sa.String))
    rows = connection.execute(sa.select(book.c.id, book.c.volume)).fetchall()
    for row_id, volume in rows:
        if volume is None:
            continue
        connection.execute(
            sa.text("UPDATE book SET sort_volume = :value WHERE id = :id"),
            {"value": _normalise(volume), "id": row_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.drop_column("authors")

    with op.batch_alter_table("book", schema=None) as batch_op:
        batch_op.drop_index("ix_book_series_sort")
        batch_op.create_index(
            batch_op.f("ix_book_series_sort"), ["series_id", "sort_number"], unique=False
        )
        batch_op.drop_column("sort_volume")
