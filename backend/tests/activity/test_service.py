"""The service: exactly-once across restarts, replays, and a flapping decoder.

This is where the roadmap's acceptance criteria are actually drilled:

* *"fixture scenarios emit exactly the expected events (no duplicates on
  restart/replay)"* — a scenario is seeded, a pass records what it justifies,
  and then the service is **destroyed and rebuilt** against the same database,
  which is what a process restart is. Some drills go further and reset the
  watermark to zero first, which is a full replay of history through the
  producers with nothing remembered at all.
* *"milestones fire once, persist, and appear in the feed"* — the same drill,
  asserted against ``milestones`` and against the feed.

Nothing here waits on time passing. :meth:`ActivityService.flush` is driven
directly against a hand-driven clock, so a minute of debounce and a fortnight
of catch-up cost microseconds (``docs/TEST_STRATEGY.md`` §3); the one test
about the background task's *cadence* injects a sleeper that returns
immediately, so even that asserts about the interval rather than about how long
a second is.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from flightsite.activity import (
    MILESTONE_FIRST_MILITARY,
    SCAN_WATERMARK_KEY,
    ActivityService,
    StoredActivityEvent,
)
from flightsite.activity.repository import ActivityRepository
from flightsite.counters import counters
from flightsite.db import Database, MetaRepository
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.ingest.health import HealthState
from flightsite.metadata.importer import ImportRun, SourceImportResult
from flightsite.metadata.registry import ImportPhase
from flightsite.receiver_metrics.model import (
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
)
from flightsite.sightings.worker import SightingLifecycle, SightingRef

from .conftest import (
    BASE_MS,
    MS_PER_MINUTE,
    FakeHealth,
    ManualClock,
    airframe,
    close_sighting,
    seed,
    service_for,
    set_lifetime,
    sighting,
)

MS_PER_HOUR = 60 * MS_PER_MINUTE

#: Long enough that a parked task never wakes during a test.
NEVER_S = 3_600.0


async def feed_types(repository: ActivityRepository) -> list[str]:
    """Every recorded event's type, newest first."""
    return [event.type for event in await repository.list_events(limit=100)]


async def feed_keys(database: Database) -> list[str]:
    """Every recorded event's dedupe key — the identity duplicates would repeat."""
    from sqlalchemy import select

    from flightsite.db import ActivityEvent

    async with database.read_session() as session:
        return sorted(key for key in await session.scalars(select(ActivityEvent.dedupe_key)) if key)


async def started(database: Database, clock: ManualClock, **kwargs: Any) -> ActivityService:
    """A service constructed and started against ``database``.

    Started rather than merely constructed, because :meth:`start` is where the
    watermark is initialized and the record baselines are seeded — the two
    pieces of state every "what does a restart do" assertion turns on.
    """
    service = service_for(database, clock=clock, **kwargs)
    await service.start()
    return service


# --------------------------------------------------- the fixture scenario


async def test_a_fixture_scenario_emits_exactly_the_events_it_justifies(
    database: Database, clock: ManualClock
) -> None:
    """Three airframes, one of a brand-new type, one military, one ordinary.

    Asserted as the *whole* set of dedupe keys rather than as a membership
    check: what this criterion is about is the event nobody expected, and a
    membership assertion is exactly the one that cannot see it.
    """
    await seed(
        database,
        [
            airframe("ae1463", first_seen_ms=BASE_MS, type_code="B738"),
            airframe("43c6db", first_seen_ms=BASE_MS + 1, type_code="A400", military=True),
            airframe("a9c2f0", first_seen_ms=BASE_MS + 2, type_code="B738"),
        ],
        [
            sighting("ae1463", started_ms=BASE_MS),
            sighting("43c6db", started_ms=BASE_MS + 1),
            sighting("a9c2f0", started_ms=BASE_MS + 2),
        ],
    )
    # Watermark at zero: this is the "the feed has never run" case, so every
    # seeded sighting is examined.
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)

    await service.flush()

    assert await feed_keys(database) == [
        "first_ever_aircraft:43c6db",
        "first_ever_aircraft:a9c2f0",
        "first_ever_aircraft:ae1463",
        "milestone:first_military",
        "new_type:A400",
        "new_type:B738",
    ]


