"""Migration test harness.

Everything a migration test needs to build a database at a chosen revision,
upgrade it, and then inspect the resulting schema *from the outside* — with
stdlib ``sqlite3``, deliberately not through the ORM, so that a test asserting
"the migration created this column" cannot be satisfied by the model
declaration alone.

Used by ``test_migrations.py`` (empty upgrade, fixture upgrade, drift, single
head) and reusable by every later migration-bearing slice.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection

from flightsite.db import Database
from flightsite.db.models import Base

#: Revision that first created the schema. Fixture databases are built here and
#: upgraded forward, which is the upgrade path an existing install takes.
INITIAL_REVISION = "0001"


@asynccontextmanager
async def database_at(path: Path, revision: str = "head") -> AsyncIterator[Database]:
    """Open a database at ``path`` upgraded to ``revision``, disposing on exit."""
    database = Database(path)
    try:
        await database.upgrade_to(revision)
        yield database
    finally:
        await database.dispose()


async def upgrade_empty_database(path: Path, revision: str = "head") -> str | None:
    """Upgrade a not-yet-existing database to ``revision``.

    Returns the revision stamped in the resulting file.
    """
    async with database_at(path, revision) as database:
        return await database.current_revision()


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the database file with stdlib ``sqlite3``, committing and closing.

    Closing matters: a lingering handle keeps a ``-wal`` sidecar alive, and the
    corruption fixtures need every byte checkpointed into the main file before
    they rewrite it.
    """
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def table_names(path: Path) -> set[str]:
    """Names of every user table in the database file."""
    with _connect(path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def column_types(path: Path, table: str) -> dict[str, str]:
    """Map of column name to declared SQL type for ``table``."""
    with _connect(path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]): str(row[2]) for row in rows}


def not_null_columns(path: Path, table: str) -> set[str]:
    """Columns of ``table`` declared ``NOT NULL``."""
    with _connect(path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows if row[3]}


def primary_key_columns(path: Path, table: str) -> list[str]:
    """Primary-key columns of ``table``, in key order."""
    with _connect(path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    keyed = sorted((int(row[5]), str(row[1])) for row in rows if row[5])
    return [name for _, name in keyed]


def create_sql(path: Path, table: str) -> str:
    """The ``CREATE TABLE`` statement SQLite stored for ``table``."""
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    return str(row[0]) if row else ""


def index_names(path: Path, table: str) -> set[str]:
    """Names of every index SQLite holds for ``table``.

    Includes the implicit ``sqlite_autoindex_*`` entries a ``UNIQUE`` column
    creates, which is how a test can assert uniqueness was actually enforced
    rather than merely declared.
    """
    with _connect(path) as connection:
        rows = connection.execute(f"PRAGMA index_list({table})").fetchall()
    return {str(row[1]) for row in rows}


def index_sql(path: Path, name: str) -> str:
    """The ``CREATE INDEX`` statement SQLite stored for ``name``.

    Empty for implicit indexes, which have no statement of their own.
    """
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
        ).fetchone()
    return str(row[0]) if row and row[0] else ""


def foreign_keys(path: Path, table: str) -> set[tuple[str, str, str]]:
    """``(column, referenced table, referenced column)`` for each foreign key."""
    with _connect(path) as connection:
        rows = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return {(str(row[3]), str(row[2]), str(row[4])) for row in rows}


def seed_meta_rows(path: Path, rows: Mapping[str, str], *, updated_ms: int = 1) -> None:
    """Insert ``meta`` rows directly, bypassing the ORM.

    A fixture database has to be populated the way a real one was populated by
    an *older* version of the code, so the seeding must not depend on today's
    models.
    """
    with _connect(path) as connection:
        connection.executemany(
            "INSERT INTO meta (key, value, updated_ms) VALUES (?, ?, ?)",
            [(key, value, updated_ms) for key, value in rows.items()],
        )


def read_meta_rows(path: Path) -> dict[str, str]:
    """Read every ``meta`` row as a plain key/value mapping."""
    with _connect(path) as connection:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _compare(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "render_as_batch": True}
    )
    return list(compare_metadata(context, Base.metadata))


async def autogenerate_diffs(database: Database) -> list[Any]:
    """Differences Alembic autogenerate sees between the models and the schema.

    This is the ``alembic check`` gate as a test: an empty list means the
    migrations and :class:`flightsite.db.models.Base` agree.
    """
    async with database.read_session() as session:
        connection = await session.connection()
        return await connection.run_sync(_compare)
