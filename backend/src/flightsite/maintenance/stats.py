"""Measuring the database: SQLite's page accounting and the filesystem's view.

Two sources, because neither answers the whole question. ``PRAGMA page_count``
and ``PRAGMA freelist_count`` describe the logical database — how much of it is
dead space a ``VACUUM`` would reclaim — and say nothing about the ``-wal``
sidecar or the card it all sits on. ``stat()`` and ``disk_usage()`` describe the
bytes actually consumed, and know nothing about which of them are free pages.
:class:`~flightsite.maintenance.model.DatabaseStats` carries both.

The pragmas are read on a **read** session. They are queries, they cost a page
lookup each, and taking the single writer lock hourly to ask how big the file is
would be exactly the kind of avoidable contention this slice exists to prevent.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from flightsite.db.engine import Database
from flightsite.maintenance.model import DatabaseStats

#: Suffix SQLite appends to the database filename for the write-ahead log.
WAL_SUFFIX = "-wal"


def wal_path(database_file: Path) -> Path:
    """Path of the ``-wal`` sidecar beside ``database_file``.

    A literal suffix on the whole name, not a replacement of the extension:
    SQLite writes ``flightsite.sqlite3-wal``, not ``flightsite-wal``.
    """
    return database_file.with_name(database_file.name + WAL_SUFFIX)


def _size_of(path: Path) -> int:
    """Size of ``path`` in bytes, or ``0`` if it does not exist.

    A missing ``-wal`` is the normal state of a cleanly closed database, and a
    missing main file is a database nothing has written to yet. Neither is an
    error worth failing a measurement over.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _free_space(directory: Path) -> int:
    """Free bytes on the filesystem holding ``directory``, or ``0`` if unknown."""
    try:
        return shutil.disk_usage(directory).free
    except OSError:  # pragma: no cover - platform-dependent failure
        return 0


async def gather_stats(database: Database) -> DatabaseStats:
    """Measure ``database``: its pages, its freelist, and its files."""
    async with database.read_session() as session:
        connection = await session.connection()
        page_count = int((await connection.exec_driver_sql("PRAGMA page_count")).scalar_one())
        page_size = int((await connection.exec_driver_sql("PRAGMA page_size")).scalar_one())
        freelist = int((await connection.exec_driver_sql("PRAGMA freelist_count")).scalar_one())

    path = database.path
    return DatabaseStats(
        page_count=page_count,
        page_size=page_size,
        freelist_count=freelist,
        file_bytes=_size_of(path),
        wal_bytes=_size_of(wal_path(path)),
        free_bytes=_free_space(path.parent),
    )


__all__ = ["WAL_SUFFIX", "gather_stats", "wal_path"]
