"""Per-sighting extremes, aircraft lifetime records, flight context, and T0.

The two halves of ADR-0004's identity model are checked against each other
here: what a *sighting* recorded (this flight's callsign, this pass's closest
approach) and what the *airframe* accumulated across sightings (SPEC §53). A
value in the wrong one of those two places is the failure this file exists to
catch.
"""

from __future__ import annotations

from flightsite.db import Database, MetaRepository
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

from .conftest import (
    CLOSE_S,
    ICAO,
    REMOVE_S,
    SEATTLE,
    SimulatedTime,
    aircraft_row,
    existing_aircraft,
    north_of,
    observe,
    only_sighting,
    sightings_of,
)


async def _close_current_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime
) -> None:
    """Take whatever is live through removal and the full closure gap."""
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S)
    await worker.process_pending()


async def test_per_sighting_extremes_track_the_observations(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    for nm, altitude_ft in ((20.0, 12_000.0), (4.0, 3_500.0), (31.0, 27_400.0)):
        observe(live, clock, position=north_of(SEATTLE, nm), altitude_ft=altitude_ft)
        clock.advance(10.0)
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)

    sighting = await only_sighting(database)

    assert sighting.closest_approach_nm is not None
    assert round(sighting.closest_approach_nm) == 4
    assert sighting.max_range_nm is not None
    assert round(sighting.max_range_nm) == 31
    assert sighting.lowest_alt_ft == 3_500
    assert sighting.highest_alt_ft == 27_400


async def test_extremes_carry_the_moment_they_were_set(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, position=north_of(SEATTLE, 30.0), altitude_ft=30_000.0)
    clock.advance(60.0)
    observe(live, clock, position=north_of(SEATTLE, 2.0), altitude_ft=1_200.0)
    closest_ms = clock.epoch_ms()
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)

    aircraft = await existing_aircraft(database)

    assert aircraft.closest_approach_ms == closest_ms
    assert aircraft.lowest_alt_ms == closest_ms
    assert aircraft.max_range_ms == closest_ms - 60_000
    assert aircraft.highest_alt_ms == closest_ms - 60_000


async def test_lifetime_records_keep_the_best_of_every_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # First pass: far and high.
    observe(live, clock, position=north_of(SEATTLE, 40.0), altitude_ft=35_000.0)
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)

    # Second pass: close and low, a week later.
    clock.advance(7 * 24 * 3_600.0)
    observe(live, clock, position=north_of(SEATTLE, 1.5), altitude_ft=800.0)
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)

    first, second = await sightings_of(database)
    aircraft = await existing_aircraft(database)

    # Each sighting knows only its own pass...
    assert first.lowest_alt_ft == 35_000
    assert second.highest_alt_ft == 800
    # ...while the airframe keeps the record across both.
    assert aircraft.sighting_count == 2
    assert aircraft.lowest_alt_ft == 800
    assert aircraft.highest_alt_ft == 35_000
    assert aircraft.max_range_nm is not None and round(aircraft.max_range_nm) == 40
    assert aircraft.closest_approach_nm is not None
    assert round(aircraft.closest_approach_nm, 1) == 1.5


