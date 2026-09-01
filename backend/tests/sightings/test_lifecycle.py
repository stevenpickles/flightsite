"""Sighting open / continue / close semantics under simulated time (SPEC §18).

The rule being pinned here is small to state and easy to get wrong: a sighting
opens on the first observation, stays open while the aircraft is absent for up
to the closure gap, is *continued* if the aircraft is heard again inside that
gap, and only afterwards may a new sighting begin. Every assertion below is one
half of that sentence.
"""

from __future__ import annotations

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import ClosureReason, PersistenceWorker

from .conftest import (
    CLOSE_S,
    ICAO,
    OTHER_ICAO,
    REMOVE_S,
    STALE_S,
    SimulatedTime,
    existing_aircraft,
    observe,
    only_sighting,
    sightings_of,
)


async def test_the_first_observation_opens_a_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)

    result = await worker.process_pending()

    assert result.opened == 1
    sighting = await only_sighting(database)
    assert sighting.started_ms == clock.epoch_ms()
    assert sighting.ended_ms is None
    assert sighting.closure_reason is None


async def test_opening_a_sighting_creates_its_aircraft(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()

    aircraft = await existing_aircraft(database)

    assert aircraft.icao24 == ICAO
    assert aircraft.sighting_count == 1
    assert aircraft.first_seen_ms == clock.epoch_ms()
    assert aircraft.total_observed_ms == 0


async def test_continued_observation_never_opens_a_second_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The no-reopen rule, exercised the way it actually fails: hundreds of
    # updates for an aircraft that is already being sighted.
    for _ in range(200):
        observe(live, clock)
        clock.advance(1.0)
        await worker.process_pending()

    assert len(await sightings_of(database)) == 1
    assert (await existing_aircraft(database)).sighting_count == 1


async def test_leaving_the_live_set_does_not_close_the_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Removal from the live display (60 s) and sighting closure (600 s) are
    # different thresholds; conflating them would end sightings ten times early.
    observe(live, clock)
    await worker.process_pending()

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    result = await worker.process_pending()

    assert result.closed == 0
    assert worker.pending_count == 1
    assert worker.active_count == 0
    assert (await only_sighting(database)).ended_ms is None


async def test_going_stale_changes_nothing(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()

    clock.advance(STALE_S + 1.0)
    live.sweep()
    result = await worker.process_pending()

    assert result.closed == 0
    assert worker.active_count == 1
    assert (await only_sighting(database)).ended_ms is None


async def test_reappearing_inside_the_gap_continues_the_same_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    opened = await only_sighting(database)

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    # Back with nine minutes of the ten-minute gap gone.
    clock.advance(CLOSE_S - REMOVE_S - 61.0)
    observe(live, clock)
    result = await worker.process_pending()

    assert result.opened == 0
    continued = await only_sighting(database)
    assert continued.id == opened.id
    assert continued.started_ms == opened.started_ms
    assert continued.ended_ms is None
    assert worker.active_count == 1
    assert worker.pending_count == 0
    assert (await existing_aircraft(database)).sighting_count == 1


async def test_reappearing_restarts_the_gap_from_the_new_observation(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    clock.advance(300.0)
    observe(live, clock)
    heard_again_ms = clock.epoch_ms()
    await worker.process_pending()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    # Past the original deadline, but not past one measured from the second
    # observation: the sighting is still open.
    clock.advance(CLOSE_S - REMOVE_S - 1.0 - 300.0)
    await worker.process_pending()
    assert (await only_sighting(database)).ended_ms is None

    clock.advance(300.0)
    await worker.process_pending()
    closed = await only_sighting(database)
    assert closed.ended_ms == heard_again_ms


async def test_absence_beyond_the_gap_closes_with_gap_timeout(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    started_ms = clock.epoch_ms()
    clock.advance(120.0)
    observe(live, clock)
    last_heard_ms = clock.epoch_ms()
    await worker.process_pending()

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    clock.advance(CLOSE_S)
    result = await worker.process_pending()

    assert result.closed == 1
    sighting = await only_sighting(database)
    assert sighting.closure_reason == ClosureReason.GAP_TIMEOUT.value
    # The sighting ends when the aircraft was last heard, not when the gap
    # expired: the ten minutes of silence were not part of the observation.
    assert sighting.ended_ms == last_heard_ms
    assert sighting.duration_ms == last_heard_ms - started_ms
    assert worker.pending_count == 0


async def test_the_sighting_closes_at_the_gap_and_not_a_millisecond_before(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    clock.advance(CLOSE_S - REMOVE_S - 1.0 - 0.001)
    await worker.process_pending()
    assert (await only_sighting(database)).ended_ms is None

    clock.advance(0.001)
    await worker.process_pending()
    assert (await only_sighting(database)).ended_ms is not None


async def test_a_new_sighting_begins_only_after_the_previous_one_closed(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S)
    await worker.process_pending()

    clock.advance(60.0)
    observe(live, clock)
    second_start_ms = clock.epoch_ms()
    await worker.process_pending()

    first, second = await sightings_of(database)
    assert first.ended_ms is not None
    assert second.id != first.id
    assert second.started_ms == second_start_ms
    assert second.ended_ms is None
    assert (await existing_aircraft(database)).sighting_count == 2


async def test_the_configured_gap_is_what_closes_the_sighting(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    # `sighting.close_s` is configurable (SPEC §18); a worker built with a
    # shorter gap must use it rather than the 600 s default.
    brief = PersistenceWorker(
        database=database, live=live, close_s=90.0, tick_interval_s=3_600.0, clock=clock.epoch_ms
    )
    await brief.start()
    try:
        observe(live, clock)
        await brief.process_pending()
        clock.advance(REMOVE_S + 1.0)
        live.sweep()
        await brief.process_pending()

        clock.advance(20.0)
        await brief.process_pending()
        assert (await only_sighting(database)).ended_ms is None

        clock.advance(10.0)
        await brief.process_pending()
        assert (await only_sighting(database)).ended_ms is not None
    finally:
        await brief.stop()


async def test_each_aircraft_gets_its_own_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, ICAO)
    observe(live, clock, OTHER_ICAO)
    await worker.process_pending()

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    # Only one of them comes back before the gap expires; the other's clock
    # keeps running, so the two close at different moments.
    clock.advance(CLOSE_S - REMOVE_S - 61.0)
    observe(live, clock, ICAO)
    heard_again_ms = clock.epoch_ms()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    clock.advance(CLOSE_S)
    await worker.process_pending()

    mine = await only_sighting(database, ICAO)
    theirs = await only_sighting(database, OTHER_ICAO)
    assert mine.ended_ms == heard_again_ms
    assert theirs.ended_ms is not None and theirs.ended_ms < mine.ended_ms
    assert worker.active_count == 0
    assert worker.pending_count == 0


async def test_a_removal_without_its_appearance_still_records_the_sighting(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    # The worker starts after ingestion has already filled the live store, so
    # its first event for this aircraft is the removal — which carries the full
    # record. Dropping it would silently lose an observation period.
    observe(live, clock)
    started_ms = clock.epoch_ms()

    late = PersistenceWorker(
        database=database, live=live, close_s=CLOSE_S, tick_interval_s=3_600.0, clock=clock.epoch_ms
    )
    await late.start()
    try:
        clock.advance(REMOVE_S + 1.0)
        live.sweep()
        await late.process_pending()

        assert late.pending_count == 1
        recorded = await only_sighting(database)
        assert recorded.started_ms == started_ms
        assert recorded.ended_ms is None
    finally:
        await late.stop()


async def test_an_aircraft_with_no_events_persists_nothing(
    worker: PersistenceWorker, database: Database
) -> None:
    result = await worker.process_pending()

    assert result == type(result)()
    assert await sightings_of(database) == []
