"""Measuring a real database: pages, freelist, and the two files on disk."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete

from flightsite.db import Database, MetaRepository
from flightsite.db.models import Meta
from flightsite.maintenance.stats import _size_of, gather_stats, wal_path


async def test_a_migrated_database_reports_pages_and_no_dead_space(database: Database) -> None:
    stats = await gather_stats(database)

    assert stats.page_count > 0
    assert stats.page_size == 4096
    assert stats.freelist_count == 0
    assert stats.reclaimable_ratio == 0.0
    assert stats.db_bytes == stats.page_count * stats.page_size
    assert stats.free_bytes > 0


async def test_deleting_rows_produces_reclaimable_pages(database: Database) -> None:
    """The signal the ``VACUUM`` guard reads: pages freed but not handed back."""
    meta = MetaRepository(database)
    for index in range(600):
        await meta.set(f"filler-{index:04d}", "x" * 400)
    grown = await gather_stats(database)

    async with database.writer_session() as session:
        await session.execute(delete(Meta).where(Meta.key.like("filler-%")))
    emptied = await gather_stats(database)

    assert grown.freelist_count == 0
    assert emptied.freelist_count > 0
    assert emptied.reclaimable_bytes == emptied.freelist_count * emptied.page_size
    # The file has not shrunk: that is precisely what a ``VACUUM`` would fix.
    assert emptied.page_count == grown.page_count


async def test_the_wal_sidecar_is_measured_separately(database: Database) -> None:
    meta = MetaRepository(database)
    await meta.set("some-key", "value")

    stats = await gather_stats(database)

    assert wal_path(database.path).name == f"{database.path.name}-wal"
    assert stats.wal_bytes > 0
    assert stats.file_bytes > 0


def test_a_file_that_is_not_there_measures_as_zero(tmp_path: Path) -> None:
    """The guard under the two file measurements, tested where it is decided.

    A cleanly closed database has no ``-wal`` at all, and a process whose
    migration never ran may have no database file either. Neither is a reason
    to fail a measurement — least of all on the cycle whose diagnostics are
    supposed to explain the failure.
    """
    assert _size_of(tmp_path / "no-such-file") == 0
    assert _size_of(tmp_path / "nested" / "no-such-file") == 0


async def test_an_absent_wal_measures_as_zero_rather_than_failing(db_path: Path) -> None:
    """An unmigrated database has no ``-wal`` yet; measuring it must not raise.

    The first maintenance cycle of a process that failed its migration would
    otherwise die on a missing sidecar, taking the diagnostics that explain the
    failure with it.
    """
    database = Database(db_path)
    try:
        stats = await gather_stats(database)
    finally:
        await database.dispose()

    assert wal_path(db_path).exists() is False
    assert stats.wal_bytes == 0
    assert stats.freelist_count == 0
    assert stats.reclaimable_ratio == 0.0
