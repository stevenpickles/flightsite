"""The zone a daily summary is keyed under, and the re-key when it changes.

Issue #205 / finding R3-01: this service captured ``settings.timezone`` at
construction, so a fresh install — whose setup wizard writes the timezone a
minute after the backend boots — kept the ``UTC`` default for the life of the
process while the scorecard's "Max range today" and the daily-totals charts
were read on the receiver-local day.

What a zone change can repair and what it cannot is stated in the service's
module docstring; these tests hold both halves to it.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.receiver_metrics.aggregate import local_day, local_day_start_ms
from flightsite.receiver_metrics.model import MetricSummary
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.service import ReceiverMetricsService
from tests.receiver_metrics.conftest import SimulatedTime, place

NEW_YORK = "America/New_York"

#: 21:00 local on 2026-09-20 in New York is 01:00 UTC on 2026-09-21 — the
#: split the review reproduced, where writer and reader disagree by a day.
LOCAL_DAY = "2026-09-20"
UTC_DAY = "2026-09-21"

SAMPLE_INTERVAL_S = 900.0


class ZoneProbe:
    """A receiver timezone the test changes under a running service.

    The shape ``flightsite.app._receiver_timezone`` hands the service, so
    these tests exercise the production wiring rather than one invented here.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self) -> str:
        return self.name


@pytest.fixture
def new_york() -> ZoneInfo:
    return ZoneInfo(NEW_YORK)


@pytest.fixture
def evening(new_york: ZoneInfo) -> SimulatedTime:
    """One interval before 21:00 local on the review's evening."""
    return SimulatedTime(
        base_ms=local_day_start_ms(LOCAL_DAY, new_york) + 21 * 3_600_000 - int(SAMPLE_INTERVAL_S)
    )


def build(
    database: Database, live: LiveStore, clock: SimulatedTime, probe: ZoneProbe
) -> ReceiverMetricsService:
    """An unstarted service whose zone the test can change under it."""
    return ReceiverMetricsService(
        database=database,
        live=live,
        timezone=probe,
        sample_interval_s=SAMPLE_INTERVAL_S,
        flush_interval_s=SAMPLE_INTERVAL_S,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )


async def sample_evening(
    service: ReceiverMetricsService, live: LiveStore, clock: SimulatedTime, *, ticks: int = 4
) -> None:
    """Fill an hour of the local evening with positioned traffic."""
    for index in range(ticks):
        clock.advance(SAMPLE_INTERVAL_S)
        place(live, clock, icao=f"a0000{index}", bearing_deg=148.0, distance_nm=200.0 + index)
        await service.sample_once()
    await service.flush()


async def test_a_timezone_written_after_boot_keys_the_day_locally(
    database: Database,
    live: LiveStore,
    repository: MetricsRepository,
    new_york: ZoneInfo,
    evening: SimulatedTime,
) -> None:
    """The wizard-after-boot install: the daily summary moves to the local day."""
    probe = ZoneProbe("UTC")
    service = build(database, live, evening, probe)

    await sample_evening(service, live, evening)
    await service.run_maintenance()
    assert UTC_DAY in await repository.daily_all()

    probe.name = NEW_YORK
    await service.run_maintenance()

    stored = await repository.daily_all()
    assert LOCAL_DAY in stored
    assert UTC_DAY not in stored
    assert stored[LOCAL_DAY].sample_count == 4


async def test_the_scorecards_today_ranges_follow_the_live_zone(
    database: Database,
    live: LiveStore,
    repository: MetricsRepository,
    new_york: ZoneInfo,
    evening: SimulatedTime,
) -> None:
    """ "Max range today" is read on the local day, so it must be written there.

    The range tier has no source table to rebuild from, so what this asserts
    is the half that matters: after the change, new samples are filed on the
    day the scorecard asks for.
    """
    probe = ZoneProbe("UTC")
    service = build(database, live, evening, probe)
    await sample_evening(service, live, evening, ticks=1)

    probe.name = NEW_YORK
    await sample_evening(service, live, evening, ticks=1)

    today = local_day(evening.epoch_ms(), new_york)
    assert today == LOCAL_DAY
    ranges = await repository.ranges_for_day(today)
    assert ranges
    assert max(record.max_range_nm for record in ranges.values()) >= 200.0


async def test_a_second_pass_in_the_same_zone_rekeys_nothing(
    database: Database,
    live: LiveStore,
    repository: MetricsRepository,
    new_york: ZoneInfo,
    evening: SimulatedTime,
) -> None:
    """Idempotence: the repair happens once, and the pass after it is ordinary."""
    service = build(database, live, evening, ZoneProbe(NEW_YORK))
    await sample_evening(service, live, evening)
    await service.run_maintenance()
    first = await repository.daily_all()

    await service.run_maintenance()

    assert await repository.daily_all() == first


async def test_summaries_older_than_the_raw_window_are_left_alone(
    database: Database,
    live: LiveStore,
    repository: MetricsRepository,
    new_york: ZoneInfo,
    evening: SimulatedTime,
) -> None:
    """A day no raw sample survives for cannot be re-derived, so it is kept.

    Deleting it would be data loss dressed as a repair — see the service's
    module docstring for why this is the honest answer rather than a gap.
    """
    ancient = "2020-01-01"
    await repository.write_summaries(
        {}, {ancient: MetricSummary(sample_count=96, messages_total=1_000)}, at_ms=evening.base_ms
    )

    probe = ZoneProbe("UTC")
    service = build(database, live, evening, probe)
    await sample_evening(service, live, evening)
    await service.run_maintenance()

    probe.name = NEW_YORK
    await service.run_maintenance()

    stored = await repository.daily_all()
    assert ancient in stored
    assert stored[ancient].sample_count == 96
