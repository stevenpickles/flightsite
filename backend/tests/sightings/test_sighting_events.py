"""Sighting events: meaningful changes, exactly once (SPEC §52).

``sighting_events`` is deliberately not a log of decoder snapshots. A row
appears when the flight took a new callsign, changed squawk, or entered or left
an emergency code — and the roadmap's acceptance criterion is that each such
change produces *exactly one* row.

"Exactly once" has three adversaries here, and each gets a test: a decoder
re-serving the same values every second, an overflow resync replaying records
the worker already folded in, and a restart that has to know what the previous
process already recorded. All three are answered the same way — the event is
decided against the accumulator's known last value, which is rehydrated from
the sighting row — so all three are worth pinning.
"""

from __future__ import annotations

import json
from pathlib import Path

from flightsite.db import Database
from flightsite.ingest import AircraftStateUpdate
from flightsite.live import LiveStore, appear
from flightsite.sightings import ActiveSighting, PersistenceWorker
from flightsite.sightings.vocabulary import SightingEventType

from .conftest import (
    BASE_EPOCH_MS,
    BASE_TIME,
    CLOSE_S,
    ICAO,
    REMOVE_S,
    SEATTLE,
    FailingOnceDatabase,
    SimulatedTime,
    events_of,
    observe,
    offset_from,
    only_sighting,
    worker_on,
)


async def timeline(database: Database) -> list[tuple[str, dict[str, str]]]:
    """The sighting's events as ``(type, payload)`` pairs, oldest first."""
    sighting = await only_sighting(database)
    return [
        (row.type, json.loads(row.payload_json) if row.payload_json else {})
        for row in await events_of(database, sighting.id)
    ]


# ----------------------------------------------------------- what is emitted


async def test_a_callsign_change_is_recorded(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, callsign="ASA123")
    await worker.process_pending()

    clock.advance(10.0)
    observe(live, clock, callsign="ASA456")
    await worker.process_pending()

    assert await timeline(database) == [
        (SightingEventType.CALLSIGN_CHANGE, {"from": "ASA123", "to": "ASA456"})
    ]