async def test_a_second_pass_over_the_same_scenario_records_nothing(
    database: Database, clock: ManualClock
) -> None:
    """The watermark has moved on, so the pass has nothing left to look at."""
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)
    await service.flush()

    result = await service.flush()

    assert result.recorded == 0
    assert await feed_types(service.repository) == ["first_ever_aircraft"]


# ------------------------------------------------------------- restart drills


async def test_a_restart_that_re_examines_everything_records_no_duplicates(
    database: Database, clock: ManualClock
) -> None:
    """The criterion, drilled at its worst case: a full replay with nothing remembered.

    The service is destroyed, the watermark is reset to zero, and a fresh one
    re-derives every conclusion from ground truth. Every dedupe key it computes
    is the one already stored, so the whole replay writes nothing — which is
    what makes the watermark an optimisation for *how much* is re-examined
    rather than a correctness dependency.
    """
    await seed(
        database,
        [airframe("ae1463", type_code="B738"), airframe("43c6db", type_code="A400", military=True)],
        [sighting("ae1463"), sighting("43c6db", started_ms=BASE_MS + 1)],
    )
    meta = MetaRepository(database)
    await meta.set(SCAN_WATERMARK_KEY, "0")
    first = await started(database, clock)
    await first.flush()
    before = await feed_keys(database)
    await first.stop()

    await meta.set(SCAN_WATERMARK_KEY, "0")
    replayed = await started(database, clock)
    result = await replayed.flush()

    assert result.recorded == 0
    assert await feed_keys(database) == before


async def test_an_ordinary_restart_picks_up_where_it_left_off(
    database: Database, clock: ManualClock
) -> None:
    """A restart re-reads the watermark, so a sighting written while it was down lands."""
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    first = await started(database, clock)
    await first.flush()
    await first.stop()

    # Something is heard while the process is down.
    await seed(
        database,
        [airframe("a9c2f0", first_seen_ms=BASE_MS + MS_PER_HOUR)],
        [sighting("a9c2f0", started_ms=BASE_MS + MS_PER_HOUR)],
    )
    second = await started(database, clock)
    await second.flush()

    assert await feed_keys(database) == [
        "first_ever_aircraft:a9c2f0",
        "first_ever_aircraft:ae1463",
    ]


async def test_a_first_boot_on_an_install_with_history_narrates_none_of_it(
    database: Database, clock: ManualClock
) -> None:
    """An upgrade into slice 035 must not fill the feed with a year of history.

    The watermark is initialized to the *present*, so what already happened
    before the feed existed stays where it is: in ``sightings``.
    """
    ids = await seed(
        database,
        [airframe(f"aa00{index:02d}", first_seen_ms=BASE_MS + index) for index in range(5)],
        [sighting(f"aa00{index:02d}", started_ms=BASE_MS + index) for index in range(5)],
    )
    service = await started(database, clock)

    await service.flush()

    assert service.watermark == ids[-1]
    assert await feed_keys(database) == []


async def test_a_watermark_that_cannot_be_read_is_re_initialized_rather_than_fatal(
    database: Database, clock: ManualClock
) -> None:
    """A corrupt key must not stop the feed; re-seeding it costs history, not correctness."""
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "not a number")

    service = await started(database, clock)

    assert service.watermark == 1


async def test_the_watermark_is_persisted_so_a_restart_does_not_rescan(
    database: Database, clock: ManualClock
) -> None:
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)

    await service.flush()

    assert await MetaRepository(database).get(SCAN_WATERMARK_KEY) == "1"


async def test_a_long_catch_up_arrives_over_several_passes(
    database: Database, clock: ManualClock
) -> None:
    """A service stopped for a week comes back to thousands of rows.

    Walking them a few at a time keeps each pass's transaction short and lets
    the writer lock go between them, which is what stops a catch-up from
    stalling sighting persistence.
    """
    await seed(
        database,
        [airframe(f"aa00{index:02d}", first_seen_ms=BASE_MS + index) for index in range(5)],
        [sighting(f"aa00{index:02d}", started_ms=BASE_MS + index) for index in range(5)],
    )
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock, scan_limit=2)

    assert (await service.flush()).recorded == 2
    assert (await service.flush()).recorded == 2
    assert (await service.flush()).recorded == 1
    assert (await service.flush()).recorded == 0


# ---------------------------------------------------------------- milestones


