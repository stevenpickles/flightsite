"""Learned schedules and the restricted status on ``route_cache``.

Slice 070 turns the route cache from a per-day ledger into a per-callsign one
(``docs/DATA_MODEL.md`` §7), and two of those changes are schema:

* **``confirmations`` and ``first_fetched_ms``.** A refresh that returns the
  same pair of airports on a *different* calendar day increments the count, and
  at three the row's expiry is pushed 30 days out. That makes a scheduled
  service cost one lookup a month rather than one a week, and it is a fact
  about the row, so it is stored on the row.
* **``restricted`` joins the status vocabulary.** An HTTP 451 is the provider
  answering that a flight is legally withheld (issue #165); before this it had
  nowhere to be recorded, so one business jet was re-requested nine times in
  twelve minutes and tripped the circuit breaker twice.

Why the table is rebuilt rather than altered
--------------------------------------------

SQLite cannot alter a ``CHECK`` constraint in place, and ``route_cache`` is
``WITHOUT ROWID`` — which Alembic's batch mode reconstructs from *reflection*,
where neither the ``WITHOUT ROWID`` clause nor the check predicate survives
reliably. So the rebuild is spelled out: create the new shape, copy every row
into it, drop the old table, rename. The copy is a plain ``INSERT ... SELECT``
over a table bounded by expiry-pruning to at most a few thousand rows.

The rows carried over keep their day-bucketed keys (``DAL1234:2026-09-03``).
They are deliberately not rewritten: they expire within hours of the upgrade
and the reader never asks for them again, whereas a rewrite would have to
choose which of a callsign's several dated rows became the undated one.

Revision ID: 0014
Revises: 0013
Created: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "route_cache"
_TEMPORARY = "route_cache_rebuild"
_INDEX = "ix_route_cache_expiry"

#: The vocabulary this revision installs, and the one it restores on the way
#: down. Both are spelled out rather than imported from
#: :data:`flightsite.db.models.ROUTE_CACHE_STATUS_CHECK`: a migration records
#: what an install ran, so a later slice adding a status must not retroactively
#: change what this one created. A drift test at head keeps the two in step.
_STATUS_CHECK = "status IN ('ok', 'not_found', 'restricted', 'error')"
_PREVIOUS_STATUS_CHECK = "status IN ('ok', 'not_found', 'error')"

#: Columns every version of the table shares, in the order both copies use.
_CARRIED = (
    "cache_key",
    "status",
    "origin_ident",
    "destination_ident",
    "payload_json",
    "fetched_ms",
    "expires_ms",
)


def _create(name: str, *, status_check: str, learned: bool) -> None:
    """Create one shape of ``route_cache`` under ``name``."""
    columns: list[Any] = [
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("origin_ident", sa.Text(), nullable=True),
        sa.Column("destination_ident", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("fetched_ms", sa.Integer(), nullable=False),
        sa.Column("expires_ms", sa.Integer(), nullable=False),
    ]
    if learned:
        columns.extend(
            (
                sa.Column(
                    "confirmations", sa.Integer(), nullable=False, server_default=sa.text("0")
                ),
                sa.Column("first_fetched_ms", sa.Integer(), nullable=True),
            )
        )
    op.create_table(
        name,
        *columns,
        sa.CheckConstraint(status_check, name="ck_route_cache_status"),
        sa.PrimaryKeyConstraint("cache_key"),
        sqlite_with_rowid=False,
    )


def _copy(source: str, destination: str) -> None:
    """Move every row of ``source`` into ``destination``, shared columns only."""
    carried = ", ".join(_CARRIED)
    op.execute(f"INSERT INTO {destination} ({carried}) SELECT {carried} FROM {source}")


def _replace(*, status_check: str, learned: bool) -> None:
    """Rebuild ``route_cache`` into the requested shape, keeping its rows."""
    op.drop_index(_INDEX, table_name=_TABLE)
    _create(_TEMPORARY, status_check=status_check, learned=learned)
    _copy(_TABLE, _TEMPORARY)
    op.drop_table(_TABLE)
    op.rename_table(_TEMPORARY, _TABLE)
    op.create_index(_INDEX, _TABLE, ["expires_ms"])


def upgrade() -> None:
    _replace(status_check=_STATUS_CHECK, learned=True)


def downgrade() -> None:
    # A `restricted` row cannot exist under the older CHECK, and it is a cache
    # entry: deleting it costs one lookup the next time that callsign is heard,
    # which is exactly what the build being downgraded to would have done with
    # the 451 anyway.
    op.execute(f"DELETE FROM {_TABLE} WHERE status = 'restricted'")
    _replace(status_check=_PREVIOUS_STATUS_CHECK, learned=False)