async def test_the_first_callsign_is_not_a_change(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # An aircraft appearing with a callsign changed nothing; the value belongs
    # on the sighting row (callsign_first), not on its timeline.
    observe(live, clock, callsign="ASA123")

    await worker.process_pending()

    assert await timeline(database) == []
    assert (await only_sighting(database)).callsign_first == "ASA123"


async def test_a_squawk_change_is_recorded(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, squawk="1200")
    clock.advance(10.0)
    observe(live, clock, squawk="4571")

    await worker.process_pending()

    assert await timeline(database) == [
        (SightingEventType.SQUAWK_CHANGE, {"from": "1200", "to": "4571"})
    ]


async def test_an_emergency_squawk_records_both_the_change_and_the_emergency(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Two distinct facts: the code changed, and the flight is now declaring an
    # emergency. The second is the one SPEC §47 cares about.
    observe(live, clock, squawk="1200")
    clock.advance(10.0)
    observe(live, clock, squawk="7700")

    await worker.process_pending()

    assert await timeline(database) == [
        (SightingEventType.SQUAWK_CHANGE, {"from": "1200", "to": "7700"}),
        (SightingEventType.EMERGENCY_START, {"squawk": "7700"}),
    ]
    assert (await only_sighting(database)).had_emergency == 1


async def test_an_emergency_on_the_first_observation_is_still_recorded(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # There is no previous squawk to change *from*, but the emergency itself
    # is the event — an aircraft first heard squawking 7500 is the case that
    # matters most.
    observe(live, clock, squawk="7500")

    await worker.process_pending()

    assert await timeline(database) == [(SightingEventType.EMERGENCY_START, {"squawk": "7500"})]


async def test_leaving_the_emergency_code_closes_the_episode(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, squawk="7700")
    clock.advance(10.0)
    observe(live, clock, squawk="1200")

    await worker.process_pending()

    kinds = [kind for kind, _ in await timeline(database)]
    assert kinds == [
        SightingEventType.EMERGENCY_START,
        SightingEventType.SQUAWK_CHANGE,
        SightingEventType.EMERGENCY_END,
    ]
    # ...and the sighting still remembers that it happened (SPEC §52).
    assert (await only_sighting(database)).had_emergency == 1


async def test_a_second_emergency_episode_fires_again(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    for squawk in ("7700", "1200", "7600"):
        clock.advance(10.0)
        observe(live, clock, squawk=squawk)

    await worker.process_pending()

    starts = [kind for kind, _ in await timeline(database) if kind == "emergency_start"]
    assert len(starts) == 2


async def test_events_carry_the_moment_the_change_was_observed(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The decoder's timestamp for the observation, not the cycle's wall clock:
    # playback puts events on the same timeline as the track (DATA_MODEL §11).
    observe(live, clock, callsign="ASA123")
    clock.advance(37.0)
    changed_at_ms = clock.epoch_ms()
    observe(live, clock, callsign="ASA999")

    await worker.process_pending()

    sighting = await only_sighting(database)
    (row,) = await events_of(database, sighting.id)
    assert row.ts_ms == changed_at_ms


# ------------------------------------------------------------- exactly once


async def test_a_repeated_value_emits_nothing_further(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The decoder re-serves the same trackfile every poll. One row per change,
    # not one per second.
    observe(live, clock, callsign="ASA123", squawk="7700")
    for _ in range(20):
        clock.advance(1.0)
        observe(live, clock, callsign="ASA123", squawk="7700")
        await worker.process_pending()

    assert len(await timeline(database)) == 1


async def test_an_unreported_field_ends_nothing(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """A ``None`` means "not reported this poll", never "cancelled".

    The live record's merge semantics keep the last known squawk; treating a
    silent poll as a change would emit an emergency_end for an aircraft still
    squawking 7700.
    """
    observe(live, clock, squawk="7700")
    for _ in range(5):
        clock.advance(1.0)
        observe(live, clock, altitude_ft=20_000.0)

    await worker.process_pending()

    assert [kind for kind, _ in await timeline(database)] == [SightingEventType.EMERGENCY_START]


async def test_a_resync_replay_emits_nothing_further(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # An overflow episode makes the worker rebuild from the live snapshot,
    # re-observing records it has already folded in.
    observe(live, clock, callsign="ASA123")
    clock.advance(10.0)
    observe(live, clock, callsign="ASA456")
    await worker.process_pending()

    accumulator = worker.sighting_for(ICAO)
    assert accumulator is not None
    for _ in range(3):
        for record in live.snapshot():
            accumulator.observe(record)
        await worker.process_pending()

    assert len(await timeline(database)) == 1


async def test_a_restart_does_not_repeat_a_recorded_change(
    worker: PersistenceWorker,
    live: LiveStore,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """The rehydrated last values are what make this exactly-once across processes.

    A new process adopts the open sighting and immediately sees the aircraft
    still transmitting the same callsign and the same emergency squawk. Both
    were already recorded; neither is a change.
    """
    observe(live, clock, callsign="ASA123", squawk="1200")
    clock.advance(10.0)
    observe(live, clock, callsign="ASA456", squawk="7700")
    await worker.process_pending()
    before = await timeline(database)
    await worker.stop()

    async with worker_on(database, live, clock) as restarted:
        for _ in range(3):
            clock.advance(5.0)
            observe(live, clock, callsign="ASA456", squawk="7700")
            await restarted.process_pending()

        assert await timeline(database) == before


async def test_a_restart_still_records_a_change_that_happened_across_it(
    worker: PersistenceWorker,
    live: LiveStore,
    clock: SimulatedTime,
    database: Database,
) -> None:
    # The other half of the guarantee: suppressing duplicates must not suppress
    # a real change the previous process never saw.
    observe(live, clock, callsign="ASA123")
    await worker.process_pending()
    await worker.stop()

    async with worker_on(database, live, clock) as restarted:
        clock.advance(5.0)
        observe(live, clock, callsign="ASA789")
        await restarted.process_pending()

        assert await timeline(database) == [
            (SightingEventType.CALLSIGN_CHANGE, {"from": "ASA123", "to": "ASA789"})
        ]


async def test_a_failed_cycle_retries_the_events_rather_than_losing_them(
    live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """Events are cleared only once their transaction commits.

    They are queued on the accumulator as the change happens, so a database
    error between the change and the write must leave them queued — the same
    discipline the sighting row itself is written under. Losing them instead
    would break exactly-once in the direction no later process can repair:
    the change is gone from the live stream too.
    """
    database = FailingOnceDatabase(db_path)
    await database.upgrade_to("head")
    try:
        async with worker_on(database, live, clock) as worker:
            observe(live, clock, callsign="ASA123")
            await worker.process_pending()

            clock.advance(10.0)
            observe(live, clock, callsign="ASA456")
            database.fail_next = True
            failed = await worker.process_pending()
            recovered = await worker.process_pending()

            assert failed.failed is True
            assert recovered.emitted == 1
            assert await timeline(database) == [
                (SightingEventType.CALLSIGN_CHANGE, {"from": "ASA123", "to": "ASA456"})
            ]
    finally:
        await database.dispose()


async def test_events_of_a_closing_sighting_are_still_written(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The transition happened inside the sighting, so it belongs to its
    # timeline even when the closing cycle is the first chance to write it.
    observe(live, clock, callsign="ASA123", position=offset_from(SEATTLE, 5.0, 0.0))
    clock.advance(10.0)
    observe(live, clock, callsign="ASA456")
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    clock.advance(CLOSE_S + 1.0)

    # One cycle carrying the open, the change and the close: the sighting's id
    # does not exist until part-way through that transaction.
    await worker.process_pending()

    sighting = await only_sighting(database)
    assert sighting.ended_ms is not None
    assert [kind for kind, _ in await timeline(database)] == [SightingEventType.CALLSIGN_CHANGE]


def test_a_sighting_with_no_last_callsign_records_no_change_from_nothing() -> None:
    """A defensive corner of the rehydration path.

    ``callsign_first`` without ``callsign_last`` is not a state the writer
    produces — it writes both together — but were a row ever to carry it, the
    event would read "from nothing", which is not a change. The first callsign
    is a value on the sighting row, not an entry on its timeline.
    """
    accumulator = ActiveSighting(
        icao=ICAO, started_ms=BASE_EPOCH_MS, last_seen_ms=BASE_EPOCH_MS, callsign_first="ASA123"
    )
    record = appear(AircraftStateUpdate(icao=ICAO, timestamp=BASE_TIME, callsign="ASA456"), now=0.0)

    accumulator.observe(record)

    assert accumulator.callsign_last == "ASA456"
    assert accumulator.pending_events == []