async def test_a_milestone_fires_once_persists_and_appears_in_the_feed(
    database: Database, clock: ManualClock
) -> None:
    """The roadmap's second criterion, in one assertion each."""
    await seed(
        database,
        [airframe("43c6db", military=True, type_code="A400")],
        [sighting("43c6db")],
    )
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)

    await service.flush()

    assert await service.repository.milestone_keys() == frozenset(
        {MILESTONE_FIRST_MILITARY, "first_type_A400"}
    )
    assert "milestone" in await feed_types(service.repository)


async def test_a_milestone_does_not_fire_again_after_a_restart(
    database: Database, clock: ManualClock
) -> None:
    """A second military aircraft, a new process, and still one first-military.

    The milestone's primary key is what makes this true, and the service's
    start reads the claimed keys so it does not even ask the question again.
    """
    await seed(
        database,
        [airframe("43c6db", military=True)],
        [sighting("43c6db")],
    )
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    first = await started(database, clock)
    await first.flush()
    await first.stop()

    await seed(
        database,
        [airframe("43c6dc", first_seen_ms=BASE_MS + MS_PER_HOUR, military=True)],
        [sighting("43c6dc", started_ms=BASE_MS + MS_PER_HOUR)],
    )
    second = await started(database, clock)
    assert MILESTONE_FIRST_MILITARY in second.milestones
    await second.flush()

    keys = await feed_keys(database)
    assert keys.count("milestone:first_military") == 1


async def test_the_thousandth_airframe_is_a_milestone_and_the_999th_is_not(
    database: Database, clock: ManualClock
) -> None:
    """SPEC §54's round number, drilled against a real rank query.

    A hundred airframes are seeded and the milestone thresholds are asserted
    against the smallest of them, so the drill exercises the same rank query a
    thousand-airframe install would without seeding a thousand rows.
    """
    await seed(
        database,
        [airframe(f"a{index:05x}", first_seen_ms=BASE_MS + index) for index in range(100)],
        [sighting(f"a{index:05x}", started_ms=BASE_MS + index) for index in range(100)],
    )
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)

    await service.flush()

    assert await service.repository.milestone_keys() == frozenset({"unique_aircraft_100"})


# ------------------------------------------------------------ rolling records


async def test_standing_records_are_seeded_at_start_and_announced_to_nobody(
    database: Database, clock: ManualClock
) -> None:
    """An install upgrading into this slice already had records; they are not news."""
    await set_lifetime(
        database,
        {
            LIFETIME_MAX_RANGE_NM: 241.5,
            LIFETIME_MAX_RANGE_AT_MS: float(BASE_MS),
            LIFETIME_MAX_SIMULTANEOUS: 87.0,
        },
    )
    service = await started(database, clock)

    await service.flush()

    assert await feed_keys(database) == []


async def test_a_record_beaten_while_the_service_runs_is_announced_once(
    database: Database, clock: ManualClock
) -> None:
    await set_lifetime(database, {LIFETIME_MAX_RANGE_NM: 180.0})
    service = await started(database, clock)
    await service.flush()

    await set_lifetime(
        database, {LIFETIME_MAX_RANGE_NM: 241.5, LIFETIME_MAX_RANGE_AT_MS: float(BASE_MS)}
    )
    await service.flush()
    await service.flush()

    assert await feed_keys(database) == ["range_record:241.500"]


async def test_the_longest_sighting_record_is_seeded_and_then_beaten(
    database: Database, clock: ManualClock
) -> None:
    """Seeded by one scan at boot; beaten by a close the seam reports.

    The seeded record is adopted silently — it was already the record before
    this process existed — and the sighting that beats it is announced.
    """
    await seed(database, [airframe("ae1463")], [sighting("ae1463", duration_ms=600_000)])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "1")
    service = await started(database, clock)
    await service.flush()
    assert await feed_keys(database) == []

    ids = await seed(
        database,
        [airframe("a9c2f0", first_seen_ms=BASE_MS + MS_PER_HOUR)],
        [sighting("a9c2f0", started_ms=BASE_MS + MS_PER_HOUR, duration_ms=1_800_000)],
    )
    await service.flush()

    assert f"receiver_record:longest_sighting:{ids[0]}" in await feed_keys(database)


