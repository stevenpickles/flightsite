"""Backing up a database that is being written to (roadmap 043 AC 1).

The acceptance criterion is "backup during active ingestion yields a
consistent, restorable snapshot". The write pattern here mirrors the
persistence worker's: every aircraft and its sighting are inserted in **one**
writer transaction through :meth:`Database.writer_session`, so a snapshot that
tore mid-transaction would show a sighting whose aircraft row is absent. That
is the invariant the assertions below stand on — not merely "the file opens".
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from flightsite.backup import DATABASE_MEMBER, create_backup, restore_backup
from flightsite.backup.snapshot import quick_check
from flightsite.db import Database, database_path
from tests.backup.conftest import (
    fixed_clock,
    insert_pair,
    read_members,
    sqlite_rows,
    sqlite_scalar,
)


async def _write_until(database: Database, stop: asyncio.Event, *, start: int) -> int:
    """Insert aircraft+sighting pairs until ``stop`` is set; return how many."""
    written = 0
    index = start
    while not stop.is_set():
        async with database.writer_session() as session:
            await insert_pair(session, index)
        written += 1
        index += 1
        # Yield so the snapshot thread actually interleaves with the writer.
        await asyncio.sleep(0)
    return written


async def test_backup_while_the_writer_is_committing(data_dir: Path, tmp_path: Path) -> None:
    database = Database(database_path(data_dir))
    stop = asyncio.Event()
    try:
        await database.upgrade_to("head")
        writer = asyncio.create_task(_write_until(database, stop, start=1))

        # Let a few transactions land, then snapshot while the writer runs on.
        await asyncio.sleep(0.05)
        result = await asyncio.to_thread(create_backup, data_dir, now=fixed_clock())
        assert not writer.done(), "the writer stopped before the snapshot finished"

        await asyncio.sleep(0.05)
        stop.set()
        total_written = await writer
    finally:
        stop.set()
        await database.dispose()

    snapshot = tmp_path / DATABASE_MEMBER
    snapshot.write_bytes(read_members(result.path)[DATABASE_MEMBER])

    # 1. The snapshot is a sound SQLite database on its own.
    assert quick_check(snapshot) == ["ok"]

    # 2. It caught a prefix of the writer's work — neither empty nor impossible.
    snapshot_sightings = sqlite_scalar(snapshot, "SELECT COUNT(*) FROM sightings")
    assert 0 < snapshot_sightings <= total_written

    # 3. The sighting set is consistent: no sighting without its aircraft, and
    #    no half-written pair. A torn snapshot would break exactly here.
    assert sqlite_rows(snapshot, "PRAGMA foreign_key_check") == []
    assert (
        sqlite_scalar(
            snapshot,
            "SELECT COUNT(*) FROM sightings s "
            "LEFT JOIN aircraft a ON a.id = s.aircraft_id WHERE a.id IS NULL",
        )
        == 0
    )
    assert sqlite_scalar(snapshot, "SELECT COUNT(*) FROM aircraft") == snapshot_sightings

    # 4. The archive carries no WAL sidecar: VACUUM INTO materializes everything.
    assert set(read_members(result.path)) == {"manifest.json", DATABASE_MEMBER}


async def test_a_live_backup_restores_into_a_working_installation(
    data_dir: Path, tmp_path: Path
) -> None:
    database = Database(database_path(data_dir))
    stop = asyncio.Event()
    try:
        await database.upgrade_to("head")
        writer = asyncio.create_task(_write_until(database, stop, start=500))
        await asyncio.sleep(0.05)
        result = await asyncio.to_thread(create_backup, data_dir, now=fixed_clock())
        stop.set()
        await writer
    finally:
        stop.set()
        await database.dispose()

    target = tmp_path / "restored-data"
    restore_backup(result.path, target, confirm=True, now=fixed_clock())

    restored = Database(database_path(target))
    try:
        assert await restored.quick_check() == ["ok"]
        assert await restored.current_revision() is not None
    finally:
        await restored.dispose()