async def test_total_observed_time_sums_closed_sightings(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    for duration_s in (120.0, 45.0):
        observe(live, clock)
        clock.advance(duration_s)
        observe(live, clock)
        await worker.process_pending()
        await _close_current_sighting(worker, live, clock)
        clock.advance(3_600.0)

    aircraft = await existing_aircraft(database)

    assert aircraft.total_observed_ms == 165_000
    assert aircraft.sighting_count == 2


async def test_first_and_last_seen_span_the_airframes_whole_history(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    first_ms = clock.epoch_ms()
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)

    clock.advance(30 * 24 * 3_600.0)
    observe(live, clock)
    last_ms = clock.epoch_ms()
    await worker.process_pending()

    aircraft = await existing_aircraft(database)

    assert aircraft.first_seen_ms == first_ms
    assert aircraft.last_seen_ms == last_ms


async def test_lifetime_records_are_visible_before_the_sighting_closes(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # A record set by an aircraft still overhead is worth showing now, and
    # surviving a crash; waiting for the close would risk both.
    observe(live, clock, position=north_of(SEATTLE, 3.0), altitude_ft=2_000.0)
    await worker.process_pending()

    aircraft = await existing_aircraft(database)

    assert aircraft.closest_approach_nm is not None
    assert (await only_sighting(database)).ended_ms is None


async def test_no_range_records_without_a_receiver_location(
    database: Database, clock: SimulatedTime
) -> None:
    # First run, before the setup wizard has collected a location: the live
    # record has no distance, so the sighting honestly has no range extremes
    # rather than a fabricated zero (SPEC §39).
    unsited = LiveStore(clock=clock.monotonic, receiver_location=None)
    worker = PersistenceWorker(
        database=database,
        live=unsited,
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        observe(unsited, clock, position=north_of(SEATTLE, 12.0), altitude_ft=9_000.0)
        await worker.process_pending()

        sighting = await only_sighting(database)
        assert sighting.closest_approach_nm is None
        assert sighting.max_range_nm is None
        # Altitude does not depend on knowing where the receiver is.
        assert sighting.highest_alt_ft == 9_000
    finally:
        await worker.stop()


async def test_flight_context_is_recorded_on_the_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, callsign="ASA123", squawk="4271")
    clock.advance(30.0)
    observe(live, clock, callsign="ASA124", squawk="4271")
    await worker.process_pending()

    sighting = await only_sighting(database)

    assert sighting.callsign_first == "ASA123"
    assert sighting.callsign_last == "ASA124"
    assert sighting.squawk_last == "4271"
    assert sighting.had_emergency == 0


async def test_an_emergency_squawk_is_remembered_after_it_clears(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, squawk="1200")
    clock.advance(10.0)
    observe(live, clock, squawk="7700")
    clock.advance(10.0)
    observe(live, clock, squawk="1200")
    await worker.process_pending()

    sighting = await only_sighting(database)

    assert sighting.had_emergency == 1
    assert sighting.squawk_last == "1200"


async def test_position_character_flags_latch(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    clock.advance(10.0)
    observe(live, clock, position=north_of(SEATTLE, 8.0), position_source="mlat")
    clock.advance(10.0)
    observe(live, clock, position=north_of(SEATTLE, 8.0), on_ground=True)
    await worker.process_pending()

    sighting = await only_sighting(database)

    assert sighting.any_position == 1
    assert sighting.mlat_used == 1
    assert sighting.ground_seen == 1


async def test_a_non_positioned_aircraft_still_gets_a_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Mode S-only trackfiles are first-class (SPEC §20): they belong in
    # history, with the position columns honestly empty.
    observe(live, clock, callsign="N12345", altitude_ft=4_000.0)
    await worker.process_pending()

    sighting = await only_sighting(database)

    assert sighting.any_position == 0
    assert sighting.closest_approach_nm is None
    assert sighting.callsign_first == "N12345"
    assert sighting.highest_alt_ft == 4_000


async def test_reception_statistics_are_left_for_slice_052(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, rssi_db=-12.5, messages=400)
    await worker.process_pending()

    sighting = await only_sighting(database)

    assert sighting.msg_count == 0
    assert sighting.pos_count == 0
    assert sighting.rssi_peak_db is None
    assert sighting.rssi_avg_db is None
    assert sighting.pos_time_pct is None
    # As are enrichment and alert outcomes.
    assert sighting.origin_ident is None
    assert sighting.route_source is None
    assert sighting.max_alert_severity is None


async def test_t0_stays_unset_until_an_observation_is_persisted(
    worker: PersistenceWorker, database: Database
) -> None:
    await worker.process_pending()

    assert await MetaRepository(database).get_t0() is None
    assert worker.t0_established is False


async def test_t0_is_the_first_persisted_observation(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    clock.advance(90.0)
    observe(live, clock)
    first_ms = clock.epoch_ms()
    await worker.process_pending()

    assert await MetaRepository(database).get_t0() == first_ms
    assert worker.t0_established is True


async def test_t0_is_written_exactly_once_across_restarts(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    t0_ms = await MetaRepository(database).get_t0()
    await worker.stop()

    # A second process, a day later, seeing an aircraft it has never seen
    # before: T0 anchors lifetime statistics and must not move (SPEC §16).
    clock.advance(24 * 3_600.0)
    restarted = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        clock=clock.epoch_ms,
    )
    await restarted.start()
    try:
        assert restarted.t0_established is True
        observe(live, clock, "c0ffee")
        await restarted.process_pending()

        assert await MetaRepository(database).get_t0() == t0_ms
    finally:
        await restarted.stop()


async def test_t0_written_by_someone_else_first_is_left_alone(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # T0 is write-once in SQL, not merely in this worker's memory: whatever
    # already stands wins, and the worker does not object.
    meta = MetaRepository(database)
    earlier_ms = clock.epoch_ms() - 5_000
    assert await meta.set_t0_once(earlier_ms) is True

    observe(live, clock)
    await worker.process_pending()

    assert await meta.get_t0() == earlier_ms
    assert worker.t0_established is True


async def test_nothing_is_persisted_for_an_aircraft_never_observed(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, ICAO)
    await worker.process_pending()

    assert await aircraft_row(database, "ffffff") is None
