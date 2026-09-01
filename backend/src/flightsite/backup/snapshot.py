"""SQLite-safe snapshotting, and reading a snapshot's provenance.

Why ``VACUUM INTO`` rather than the online backup API
-----------------------------------------------------

FlightSite backs up a database that a live process is writing to: the
write-behind persistence worker commits a batch every flush interval
(ADR-0008). Both SQLite-safe options were considered and ``VACUUM INTO`` wins
on this workload:

* **The online backup API** (``sqlite3_backup_step`` / Python's
  ``Connection.backup``) copies pages incrementally, and SQLite *restarts the
  copy from the beginning* whenever the source database is written through a
  different connection mid-copy. Against a continuously writing FlightSite that
  is a livelock risk on a multi-gigabyte history. Copying in a single step
  instead avoids the restart, but only by holding a read lock over the whole
  copy — which stalls the writer, and ADR-0008's whole point is that ingestion
  never blocks on disk.
* **``VACUUM INTO``** runs inside one ordinary read transaction. ADR-0001 puts
  the database in ``journal_mode=WAL``, where a reader neither blocks nor is
  blocked by the writer, so the snapshot is a consistent point-in-time image of
  the database *as of the read transaction's start* and the persistence worker
  keeps committing throughout. It also writes a compacted, fully materialized
  single file: no ``-wal``/``-shm`` sidecars to carry into the archive, and no
  possibility of shipping a main file whose committed tail is still in a WAL
  the archive does not contain.

The snapshot is taken through this module's **own** stdlib ``sqlite3``
connection, never through :class:`~flightsite.db.engine.Database`. That keeps
the command usable when the app is stopped (there is no ``Database`` to borrow)
and, when the app *is* running, keeps the backup off the writer lock entirely —
it is a reader, and readers do not queue behind the writer under WAL.

``busy_timeout`` is set to the same value the application uses so a snapshot
taken at the instant of a checkpoint waits rather than failing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

from flightsite.backup.errors import SnapshotError
from flightsite.backup.manifest import MetadataSourceEntry, utc_iso_from_ms
from flightsite.db import migrate
from flightsite.db.engine import BUSY_TIMEOUT_MS

#: Seconds the snapshot connection waits for a locked database before failing.
SNAPSHOT_TIMEOUT_S = BUSY_TIMEOUT_MS / 1000

#: Table the metadata framework (slice 021) keeps per-source import status in.
METADATA_SOURCES_TABLE = "metadata_sources"


def _connect(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-oriented, in autocommit mode.

    ``isolation_level=None`` matters: Python's legacy transaction handling would
    otherwise wrap statements in an implicit transaction, and ``VACUUM`` cannot
    run inside one.
    """
    connection = sqlite3.connect(path, timeout=SNAPSHOT_TIMEOUT_S, isolation_level=None)
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return connection


def vacuum_into(source: Path, destination: Path) -> None:
    """Write a consistent snapshot of ``source`` to ``destination``.

    Safe to run while FlightSite is writing to ``source``; see this module's
    docstring for why ``VACUUM INTO`` is the mechanism.

    Raises:
        SnapshotError: if ``source`` does not exist, ``destination`` already
            exists (``VACUUM INTO`` refuses to overwrite), or SQLite fails.
    """
    if not source.exists():
        raise SnapshotError(f"no database to back up at {source}")
    if destination.exists():
        raise SnapshotError(f"snapshot destination already exists: {destination}")

    connection = _connect(source)
    try:
        # Bound parameter rather than string interpolation: the INTO clause
        # takes an expression, so the path never becomes SQL.
        connection.execute("VACUUM INTO ?", (destination.as_posix(),))
    except sqlite3.Error as exc:
        destination.unlink(missing_ok=True)
        raise SnapshotError(f"SQLite snapshot of {source} failed: {exc}") from exc
    finally:
        connection.close()


def quick_check(path: Path) -> list[str]:
    """Run ``PRAGMA quick_check`` against a database file.

    A healthy database returns ``["ok"]``. Used to prove a snapshot is sound
    before it is archived.
    """
    connection = _connect(path)
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as exc:
        raise SnapshotError(f"integrity check of {path} failed: {exc}") from exc
    finally:
        connection.close()
    return [str(row[0]) for row in rows]


def snapshot_revision(path: Path) -> str | None:
    """The Alembic revision stamped in the database at ``path``.

    Read from the *snapshot*, not from the live database, so the manifest
    describes exactly the bytes in the archive.
    """
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.connect() as connection:
            return migrate.current_revision(connection)
    finally:
        engine.dispose()


def metadata_source_entries(path: Path) -> tuple[MetadataSourceEntry, ...]:
    """Per-source dataset versions recorded in the database at ``path``.

    Returns an empty tuple when the table does not exist — a backup taken from
    a database older than the metadata framework is still a valid backup.
    """
    connection = _connect(path)
    try:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (METADATA_SOURCES_TABLE,),
        ).fetchone()
        if present is None:
            return ()
        # The table name is a module constant, never caller input.
        rows = connection.execute(
            f"SELECT source, dataset_version, last_success_ms FROM {METADATA_SOURCES_TABLE} "
            "ORDER BY source"
        ).fetchall()
    except sqlite3.Error as exc:
        raise SnapshotError(f"reading metadata sources from {path} failed: {exc}") from exc
    finally:
        connection.close()

    return tuple(
        MetadataSourceEntry(
            source=str(row[0]),
            dataset_version=None if row[1] is None else str(row[1]),
            last_success=utc_iso_from_ms(None if row[2] is None else int(row[2])),
        )
        for row in rows
    )


__all__ = [
    "METADATA_SOURCES_TABLE",
    "SNAPSHOT_TIMEOUT_S",
    "metadata_source_entries",
    "quick_check",
    "snapshot_revision",
    "vacuum_into",
]
