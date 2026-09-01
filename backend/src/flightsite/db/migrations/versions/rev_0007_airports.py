"""The airport dataset table.

Creates ``airports`` (``docs/DATA_MODEL.md`` §3.6), the one table slice 027
owns. The sighting columns the inference *writes* — ``inferred_airport_ident``
and ``inferred_phase`` — already exist: revision 0002 created them with the
rest of ``sightings``, and the ``inferred_phase`` ``CHECK`` already names
``arriving`` and ``departing``. So this revision adds a table and alters
nothing, which is why it needs no backfill and why its downgrade is a plain
drop.

No staging table, unlike the aircraft-metadata import. The airport dataset is
~70k narrow rows where a metadata snapshot is half a million wide ones, so
:class:`flightsite.airports.sink.AirportImportSink` buffers a run in memory and
replaces the table in a single transaction instead. The guarantee is the same
one ``docs/DATA_MODEL.md`` §3.2 states for metadata — *a failed import leaves
the previous dataset untouched* — reached by a shorter route, and it keeps the
schema exactly what §3.6 documents.

``ix_airports_lat`` covers ``(lat, lon)`` per §3.6: nearest-airport lookup is a
bounding box on that index refined by great-circle in code, which at this row
count needs no R*Tree — and SQLite ships none by default, so requiring one
would be a new dependency for a table that does not need it. ``ix_airports_iata``
is partial because only about one row in eight carries an IATA code.

Revision ID: 0007
Revises: 0006
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "airports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ident", sa.Text(), nullable=False),
        sa.Column("iata", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("lat", sa.REAL(), nullable=False),
        sa.Column("lon", sa.REAL(), nullable=False),
        sa.Column("elevation_ft", sa.Integer(), nullable=True),
        sa.Column("iso_country", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ident"),
    )
    op.create_index("ix_airports_lat", "airports", ["lat", "lon"])
    op.create_index(
        "ix_airports_iata",
        "airports",
        ["iata"],
        sqlite_where=sa.text("iata IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_airports_iata", table_name="airports")
    op.drop_index("ix_airports_lat", table_name="airports")
    op.drop_table("airports")