async def test_a_busiest_day_record_names_the_day_and_the_count(
    database: Database, clock: ManualClock
) -> None:
    await set_lifetime(
        database, {LIFETIME_BUSIEST_DAY: "2026-05-01", LIFETIME_BUSIEST_DAY_COUNT: 90_000.0}
    )
    service = await started(database, clock)
    await service.flush()

    await set_lifetime(
        database, {LIFETIME_BUSIEST_DAY: "2026-06-02", LIFETIME_BUSIEST_DAY_COUNT: 120_000.0}
    )
    await service.flush()

    assert await feed_keys(database) == ["receiver_record:busiest_day:2026-06-02:120000"]


# ------------------------------------------------------------ decoder health


async def test_an_install_with_no_decoder_says_nothing_about_one(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    """A first run has no decoder configured. Silence is the honest answer."""
    service = await started(database, clock, health=health)

    await service.flush()
    clock.advance_s(600)
    await service.flush()

    assert await feed_keys(database) == []


async def test_the_state_at_boot_seeds_silently(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    """A decoder's state at boot predates the process, so it is not a transition."""
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health)

    await service.flush()

    assert await feed_keys(database) == []


async def test_a_sustained_outage_is_announced_once_and_stamped_when_it_began(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health, offline_debounce_s=60.0)
    await service.flush()

    clock.advance_s(10)
    outage_ms = clock.now_ms
    health.set(HealthState.DOWN, error="ConnectError")
    await service.flush()
    # Not yet: the state has to hold for the debounce window first.
    assert await feed_keys(database) == []

    clock.advance_s(61)
    await service.flush()
    await service.flush()

    assert await feed_keys(database) == [f"receiver_offline:{outage_ms}"]
    events = await service.repository.list_events(limit=1)
    assert events[0].ts_ms == outage_ms
    assert events[0].payload["error"] == "ConnectError"


async def test_a_flapping_decoder_produces_no_events_at_all(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    """The debounce's whole point: a decoder restarting on a timer is not news.

    Neither state ever holds for the window, so neither is ever announced —
    and the feed stays about aircraft rather than about a flaky cable.
    """
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health, offline_debounce_s=60.0)
    await service.flush()

    for index in range(20):
        health.set(HealthState.DOWN if index % 2 else HealthState.CONNECTED)
        clock.advance_s(10)
        await service.flush()

    assert await feed_keys(database) == []


async def test_a_degraded_decoder_is_not_an_outage(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    """``degraded`` is "failing, but not yet gone" — the state to stay quiet about.

    It is the first half of the debounce and it costs nothing: a run of failed
    polls that never reaches ``down`` leaves the announced state exactly where
    it was.
    """
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health, offline_debounce_s=60.0)
    await service.flush()

    health.set(HealthState.DEGRADED)
    for _ in range(10):
        clock.advance_s(60)
        await service.flush()

    assert await feed_keys(database) == []


async def test_a_restore_reports_how_long_the_receiver_was_gone(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    """The outage is measured between the two *transitions*, not between passes.

    An episode is stamped with when the state was first observed, not when the
    debounce expired, so the duration a restore reports is how long the decoder
    was actually away — the minute spent waiting to be sure included.
    """
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health, offline_debounce_s=60.0)
    await service.flush()

    health.set(HealthState.DOWN, error="ConnectError")
    clock.advance_s(10)
    went_down_ms = clock.now_ms
    await service.flush()
    clock.advance_s(61)
    await service.flush()

    health.set(HealthState.CONNECTED)
    clock.advance_s(300)
    came_back_ms = clock.now_ms
    await service.flush()
    clock.advance_s(61)
    await service.flush()

    assert await feed_types(service.repository) == ["receiver_restored", "receiver_offline"]
    restored = (await service.repository.list_events(limit=1))[0]
    assert restored.ts_ms == came_back_ms
    assert restored.payload["outage_s"] == (came_back_ms - went_down_ms) / 1000


async def test_a_decoder_that_disappears_from_configuration_stops_the_reporting(
    database: Database, clock: ManualClock, health: FakeHealth
) -> None:
    """``None`` is "no decoder", not "a decoder that is down"."""
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health, offline_debounce_s=60.0)
    await service.flush()

    health.detach()
    clock.advance_s(600)
    await service.flush()

    assert await feed_keys(database) == []


# ---------------------------------------------------------- metadata imports


def _run(*results: SourceImportResult) -> ImportRun:
    return ImportRun(results=results, started_ms=BASE_MS, finished_ms=BASE_MS + 1_000)


