"""The zone a rollup row is keyed under, and the repair when it changes.

The defect these tests exist for is issue #205 / findings R1-02 and R3-01: the
writer captured ``settings.timezone`` at construction while the read path
resolved it per request, so on every fresh install — where the setup wizard
writes the timezone a minute *after* the backend boots — the rollups were
keyed under ``UTC`` and every "today" read asked for a receiver-local day that
had never been written.

The instants here are the ones the review reproduced: 01:47 UTC on
2026-09-21, which in ``America/New_York`` is 21:47 on 2026-09-20. A writer in
the wrong zone and a reader in the right one disagree by a whole day at that
moment, so a test that passes at this instant cannot be passing by accident.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from flightsite.analytics.bucketing import Preset, day_bounds_ms, local_day, resolve_window
from flightsite.analytics.queries import AnalyticsQueries
from flightsite.analytics.repository import (
    META_KEY_ROLLUP_THROUGH_DAY,
    META_KEY_ROLLUP_ZONE,
    AnalyticsRepository,
)
from flightsite.analytics.service import AnalyticsService
from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.db.meta import MetaRepository
from flightsite.db.models import DailyStats

from ..api.aircraft_history_fixtures import SeedAircraft
from ..api.sighting_fixtures import SeedSighting
from .conftest import NEW_YORK, ManualClock, seed_world

#: The evening the review caught: 21:47 local on 2026-09-20 in New York, which
#: is already 2026-09-21 in UTC.
LOCAL_DAY = "2026-09-20"
UTC_DAY = "2026-09-21"
LOCAL_HOUR_MS = 21 * 3_600_000 + 47 * 60_000

#: Long enough that no background flush fires: every pass is one a test asked
#: for.
NEVER_S = 3_600.0


class ZoneProbe:
    """A receiver timezone the test changes under a running service.

    This is exactly what ``flightsite.app._receiver_timezone`` hands the
    service — a callable over live settings — so what these tests exercise is
    the production wiring rather than a shape invented for them.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self) -> str:
        return self.name


@pytest.fixture
def new_york() -> ZoneInfo:
    return ZoneInfo(NEW_YORK)


@pytest.fixture
def evening_ms(new_york: ZoneInfo) -> int:
    """21:47 local on the review's day — 01:47 UTC the following date."""
    return day_bounds_ms(LOCAL_DAY, new_york)[0] + LOCAL_HOUR_MS


def build_service(database: Database, clock: ManualClock, probe: ZoneProbe) -> AnalyticsService:
    return AnalyticsService(
        database=database,
        persistence=None,
        timezone=probe,
        flush_interval_s=NEVER_S,
        clock=clock,
        counters=CounterRegistry(),
    )


async def seed_evening(database: Database, zone: ZoneInfo, evening_ms: int) -> None:
    """One airframe, three sightings, all in the local evening (issue #205)."""
    await seed_world(
        database,
        zone=zone,
        aircraft=[
            SeedAircraft(
                icao24="a0beef",
                first_seen_ms=evening_ms,
                last_seen_ms=evening_ms + 600_000,
                sighting_count=3,
                max_range_nm=225.6,
            )
        ],
        sightings=[
            SeedSighting(
                icao24="a0beef",
                started_ms=evening_ms + offset,
                ended_ms=evening_ms + offset + 60_000,
                max_range_nm=225.6,
            )
            for offset in (0, 120_000, 240_000)
        ],
    )


async def stored_days(repository: AnalyticsRepository) -> set[str]:
    return await repository.stored_days()


# ------------------------------------------------- the wizard-after-boot case


async def test_a_timezone_written_after_boot_keys_the_rollup_on_the_local_day(
    database: Database,
    repository: AnalyticsRepository,
    clock: ManualClock,
    new_york: ZoneInfo,
    evening_ms: int,
) -> None:
    """The install the review found: boot in UTC, wizard writes the real zone.

    Before the fix the service kept ``UTC`` for the life of the process, so
    the row landed on 2026-09-21 while ``/analytics/daily?preset=today`` asked
    for 2026-09-20 and read nothing.
    """
    clock.now_ms = evening_ms
    await seed_evening(database, new_york, evening_ms)
    probe = ZoneProbe("UTC")
    service = build_service(database, clock, probe)

    await service.start()
    try:
        service.mark_dirty(local_day(clock.now_ms, ZoneInfo("UTC")))
        await service.flush()
        assert UTC_DAY in await stored_days(repository)

        probe.name = NEW_YORK
        await service.flush()
    finally:
        await service.stop()

    days = await stored_days(repository)
    assert LOCAL_DAY in days
    assert UTC_DAY not in days
    row = await repository.day(LOCAL_DAY)
    assert row is not None
    assert row.sightings == 3


