"""The ``meta`` key/value store and T0's write-once guarantee (SPEC §16)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select

from flightsite.db import META_KEY_T0, Database, Meta, MetaError, MetaRepository
from flightsite.db.clock import MS_PER_SECOND, from_epoch_ms, to_epoch_ms, utc_now_ms

T0_MS = 1_756_600_000_000
LATER_MS = T0_MS + 60_000


async def test_fresh_database_has_no_t0(meta: MetaRepository) -> None:
    """A fresh install records nothing until the first observation (slice 009)."""
    assert await meta.get_t0() is None
    assert await meta.get(META_KEY_T0) is None


async def test_set_t0_once_writes_when_absent(meta: MetaRepository) -> None:
    assert await meta.set_t0_once(T0_MS) is True
    assert await meta.get_t0() == T0_MS


async def test_set_t0_once_never_overwrites(meta: MetaRepository) -> None:
    """The second call reports that it did not write, and T0 is unchanged."""
    assert await meta.set_t0_once(T0_MS) is True
    assert await meta.set_t0_once(LATER_MS) is False
    assert await meta.get_t0() == T0_MS


async def test_concurrent_set_t0_once_produces_exactly_one_winner(meta: MetaRepository) -> None:
    """Absence check and insert are one statement, so there is no race window."""
    results = await asyncio.gather(*(meta.set_t0_once(T0_MS + offset) for offset in range(8)))

    assert results.count(True) == 1
    stored = await meta.get_t0()
    assert stored is not None
    assert T0_MS <= stored < T0_MS + 8


@pytest.mark.parametrize("value", [0, -1, -T0_MS])
async def test_set_t0_once_rejects_non_positive_timestamps(
    meta: MetaRepository, value: int
) -> None:
    with pytest.raises(ValueError, match="positive epoch-ms"):
        await meta.set_t0_once(value)
    assert await meta.get_t0() is None


async def test_get_t0_surfaces_a_corrupt_value(meta: MetaRepository) -> None:
    """A non-integer T0 is a data-integrity problem, not a missing value."""
    await meta.set(META_KEY_T0, "not-a-timestamp")

    with pytest.raises(MetaError, match=META_KEY_T0):
        await meta.get_t0()


async def test_set_overwrites_and_stamps_updated_ms(meta: MetaRepository) -> None:
    before = utc_now_ms()
    await meta.set("install_id", "first")
    await meta.set("install_id", "second")

    assert await meta.get("install_id") == "second"
    async with meta.database.read_session() as session:
        updated_ms = await session.scalar(select(Meta.updated_ms).where(Meta.key == "install_id"))
    assert updated_ms is not None
    assert updated_ms >= before


async def test_set_if_absent_reports_whether_it_wrote(meta: MetaRepository) -> None:
    assert await meta.set_if_absent("install_id", "abc") is True
    assert await meta.set_if_absent("install_id", "xyz") is False
    assert await meta.get("install_id") == "abc"


async def test_delete_reports_whether_a_row_was_removed(meta: MetaRepository) -> None:
    await meta.set("scratch", "value")

    assert await meta.delete("scratch") is True
    assert await meta.delete("scratch") is False
    assert await meta.get("scratch") is None


async def test_meta_reads_do_not_queue_behind_an_in_flight_write(
    migrated_database: Database,
) -> None:
    meta = MetaRepository(migrated_database)

    async with migrated_database.writer_session(), asyncio.timeout(5):
        assert await meta.get("anything") is None


def test_epoch_ms_round_trip() -> None:
    moment = from_epoch_ms(T0_MS)
    offset = moment.utcoffset()

    assert to_epoch_ms(moment) == T0_MS
    assert offset is not None
    assert offset.total_seconds() == 0


def test_to_epoch_ms_refuses_naive_datetimes() -> None:
    """A naive datetime would silently adopt the host's zone."""
    with pytest.raises(ValueError, match="timezone-aware"):
        to_epoch_ms(datetime(2026, 8, 31, 12, 0, 0))


def test_utc_now_ms_is_milliseconds_not_seconds() -> None:
    """Guards the unit: an epoch in seconds would be ~1000x smaller."""
    assert utc_now_ms() > 1_700_000_000 * MS_PER_SECOND