async def test_a_completed_import_run_becomes_one_event_per_source(
    database: Database, clock: ManualClock
) -> None:
    """SPEC §27: the user needs to see which sources worked, so each gets a row."""
    service = await started(database, clock)

    await service.record_import(
        _run(
            SourceImportResult(
                source="mictronics", ok=True, phase=ImportPhase.DONE, rows_imported=430_000
            ),
            SourceImportResult(
                source="airports", ok=False, phase=ImportPhase.DOWNLOAD, error="ConnectError"
            ),
        )
    )
    await service.flush()

    assert await feed_keys(database) == [
        f"metadata_updated:airports:{BASE_MS + 1_000}",
        f"metadata_updated:mictronics:{BASE_MS + 1_000}",
    ]


async def test_the_same_run_recorded_twice_is_one_set_of_events(
    database: Database, clock: ManualClock
) -> None:
    """The run's finish moment names it, so a retried notification is a no-op."""
    service = await started(database, clock)
    run = _run(SourceImportResult(source="faa", ok=True, phase=ImportPhase.DONE))

    await service.record_import(run)
    await service.flush()
    await service.record_import(run)
    await service.flush()

    assert await feed_keys(database) == [f"metadata_updated:faa:{BASE_MS + 1_000}"]


# ------------------------------------------------------------- the two seams


async def test_an_open_reported_by_the_seam_is_not_re_examined(
    database: Database, clock: ManualClock
) -> None:
    """Opens need no notification — the catch-up scan finds them by id.

    Taking them from the seam as well would make a lossy notification
    load-bearing for a fact that is already durable, and would mean a sighting
    the scan had already passed could be narrated a second time.
    """
    ids = await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    service = await started(database, clock)

    service.record_lifecycle(
        SightingLifecycle(
            at_ms=clock.now_ms,
            opened=(SightingRef("ae1463", 1, ids[0], BASE_MS, None),),
        )
    )
    await service.flush()

    assert await feed_keys(database) == []


async def test_a_close_reported_by_the_seam_is_examined(
    database: Database, clock: ManualClock
) -> None:
    """A sighting that opened before the watermark and ends now is only findable here.

    The scan walks ids and has already passed this row; the record it sets is
    news the feed would otherwise miss until the next boot's baseline quietly
    adopted it.
    """
    ids = await seed(
        database,
        [airframe("ae1463"), airframe("a9c2f0", first_seen_ms=BASE_MS + 1)],
        [sighting("ae1463", duration_ms=600_000), sighting("a9c2f0", started_ms=BASE_MS + 1)],
    )
    service = await started(database, clock)
    await service.flush()

    await close_sighting(database, ids[1], duration_ms=1_800_000)
    service.record_lifecycle(
        SightingLifecycle(
            at_ms=clock.now_ms,
            closed=(SightingRef("a9c2f0", 2, ids[1], BASE_MS + 1, BASE_MS + 1_800_001),),
        )
    )
    await service.flush()

    assert await feed_keys(database) == [f"receiver_record:longest_sighting:{ids[1]}"]


async def test_new_events_reach_the_subscriber_and_repeats_do_not(
    database: Database, clock: ManualClock
) -> None:
    """The seam the WebSocket's ``activity`` frame hangs off (``docs/API.md`` §4.4).

    Only rows that were genuinely created are published, so the socket inherits
    the table's exactly-once guarantee instead of needing one of its own.
    """
    published: list[StoredActivityEvent] = []
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)
    service.subscribe(published.extend)

    await service.flush()
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service._watermark = 0
    await service.flush()

    assert [event.type for event in published] == ["first_ever_aircraft"]


async def test_subscribing_the_same_listener_twice_subscribes_it_once(
    database: Database, clock: ManualClock
) -> None:
    """A broadcaster restarted against a running service must not double-publish."""
    published: list[StoredActivityEvent] = []
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)
    service.subscribe(published.extend)
    service.subscribe(published.extend)

    await service.flush()

    assert len(published) == 1


async def test_an_unsubscribed_listener_stops_hearing(
    database: Database, clock: ManualClock
) -> None:
    published: list[StoredActivityEvent] = []
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)
    service.subscribe(published.extend)
    service.unsubscribe(published.extend)
    service.unsubscribe(published.extend)

    await service.flush()

    assert published == []