async def test_the_read_path_finds_what_the_writer_wrote_after_a_change(
    database: Database,
    clock: ManualClock,
    new_york: ZoneInfo,
    evening_ms: int,
) -> None:
    """The two halves of R3-01 meet: today's window reads today's rollup."""
    clock.now_ms = evening_ms
    await seed_evening(database, new_york, evening_ms)
    probe = ZoneProbe("UTC")
    service = build_service(database, clock, probe)

    await service.start()
    try:
        await service.flush()
        probe.name = NEW_YORK
        await service.flush()
    finally:
        await service.stop()

    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    window = resolve_window(Preset.TODAY, now_ms=clock.now_ms, zone=new_york)
    summary = await queries.summary(window)
    assert window.first_day == LOCAL_DAY
    assert summary.sightings == 3
    assert summary.max_range_nm == pytest.approx(225.6)


# ------------------------------------------------------------- the repair


async def test_the_repair_deletes_the_rows_keyed_under_the_old_zone(
    database: Database,
    repository: AnalyticsRepository,
    clock: ManualClock,
    new_york: ZoneInfo,
    evening_ms: int,
) -> None:
    """An orphan a rebuild would never visit — a day *after* today — is dropped.

    A receiver behind UTC accumulates exactly this: the evening's traffic
    filed under tomorrow's date, on a day no later rebuild reaches because it
    is outside the receiver's own history.
    """
    clock.now_ms = evening_ms
    await seed_evening(database, new_york, evening_ms)
    async with database.writer_session() as session:
        session.add(DailyStats(day=UTC_DAY, unique_aircraft=1, sightings=3))

    service = build_service(database, clock, ZoneProbe(NEW_YORK))
    await service.start()
    await service.stop()

    days = await stored_days(repository)
    assert UTC_DAY not in days
    assert LOCAL_DAY in days


async def test_the_repair_is_idempotent_across_boots(
    database: Database,
    repository: AnalyticsRepository,
    clock: ManualClock,
    new_york: ZoneInfo,
    evening_ms: int,
) -> None:
    """A second boot in the same zone re-keys nothing and rewrites the same rows."""
    clock.now_ms = evening_ms
    await seed_evening(database, new_york, evening_ms)
    probe = ZoneProbe(NEW_YORK)

    first = build_service(database, clock, probe)
    await first.start()
    await first.stop()
    after_first = await stored_days(repository)
    row_first = await repository.day(LOCAL_DAY)

    second = build_service(database, clock, probe)
    await second.start()
    await second.stop()

    assert second.startup_repair.rekeyed is False
    assert second.startup_repair.removed_days == 0
    assert await stored_days(repository) == after_first
    assert await repository.day(LOCAL_DAY) == row_first


async def test_a_zone_change_drops_the_watermark_so_history_is_rebuilt(
    database: Database,
    clock: ManualClock,
    new_york: ZoneInfo,
    evening_ms: int,
) -> None:
    """The marker is claimed before the rebuild, and the watermark carries it.

    Recording the zone up front is what makes an interrupted repair resumable
    rather than endlessly restarted: the watermark is the resumption state.
    """
    clock.now_ms = evening_ms
    await seed_evening(database, new_york, evening_ms)
    meta = MetaRepository(database)
    await meta.set(META_KEY_ROLLUP_ZONE, "UTC")
    await meta.set(META_KEY_ROLLUP_THROUGH_DAY, "2026-09-19")

    service = build_service(database, clock, ZoneProbe(NEW_YORK))
    await service.start()
    await service.stop()

    assert service.startup_repair.rekeyed is True
    assert await meta.get(META_KEY_ROLLUP_ZONE) == NEW_YORK
    assert LOCAL_DAY in service.startup_repair.days


async def test_an_install_upgrading_into_the_marker_rebuilds_once(
    database: Database,
    repository: AnalyticsRepository,
    clock: ManualClock,
    new_york: ZoneInfo,
    evening_ms: int,
) -> None:
    """No marker means "unknown zone": the owner's Pi, running since v0.3.x.

    Its rows may have been keyed under anything, so the first boot that knows
    to ask rebuilds them all — and the boot after that does not.
    """
    clock.now_ms = evening_ms
    await seed_evening(database, new_york, evening_ms)
    meta = MetaRepository(database)
    await meta.set(META_KEY_ROLLUP_THROUGH_DAY, "2026-09-19")
    async with database.writer_session() as session:
        session.add(DailyStats(day=UTC_DAY, unique_aircraft=9, sightings=9))

    service = build_service(database, clock, ZoneProbe(NEW_YORK))
    await service.start()
    await service.stop()

    assert service.startup_repair.rekeyed is True
    assert service.startup_repair.removed_days == 1
    assert UTC_DAY not in await stored_days(repository)
