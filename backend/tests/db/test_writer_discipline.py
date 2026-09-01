"""Single-writer discipline (ADR-0001, ADR-0008).

The rule is "exactly one writer at a time, enforced by construction". These
tests check the three ways :class:`~flightsite.db.Database` enforces it:
serialization of overlapping writers, transaction semantics on the writer
session, and read sessions that cannot write at all.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select, text

from flightsite.db import Database, Meta
from flightsite.db.clock import utc_now_ms


async def _count_rows(database: Database) -> int:
    async with database.read_session() as session:
        return await session.scalar(select(func.count()).select_from(Meta)) or 0


async def test_overlapping_writers_are_serialized_not_interleaved(
    migrated_database: Database,
) -> None:
    """Two concurrent writers run one after the other, never inside each other."""
    events: list[str] = []

    async def writer(name: str) -> None:
        async with migrated_database.writer_session() as session:
            events.append(f"enter:{name}")
            # Yield control: without the writer lock the other task would slip
            # in here and the event log would interleave.
            await asyncio.sleep(0)
            session.add(Meta(key=name, value=name, updated_ms=utc_now_ms()))
            events.append(f"exit:{name}")

    await asyncio.gather(writer("a"), writer("b"))

    first, second = (events[0], events[1]), (events[2], events[3])
    assert first[0].startswith("enter:") and first[1] == first[0].replace("enter", "exit")
    assert second[0].startswith("enter:") and second[1] == second[0].replace("enter", "exit")
    assert await _count_rows(migrated_database) == 2


async def test_writer_session_commits_on_clean_exit(migrated_database: Database) -> None:
    async with migrated_database.writer_session() as session:
        session.add(Meta(key="committed", value="yes", updated_ms=utc_now_ms()))

    async with migrated_database.read_session() as session:
        assert await session.scalar(select(Meta.value).where(Meta.key == "committed")) == "yes"


async def test_writer_session_rolls_back_on_exception(migrated_database: Database) -> None:
    """A failed batch must leave no partial rows behind."""
    with pytest.raises(RuntimeError, match="boom"):
        async with migrated_database.writer_session() as session:
            session.add(Meta(key="doomed", value="no", updated_ms=utc_now_ms()))
            await session.flush()
            raise RuntimeError("boom")

    assert await _count_rows(migrated_database) == 0


async def test_writer_lock_is_released_after_a_failed_write(migrated_database: Database) -> None:
    """A raising writer must not strand the lock and wedge all future writes."""
    with pytest.raises(RuntimeError):
        async with migrated_database.writer_session():
            raise RuntimeError("boom")

    async with asyncio.timeout(5):
        async with migrated_database.writer_session() as session:
            session.add(Meta(key="after", value="ok", updated_ms=utc_now_ms()))

    assert await _count_rows(migrated_database) == 1


async def test_reads_proceed_while_a_write_transaction_is_open(
    migrated_database: Database,
) -> None:
    """WAL's whole point: a reader is not blocked by an in-flight writer."""
    async with migrated_database.writer_session() as writer:
        writer.add(Meta(key="in-flight", value="x", updated_ms=utc_now_ms()))
        await writer.flush()

        async with asyncio.timeout(5):
            async with migrated_database.read_session() as reader:
                assert (await reader.execute(text("SELECT 1"))).scalar() == 1
                # The uncommitted row is invisible to the reader's snapshot.
                assert await reader.scalar(select(func.count()).select_from(Meta)) == 0

    assert await _count_rows(migrated_database) == 1


async def test_read_and_writer_sessions_use_separate_connections(
    migrated_database: Database,
) -> None:
    async with (
        migrated_database.writer_session() as writer,
        migrated_database.read_session() as reader,
    ):
        writer_connection = await writer.connection()
        reader_connection = await reader.connection()
        assert writer_connection is not reader_connection