# ------------------------------------------------------------- degradation


async def test_a_failed_pass_keeps_its_work_and_retries_it(
    database: Database, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every failure mode ends in the feed being later, and nowhere else.

    The pending work is restored, ``db_errors`` rises, and no baseline advances
    — so the next pass proposes exactly the same events rather than believing
    it already wrote them.
    """
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)

    async def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(ActivityRepository, "record", explode)
    failed = await service.flush()

    assert failed.failed is True
    assert counters.snapshot()[DB_ERRORS_COUNTER] == 1
    assert service.watermark == 0

    monkeypatch.undo()
    recovered = await service.flush()

    assert recovered.recorded == 1
    assert await feed_keys(database) == ["first_ever_aircraft:ae1463"]


async def test_a_failed_pass_does_not_lose_a_health_episode(
    database: Database, clock: ManualClock, health: FakeHealth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A debounced transition is observed once; losing it would lose the outage."""
    health.set(HealthState.CONNECTED)
    service = await started(database, clock, health=health, offline_debounce_s=60.0)
    await service.flush()

    health.set(HealthState.DOWN, error="ConnectError")
    clock.advance_s(10)
    await service.flush()
    clock.advance_s(61)

    async def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(ActivityRepository, "record", explode)
    await service.flush()
    monkeypatch.undo()
    await service.flush()

    assert await feed_types(service.repository) == ["receiver_offline"]


async def test_a_listener_that_raises_does_not_fail_the_pass(
    database: Database, clock: ManualClock
) -> None:
    """The transaction has already committed; an exception could only make it worse."""
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    service = await started(database, clock)

    def explode(_events: object) -> None:
        raise RuntimeError("broadcaster is gone")

    service.subscribe(explode)
    result = await service.flush()

    assert result.recorded == 1


async def test_a_pass_whose_reads_fail_does_not_raise(
    database: Database, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``stop()`` runs a final pass unconditionally, including after a failed migration.

    A database that never migrated fails on the very first *read*, not on the
    write, so a guard around the write alone would turn every shutdown of a
    degraded install into a traceback. The reads are inside it too.
    """

    async def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("no such table: sightings")

    service = await started(database, clock)
    monkeypatch.setattr(ActivityRepository, "sighting_ids_after", explode)

    result = await service.flush()

    assert result.failed is True
    # And a stop against the same database still completes.
    await service.stop()


# ----------------------------------------------------------------- lifecycle


async def test_the_background_task_runs_a_pass_on_its_own_cadence(
    database: Database, clock: ManualClock
) -> None:
    """Everything else drives ``flush`` by hand; this is the path production takes.

    The sleeper is injected and returns immediately, so the loop's cadence is
    exercised without a second of wall clock passing: what is asserted is that
    the task waits its configured interval and then runs a pass, not how long a
    second is (``docs/TEST_STRATEGY.md`` §3).
    """
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])
    await MetaRepository(database).set(SCAN_WATERMARK_KEY, "0")
    intervals: list[float] = []
    ran = asyncio.Event()

    async def sleeper(seconds: float) -> None:
        intervals.append(seconds)
        if len(intervals) > 1:
            # Second time round the task parks here rather than spinning the
            # loop for the rest of the test.
            ran.set()
            await asyncio.sleep(NEVER_S)

    service = ActivityService(database=database, flush_interval_s=2.5, clock=clock, sleep=sleeper)
    await service.start()
    try:
        await asyncio.wait_for(ran.wait(), timeout=5.0)
    finally:
        await service.stop()

    assert intervals[0] == 2.5
    assert await feed_keys(database) == ["first_ever_aircraft:ae1463"]


async def test_start_and_stop_are_idempotent(database: Database, clock: ManualClock) -> None:
    service = await started(database, clock)

    await service.start()
    assert service.running is True

    await service.stop()
    await service.stop()
    assert service.running is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("flush_interval_s", 0.0), ("offline_debounce_s", -1.0), ("scan_limit", 0)],
)
def test_a_nonsensical_cadence_is_refused_at_construction(
    database: Database, field: str, value: float
) -> None:
    """A misconfigured detector should fail loudly at wiring time, not silently later."""
    with pytest.raises(ValueError, match=field.split("_")[0]):
        ActivityService(database=database, **{field: value})  # type: ignore[arg-type]
