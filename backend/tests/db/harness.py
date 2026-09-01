"""Migration and corruption test harness.

Everything a migration test needs to build a database at a chosen revision,
upgrade it, and then inspect the resulting schema *from the outside* — with
stdlib ``sqlite3``, deliberately not through the ORM, so that a test asserting
"the migration created this column" cannot be satisfied by the model
declaration alone.

Also the two corruption fixtures, which are shared for the same reason: slice
005 checks corruption at startup and slice 044 checks it again on the
maintenance cycle, and a drill that smashes bytes differently in each place
would be testing two different failure modes while claiming to test one.

Used by ``test_migrations.py`` (empty upgrade, fixture upgrade, drift, single
head), ``test_startup.py`` and ``tests/maintenance/``, and reusable by every
later migration-bearing slice.
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

from flightsite.db import Database, MetaRepository
from flightsite.db.models import Base

#: Revision that first created the schema. Fixture databases are built here and
#: upgraded forward, which is the upgrade path an existing install takes.
INITIAL_REVISION = "0001"

#: Byte written over a page being deliberately destroyed. Any non-zero filler
#: works; a recognisable one makes a hex dump of a failed drill readable.
CORRUPTION_BYTE = 0xA5

#: SQLite's default page size, which is what these databases are built with.
SQLITE_PAGE_SIZE = 4096

#: ``meta`` rows written before corrupting, so the file has data pages beyond
#: the schema worth smashing at all.
FILLER_ROWS = 400


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


def write_garbage(path: Path) -> None:
    """Replace the database with bytes that are not a SQLite file at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a sqlite database" * 200)


def _schema_survives(path: Path) -> bool:
    """True if the schema and the Alembic stamp are still readable.

    Exactly the two things the migration step touches on an already-current
    database. If both answer, ``upgrade head`` succeeds and the damage is left
    for ``quick_check`` to find — which is the failure path under test.
    """
    try:
        connection = sqlite3.connect(path)
    except sqlite3.DatabaseError:  # pragma: no cover - defensive
        return False
    try:
        connection.execute("SELECT name, rootpage FROM sqlite_master").fetchall()
        connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.DatabaseError:
        return False
    finally:
        connection.close()
    return True


def smash_data_pages(path: Path) -> None:
    """Overwrite the tail of an existing database file, sparing its schema.

    The schema and the ``alembic_version`` row must stay readable, so that the
    migration step still succeeds and it is the integrity check that catches
    the damage — the failure mode slices 005 and 044 exist to surface.

    Where the schema ends is not guessed, and it is not *computed* either.
    Three computed boundaries have already gone stale: a hardcoded page 2 when
    slice 052's three tables landed; a fraction of the file when slice 024's
    table and four indexes pushed the last root page past the midpoint; and
    ``MAX(rootpage)`` itself when slice 033's five tables grew ``sqlite_master``
    past one page, putting its own overflow *above* every root page it lists.

    So the boundary is *found* instead: start at the first page past the last
    root page and walk forward until the file corrupts without taking the
    schema with it. That cannot go stale, because the property being searched
    for is the property the test needs. The filler rows are what guarantee
    there are data pages beyond the schema worth corrupting at all.
    """
    pristine = path.read_bytes()
    pages = len(pristine) // SQLITE_PAGE_SIZE

    connection = sqlite3.connect(path)
    try:
        highest = int(connection.execute("SELECT MAX(rootpage) FROM sqlite_master").fetchone()[0])
    finally:
        connection.close()

    # ``rootpage`` is 1-based, so page N occupies bytes [(N-1) * size, N * size)
    # and corrupting "from page N + 1 onward" starts at byte N * size.
    for first_smashed in range(highest, pages):
        raw = bytearray(pristine)
        for offset in range(SQLITE_PAGE_SIZE * first_smashed, len(raw)):
            raw[offset] = CORRUPTION_BYTE
        path.write_bytes(bytes(raw))
        if _schema_survives(path):
            assert pages - first_smashed >= 4, (
                f"fixture database has {pages} pages and a schema reaching page "
                f"{first_smashed}: too few data pages left to corrupt meaningfully"
            )
            return

    raise AssertionError(
        f"no boundary in a {pages}-page fixture leaves the schema readable; "
        "the fixture needs more filler rows"
    )


async def build_then_corrupt(path: Path) -> None:
    """Build a real migrated database with data pages, then corrupt them.

    Disposing the database first checkpoints the WAL into the main file, so the
    bytes being rewritten are the bytes SQLite will later read back.
    """
    database = Database(path)
    meta = MetaRepository(database)
    await database.upgrade_to("head")
    for index in range(FILLER_ROWS):
        await meta.set(f"filler-{index:04d}", "x" * 200)
    await database.dispose()

    smash_data_pages(path)


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
