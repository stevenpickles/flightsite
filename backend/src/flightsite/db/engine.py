"""Async SQLite engine, connection pragmas, and the single-writer discipline.

FlightSite persists everything in one SQLite file inside the data directory
(``docs/ARCHITECTURE.md`` §2.1, ADR-0001). This module owns how that file is
opened and — more importantly — *who is allowed to write to it*.

Single-writer discipline
------------------------

SQLite permits exactly one writer at a time. ADR-0001 and ADR-0008 turn that
constraint into an explicit architectural rule: every write goes through one
serialized writer, and reads use separate connections that WAL keeps
unblocked. :class:`Database` enforces the rule *by construction* rather than by
convention:

* :meth:`Database.writer_session` is the only way to obtain a writable
  session. It is guarded by an :class:`asyncio.Lock`, so overlapping callers
  queue in the application instead of racing for SQLite's file lock, and it is
  bound to a writer engine capped at a single pooled connection. The session
  commits on clean exit and rolls back on any exception, which is the
  "batched short transactions" shape ADR-0008 asks for.
* :meth:`Database.read_session` hands out sessions from a separate read engine
  whose connections set ``PRAGMA query_only=ON``. A stray write on a read
  session raises instead of quietly becoming a second writer.

From slice 009 onward the write-behind persistence worker is the sole caller of
:meth:`writer_session`; API queries and analytics use :meth:`read_session`. The
lock means an accidental second writer degrades to serialization, never to
``SQLITE_BUSY`` storms or interleaved transactions.

Connection pragmas
------------------

Applied on **every** connection of both engines (SQLite pragmas are per
connection, not per database, except ``journal_mode`` which persists in the
file):

===================== ============================================================
``journal_mode=WAL``  Readers never block the writer and vice versa; survives a
                      power cut with the WAL recovery path SPEC §71 assumes.
``synchronous=NORMAL`` The WAL-appropriate durability point: safe against process
                      crashes, trading a small window on a full power loss for
                      far less SD-card wear on a Pi 4.
``foreign_keys=ON``   SQLite defaults to *off*; ADR-0001 requires it on so the
                      referential integrity in ``docs/DATA_MODEL.md`` is real.
``busy_timeout``      Waits instead of failing instantly if a lock is briefly
                      held (e.g. by a maintenance job or a backup snapshot).
``query_only``        Read engine only — makes read sessions structurally
                      incapable of writing.
===================== ============================================================
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from flightsite.db import migrate

#: Database filename inside the data directory (``docs/ARCHITECTURE.md`` §2.1).
DB_FILENAME = "flightsite.sqlite3"

#: How long SQLite waits for a held lock before raising ``SQLITE_BUSY``.
BUSY_TIMEOUT_MS = 5000

#: Concurrent read connections. Reads are short and the backend is a single
#: asyncio process, so a small pool is plenty and keeps file handles bounded.
READ_POOL_SIZE = 5

#: ``PRAGMA quick_check`` returns this single row on a healthy database.
QUICK_CHECK_OK = "ok"


def database_path(data_dir: Path) -> Path:
    """Path of the application database inside ``data_dir``."""
    return data_dir / DB_FILENAME


def sqlite_url(path: Path) -> str:
    """Async SQLAlchemy URL for a SQLite file at ``path``.

    ``as_posix`` keeps Windows paths (``C:\\...``) valid inside a URL, so the
    same code works on a developer laptop and on the Pi.
    """
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _apply_pragmas(
    dbapi_connection: DBAPIConnection,
    connection_record: ConnectionPoolEntry,
    *,
    read_only: bool,
) -> None:
    """Apply FlightSite's SQLite pragmas to a freshly opened connection."""
    cursor = dbapi_connection.cursor()
    try:
        # journal_mode must precede query_only: switching a database to WAL is
        # itself a write to the file header (a no-op returning 'wal' once set).
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        if read_only:
            cursor.execute("PRAGMA query_only=ON")
    finally:
        cursor.close()


def create_sqlite_engine(url: str, *, read_only: bool = False, **kwargs: Any) -> AsyncEngine:
    """Create an async SQLite engine with FlightSite's pragmas attached.

    Every engine that touches the FlightSite database — the writer, the
    readers, and the one Alembic's ``env.py`` builds for CLI runs — is created
    here, so there is exactly one definition of the connection contract.
    """
    engine = create_async_engine(url, **kwargs)

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(
        dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry
    ) -> None:
        _apply_pragmas(dbapi_connection, connection_record, read_only=read_only)

    return engine


class Database:
    """The application database: one writer, many readers, one schema owner.

    Construction is side-effect free — no directory is created and no
    connection opened until :meth:`upgrade_to` runs or a session is requested —
    so building a :class:`Database` in an app factory never touches the disk.
    """

    def __init__(self, path: Path, *, echo: bool = False) -> None:
        self._path = path
        url = sqlite_url(path)
        # pool_size=1/max_overflow=0 makes "one writer connection" a property of
        # the engine as well as of the lock below.
        self._writer_engine = create_sqlite_engine(
            url, read_only=False, echo=echo, pool_size=1, max_overflow=0
        )
        self._read_engine = create_sqlite_engine(
            url, read_only=True, echo=echo, pool_size=READ_POOL_SIZE, max_overflow=0
        )
        self._writer_lock = asyncio.Lock()
        self._writer_sessions = async_sessionmaker(self._writer_engine, expire_on_commit=False)
        self._read_sessions = async_sessionmaker(self._read_engine, expire_on_commit=False)

    @property
    def path(self) -> Path:
        """Filesystem path of the SQLite database file."""
        return self._path

    def ensure_directory(self) -> None:
        """Create the parent data directory if it does not exist yet."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def writer_session(self) -> AsyncIterator[AsyncSession]:
        """The single serialized writer session (ADR-0001, ADR-0008).

        Commits on clean exit, rolls back and re-raises otherwise. Never nest
        writer contexts: the guarding lock is not reentrant, and nesting would
        deadlock rather than silently open a second writer.
        """
        async with self._writer_lock, self._writer_sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        """A read-only session (``PRAGMA query_only=ON``) for queries."""
        async with self._read_sessions() as session:
            yield session

    async def upgrade_to(self, revision: str = "head") -> None:
        """Run Alembic migrations up to ``revision`` on the writer connection.

        Schema changes are writes, so they take the writer lock like any other
        write — the single-writer rule has no exemption for DDL.
        """
        self.ensure_directory()
        async with self._writer_lock:
            await migrate.upgrade(self._writer_engine, revision)

    async def downgrade_to(self, revision: str) -> None:
        """Roll the schema back to ``revision`` (SPEC §107, where practical)."""
        async with self._writer_lock:
            await migrate.downgrade(self._writer_engine, revision)

    async def current_revision(self) -> str | None:
        """The Alembic revision stamped in the database, or ``None`` if unstamped."""
        async with self._read_sessions() as session:
            connection = await session.connection()
            return await connection.run_sync(migrate.current_revision)

    async def quick_check(self) -> Sequence[str]:
        """Run ``PRAGMA quick_check`` and return its result rows.

        A healthy database returns exactly ``["ok"]``; anything else is a
        corruption report that the caller must surface.
        """
        async with self._writer_lock, self._writer_engine.connect() as connection:
            result = await connection.exec_driver_sql("PRAGMA quick_check")
            return [str(row[0]) for row in result.fetchall()]

    async def dispose(self) -> None:
        """Close both engines' pooled connections."""
        await self._writer_engine.dispose()
        await self._read_engine.dispose()
