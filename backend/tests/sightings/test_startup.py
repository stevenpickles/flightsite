"""Restart behaviour: what a new worker does with sightings left open.

A restart must not be silently destructive: a sighting whose aircraft is still
being heard continues in the same row, and one whose closure gap expired while
the process was down is closed at the last moment the aircraft was actually
heard — never left open forever, and never duplicated by a second sighting
opening alongside it.

The closure itself is startup recovery's (slice 053): a process that came back
never watched that gap, so the reason recorded is ``shutdown_recovery`` and the
close happens inside :meth:`PersistenceWorker.start` rather than on the first
cycle. The drills covering *what* is recovered live in ``test_recovery.py``;
what this module pins is that the restart contract around it is unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import ClosureReason, PersistenceWorker

from .conftest import (
    CLOSE_S,
    ICAO,
    REMOVE_S,
    SEATTLE,
    SimulatedTime,
    existing_aircraft,
    north_of,
    observe,
    only_sighting,
    sightings_of,
)


def restart(database: Database, live: LiveStore, clock: SimulatedTime) -> PersistenceWorker:
    """A fresh worker over the same database — the next process."""
    return PersistenceWorker(
        database=database, live=live, close_s=CLOSE_S, tick_interval_s=3_600.0, clock=clock.epoch_ms
    )


async def test_a_clean_stop_leaves_the_sighting_open(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Stopping is not an observation gap. Closing here would chop every
    # sighting in the sky in half on a routine restart.
    observe(live, clock)
    await worker.process_pending()

    await worker.stop()

    assert (await only_sighting(database)).ended_ms is None


async def test_a_restart_continues_a_sighting_still_being_heard(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, callsign="ASA100")
    await worker.process_pending()
    original = await only_sighting(database)
    await worker.stop()

    clock.advance(20.0)
    successor = restart(database, live, clock)
    await successor.start()
    try:
        assert successor.pending_count == 1

        observe(live, clock, callsign="ASA100", altitude_ft=11_000.0)
        await successor.process_pending()

        continued = await only_sighting(database)
        assert continued.id == original.id
        assert continued.started_ms == original.started_ms
        assert continued.ended_ms is None
        assert continued.highest_alt_ft == 11_000
        assert (await existing_aircraft(database)).sighting_count == 1
    finally:
        await successor.stop()


async def test_an_adopted_sighting_keeps_its_flight_context(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The callsign this flight started with belongs to the sighting; a restart
    # must not overwrite it with whatever the aircraft is squawking now.
    observe(live, clock, callsign="ASA100", position=north_of(SEATTLE, 25.0), altitude_ft=30_000.0)
    await worker.process_pending()
    await worker.stop()

    successor = restart(database, live, clock)
    await successor.start()
    try:
        clock.advance(30.0)
        observe(live, clock, callsign="ASA200", position=north_of(SEATTLE, 5.0))
        await successor.process_pending()

        sighting = await only_sighting(database)
        assert sighting.callsign_first == "ASA100"
        assert sighting.callsign_last == "ASA200"
        # The extremes from before the restart survive alongside the new ones.
        assert sighting.highest_alt_ft == 30_000
        assert sighting.max_range_nm is not None and round(sighting.max_range_nm) == 25
        assert sighting.closest_approach_nm is not None
        assert round(sighting.closest_approach_nm) == 5
    finally:
        await successor.stop()


async def test_a_restart_closes_a_sighting_whose_gap_expired_while_down(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    last_heard_ms = clock.epoch_ms()
    await worker.process_pending()
    await worker.stop()

    # The process was down for longer than the closure gap.
    clock.advance(CLOSE_S + 60.0)
    successor = restart(database, live, clock)
    await successor.start()
    try:
        assert successor.recovery.recovered == 1
        sighting = await only_sighting(database)
        assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
        assert sighting.ended_ms == last_heard_ms
        assert successor.pending_count == 0
        assert (await successor.process_pending()).wrote is False
    finally:
        await successor.stop()


async def test_an_expired_adoption_still_credits_the_airframe(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    clock.advance(240.0)
    observe(live, clock)
    await worker.process_pending()
    await worker.stop()

    clock.advance(CLOSE_S + 60.0)
    successor = restart(database, live, clock)
    await successor.start()
    try:
        await successor.process_pending()

        aircraft = await existing_aircraft(database)
        assert aircraft.total_observed_ms == 240_000
        assert aircraft.sighting_count == 1
    finally:
        await successor.stop()


async def test_a_new_sighting_follows_an_adopted_one_that_closed(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    await worker.stop()
    clock.advance(CLOSE_S + 60.0)

    successor = restart(database, live, clock)
    await successor.start()
    try:
        await successor.process_pending()
        clock.advance(30.0)
        observe(live, clock)
        await successor.process_pending()

        first, second = await sightings_of(database)
        assert first.ended_ms is not None
        assert second.ended_ms is None
        assert (await existing_aircraft(database)).sighting_count == 2
    finally:
        await successor.stop()


async def test_a_restart_with_no_history_adopts_nothing(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    fresh = restart(database, live, clock)
    await fresh.start()
    try:
        assert fresh.pending_count == 0
        assert fresh.active_count == 0
        assert (await fresh.process_pending()).wrote is False
    finally:
        await fresh.stop()


async def test_adoption_survives_a_second_restart(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Restart loops (a crash-looping container) must not multiply sightings.
    observe(live, clock)
    await worker.process_pending()
    await worker.stop()

    for _ in range(3):
        successor = restart(database, live, clock)
        await successor.start()
        clock.advance(10.0)
        observe(live, clock)
        await successor.process_pending()
        await successor.stop()

    assert len(await sightings_of(database)) == 1
    assert (await existing_aircraft(database)).sighting_count == 1


async def test_starting_an_already_started_worker_is_a_no_op(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()

    await worker.start()

    assert len(await sightings_of(database)) == 1
    assert worker.active_count == 1


async def test_stopping_a_worker_that_never_started_is_safe(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    await restart(database, live, clock).stop()


@pytest.mark.parametrize(
    ("timing", "message"),
    [
        ({"close_s": 0.0}, "close_s"),
        ({"flush_interval_s": -1.0}, "flush_interval_s"),
        ({"tick_interval_s": 0.0}, "tick_interval_s"),
    ],
)
def test_non_positive_timings_are_rejected_at_construction(
    database: Database, live: LiveStore, timing: dict[str, Any], message: str
) -> None:
    # A zero interval would spin the loop or close every sighting instantly;
    # failing at construction beats discovering it in production.
    with pytest.raises(ValueError, match=message):
        PersistenceWorker(database=database, live=live, **timing)


async def test_the_background_task_persists_without_being_driven(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    # Everywhere else the tests call `process_pending` directly; this is the
    # one place the real loop has to prove it runs on its own.
    ticking = PersistenceWorker(
        database=database, live=live, close_s=CLOSE_S, tick_interval_s=0.01, clock=clock.epoch_ms
    )
    await ticking.start()
    try:
        assert ticking.running is True
        observe(live, clock, ICAO)
        for _ in range(500):
            if await sightings_of(database, ICAO):
                break
            await asyncio.sleep(0.01)
        assert await sightings_of(database, ICAO)
    finally:
        await ticking.stop()

    assert ticking.running is False


async def test_a_removal_after_shutdown_is_still_closed_on_the_next_start(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The aircraft left the live set, the process stopped before the gap
    # expired, and the gap expired while it was down.
    observe(live, clock)
    await worker.process_pending()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.stop()

    clock.advance(CLOSE_S)
    successor = restart(database, live, clock)
    await successor.start()
    try:
        assert successor.recovery.recovered == 1
        sighting = await only_sighting(database)
        assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
    finally:
        await successor.stop()
