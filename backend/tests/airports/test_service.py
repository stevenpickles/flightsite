"""Fixture tracks through the live store, and what comes out the other side.

This is the slice's first acceptance criterion, tested the way it is written:
*"known approach/departure fixture tracks yield correct, inferred-labeled
context; cruise traffic yields none."* Every case here drives a whole scripted
profile through the real :class:`~flightsite.live.store.LiveStore`, so what the
service sees is what a decoder poll produces, not a hand-built record.

The service is never started. The tests hand it events themselves, so every
inference happens at an instant the test chose and nothing races an assertion.
"""

from __future__ import annotations

import pytest

from flightsite.airports import AirportContextService, AirportRepository
from flightsite.airports.model import InferredPhase
from flightsite.airports.service import MAX_TRACKED_AIRCRAFT
from flightsite.db import Database
from flightsite.ingest import Position
from flightsite.live import LiveStore
from flightsite.live.events import AircraftRemoved
from flightsite.sightings import PersistenceWorker
from tests.airports.conftest import (
    BOEING_FIELD,
    FIXTURE_AIRPORTS,
    ICAO,
    OTHER_ICAO,
    SEATTLE_TACOMA,
    Sample,
    SimulatedTime,
    airport,
    ambiguous_track,
    appear,
    approach_track,
    cruise_track,
    departure_track,
    feed,
    fly,
    north_of,
    observe,
    only_sighting,
    overflight_track,
    seed_index,
)

# ------------------------------------------------------------ the criterion


async def test_an_approach_yields_an_inferred_arrival(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    await fly(service, live, clock, approach_track())

    context = service.context_for(ICAO)
    assert context is not None
    assert context.ident == "KBFI"
    assert context.name == "Boeing Field"
    assert context.phase is InferredPhase.ARRIVING
    assert context.distance_nm == pytest.approx(1.2, abs=0.05)


async def test_a_departure_yields_an_inferred_departure(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    await fly(service, live, clock, departure_track())

    context = service.context_for(ICAO)
    assert context is not None
    assert context.ident == "KBFI"
    assert context.phase is InferredPhase.DEPARTING


async def test_cruise_traffic_yields_nothing_at_all(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """Not "an airport with no phase" — nothing. An airliner at FL350 crossing
    a field is not near it in any sense a reader would mean."""
    await fly(service, live, clock, cruise_track())

    assert service.context_for(ICAO) is None


async def test_ambiguous_kinematics_yield_the_field_but_no_phase(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """Low and near a field, but level. The confidence gate, end to end."""
    await fly(service, live, clock, ambiguous_track())

    context = service.context_for(ICAO)
    assert context is not None
    assert context.ident == "KBFI"
    assert context.phase is None


async def test_descending_past_a_field_is_not_arriving_at_it(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """Still descending, but the range is growing: the trend gate refuses it."""
    await fly(service, live, clock, overflight_track())

    context = service.context_for(ICAO)
    assert context is not None
    assert context.phase is None


async def test_the_nearest_field_is_the_one_reported(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """The same profile flown at Sea-Tac names Sea-Tac, not Boeing Field."""
    await fly(service, live, clock, approach_track(), field=SEATTLE_TACOMA)

    context = service.context_for(ICAO)
    assert context is not None
    assert context.ident == "KSEA"


# --------------------------------------------------------------- the latch


async def test_a_phase_survives_a_momentary_level_off(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """An aircraft in the flare stops descending. It has not stopped arriving.

    Without the latch the panel would flicker between "likely arriving" and
    nothing once a second on short final.
    """
    await fly(service, live, clock, approach_track())
    assert service.context_for(ICAO) is not None

    await fly(service, live, clock, (Sample(range_nm=0.6, altitude_ft=200, vertical_rate_fpm=0),))

    context = service.context_for(ICAO)
    assert context is not None
    assert context.phase is InferredPhase.ARRIVING


async def test_the_latch_does_not_follow_the_aircraft_to_another_field(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """A phase is a statement about a field, not about an aircraft."""
    await fly(service, live, clock, approach_track())
    assert service.context_for(ICAO) is not None

    # Level at 2 000 ft over Sea-Tac: a different field, ambiguous kinematics.
    await fly(
        service,
        live,
        clock,
        (Sample(range_nm=1.0, altitude_ft=2_000, vertical_rate_fpm=0),),
        field=SEATTLE_TACOMA,
    )

    context = service.context_for(ICAO)
    assert context is not None
    assert context.ident == "KSEA"
    assert context.phase is None


# ---------------------------------------------------------- what it forgets


async def test_leaving_the_live_set_drops_everything_held(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """The persisted inference stays on the sighting; the live answer does not."""
    await fly(service, live, clock, approach_track())
    record = live.get(ICAO)
    assert record is not None

    service.consider(AircraftRemoved(aircraft=record, at=record.last_seen))

    assert service.context_for(ICAO) is None
    assert service.tracked == 0


async def test_flying_out_of_range_drops_a_stale_answer(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """A nearest airport the aircraft has left behind is worse than none."""
    await fly(service, live, clock, approach_track())
    assert service.context_for(ICAO) is not None

    clock.advance(60.0)
    observe(live, clock, position=Position(latitude=45.0, longitude=-127.0), altitude_ft=2_000)
    feed(service, live)

    assert service.context_for(ICAO) is None


async def test_an_aircraft_with_no_position_is_not_answered_about(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """Mode S only. No geometry, no context (SPEC §20 keeps it live regardless)."""
    observe(live, clock, position=None, callsign="N12345")
    appear(service, live)

    assert service.context_for(ICAO) is None


async def test_an_empty_index_answers_nothing_and_costs_nothing(
    live: LiveStore,
    worker: PersistenceWorker,
    repository: AirportRepository,
    clock: SimulatedTime,
) -> None:
    """The state of every install that has never run an update."""
    service = AirportContextService(live=live, persistence=worker, repository=repository)

    await fly(service, live, clock, approach_track())

    assert service.known_airports == 0
    assert service.context_for(ICAO) is None


# --------------------------------------------------------------- the index


async def test_the_index_rebuilds_after_an_import(
    live: LiveStore,
    worker: PersistenceWorker,
    repository: AirportRepository,
    clock: SimulatedTime,
) -> None:
    """The airport equivalent of the metadata cache's invalidation.

    An install with no dataset answers nothing; the same service answers
    correctly the moment an import has landed and the index is rebuilt — with
    no restart and no second service.
    """
    service = AirportContextService(live=live, persistence=worker, repository=repository)
    await fly(service, live, clock, approach_track())
    assert service.context_for(ICAO) is None

    await seed_index(repository, service, FIXTURE_AIRPORTS)
    assert service.known_airports == len(FIXTURE_AIRPORTS)

    await fly(service, live, clock, approach_track())
    assert service.context_for(ICAO) is not None


async def test_a_rebuild_replaces_the_whole_index(
    service: AirportContextService, repository: AirportRepository
) -> None:
    """A dataset that lost an airport loses it from memory too, not just on disk."""
    assert service.index.get("KBFI") is not None

    await seed_index(repository, service, [airport("ONLY1", 10.0, 10.0)])

    assert service.known_airports == 1
    assert service.index.get("KBFI") is None


async def test_reload_reports_what_it_loaded(
    service: AirportContextService, repository: AirportRepository
) -> None:
    assert await service.reload() == len(FIXTURE_AIRPORTS)


# ----------------------------------------------------------- persistence


async def test_a_confident_arrival_reaches_the_sighting_row(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """History keeps the inference — through the worker's cycle, not a session
    of the service's own (the seam route enrichment already uses)."""
    await fly(service, live, clock, approach_track(), worker=worker)
    await worker.process_pending(force_flush=True)

    row = await only_sighting(database)
    assert row.inferred_airport_ident == "KBFI"
    assert row.inferred_phase == "arriving"
    # And the columns stay apart from the enrichment ones (SPEC §28, §41).
    assert row.origin_ident is None
    assert row.destination_ident is None
    assert row.route_source is None


async def test_an_aircraft_on_the_ground_records_the_field_with_no_phase(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """The one no-phase case worth persisting: on the ground within the gate."""
    await fly(
        service,
        live,
        clock,
        (
            Sample(range_nm=0.4, altitude_ft=None, vertical_rate_fpm=None, on_ground=True),
            Sample(range_nm=0.5, altitude_ft=None, vertical_rate_fpm=None, on_ground=True),
        ),
        worker=worker,
    )
    await worker.process_pending(force_flush=True)

    row = await only_sighting(database)
    assert row.inferred_airport_ident == "KBFI"
    assert row.inferred_phase is None


async def test_flying_low_past_a_field_leaves_no_claim_in_history(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """A reported nearest airport is not the same as a claim about intent."""
    await fly(service, live, clock, ambiguous_track(), worker=worker)
    await worker.process_pending(force_flush=True)

    assert service.context_for(ICAO) is not None
    row = await only_sighting(database)
    assert row.inferred_airport_ident is None
    assert row.inferred_phase is None


async def test_a_phase_already_recorded_is_not_blanked_by_a_later_doubt(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """The sighting's history is "this aircraft was seen arriving at KBFI"; an
    ambiguous second afterwards does not unmake that."""
    await fly(service, live, clock, approach_track(), worker=worker)
    await worker.process_pending(force_flush=True)

    # Taxiing after landing: on the ground, no phase inferable any more.
    await fly(
        service,
        live,
        clock,
        (Sample(range_nm=0.3, altitude_ft=None, vertical_rate_fpm=None, on_ground=True),),
        worker=worker,
    )
    await worker.process_pending(force_flush=True)

    row = await only_sighting(database)
    assert row.inferred_airport_ident == "KBFI"
    assert row.inferred_phase == "arriving"


async def test_the_worker_reports_the_persisted_inference(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
) -> None:
    """The in-memory half the API could read without touching SQLite."""
    await fly(service, live, clock, approach_track(), worker=worker)

    inferred = worker.inferred_airport_for(ICAO)
    assert inferred is not None
    assert inferred.ident == "KBFI"
    assert inferred.phase == "arriving"


async def test_applying_to_an_aircraft_with_no_open_sighting_is_harmless(
    worker: PersistenceWorker,
) -> None:
    """The aircraft left the live set while the answer was being computed."""
    from flightsite.sightings.state import InferredAirport

    assert not worker.apply_inferred_airport(
        "ffffff", InferredAirport(ident="KBFI", phase="arriving"), at_ms=1
    )
    assert worker.inferred_airport_for("ffffff") is None


async def test_re_applying_the_same_inference_changes_nothing(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
) -> None:
    """Idempotent by comparison, exactly as `apply_route` is."""
    from flightsite.sightings.state import InferredAirport

    await fly(service, live, clock, approach_track(), worker=worker)
    inferred = InferredAirport(ident="KBFI", phase="arriving")

    assert not worker.apply_inferred_airport(ICAO, inferred, at_ms=clock.epoch_ms())


# -------------------------------------------------------------- book-keeping


async def test_two_aircraft_are_answered_about_independently(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    await fly(service, live, clock, approach_track(), icao=ICAO)
    await fly(service, live, clock, cruise_track(), icao=OTHER_ICAO, callsign="DAL1")

    assert service.context_for(ICAO) is not None
    assert service.context_for(OTHER_ICAO) is None


async def test_the_tracked_set_is_bounded(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """A leak in the removal path costs memory that stops growing.

    Driven through the service's own entry point rather than the live store,
    because putting four thousand aircraft in the sky would be a test of the
    store rather than of this bound.
    """
    await fly(service, live, clock, approach_track())
    assert service.tracked == 1

    record = live.get(ICAO)
    assert record is not None
    for index in range(MAX_TRACKED_AIRCRAFT + 5):
        clock.advance(1.0)
        observe(
            live,
            clock,
            icao=f"{index:06x}",
            position=north_of(BOEING_FIELD, 2.0),
            altitude_ft=1_500,
            vertical_rate_fpm=-700,
        )
        feed(service, live, icao=f"{index:06x}")

    assert service.tracked == MAX_TRACKED_AIRCRAFT


async def test_an_event_that_is_neither_an_observation_nor_a_removal_is_ignored(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """`AircraftStale` announces silence; it carries nothing new to reason about."""
    from flightsite.live.events import AircraftStale

    await fly(service, live, clock, approach_track())
    before = service.context_for(ICAO)
    record = live.get(ICAO)
    assert record is not None and before is not None

    service.consider(AircraftStale(aircraft=record, at=record.last_seen))

    assert service.context_for(ICAO) == before


async def test_a_trail_sample_older_than_the_window_is_pruned(
    service: AirportContextService, live: LiveStore, clock: SimulatedTime
) -> None:
    """The trend gate's window, enforced where the trail is kept rather than
    only where it is read — so a low aircraft loitering near a field for an
    hour costs a bounded number of samples, not an hour of them."""
    from flightsite.airports.inference import TREND_WINDOW_MS

    await fly(service, live, clock, approach_track())

    # Long enough that every sample so far has aged out, then a fresh approach
    # from the same direction. The phase must be inferred from the new samples
    # alone, which is only possible if the old ones were dropped rather than
    # silently mixed in.
    clock.advance(TREND_WINDOW_MS / 1_000 + 60.0)
    await fly(service, live, clock, approach_track())

    context = service.context_for(ICAO)
    assert context is not None
    assert context.phase is InferredPhase.ARRIVING


async def test_a_shed_event_is_acknowledged_rather_than_resynced(
    live: LiveStore,
    worker: PersistenceWorker,
    repository: AirportRepository,
    clock: SimulatedTime,
) -> None:
    """This consumer holds no history a gap could corrupt (unlike persistence).

    A one-deep subscription guarantees shedding; the service must notice, clear
    the flag, and carry on answering from the tail.
    """
    service = AirportContextService(
        live=live, persistence=worker, repository=repository, queue_size=1
    )
    await seed_index(repository, service, FIXTURE_AIRPORTS)
    await service.start()
    try:
        for sample in approach_track():
            clock.advance(sample.after_s)
            observe(
                live,
                clock,
                position=north_of(BOEING_FIELD, sample.range_nm),
                altitude_ft=sample.altitude_ft,
                vertical_rate_fpm=sample.vertical_rate_fpm,
                on_ground=sample.on_ground,
            )
            observe(
                live,
                clock,
                icao=OTHER_ICAO,
                position=north_of(SEATTLE_TACOMA, sample.range_nm),
                altitude_ft=sample.altitude_ft,
                vertical_rate_fpm=sample.vertical_rate_fpm,
                on_ground=sample.on_ground,
            )
        for _ in range(64):
            await _settle()
    finally:
        await service.stop()

    # Whatever was shed, the service is still answering rather than stuck.
    assert service.tracked >= 1


async def test_a_started_service_stops_cleanly(
    live: LiveStore, worker: PersistenceWorker, repository: AirportRepository
) -> None:
    """A restart in the same process must not leak a task or a subscription."""
    service = AirportContextService(live=live, persistence=worker, repository=repository)

    for _ in range(2):
        await service.start()
        assert service.running
        await service.start()  # idempotent
        await service.stop()
        assert not service.running

    await service.stop()  # safe before, and after, everything


async def test_a_started_service_consumes_the_live_stream(
    live: LiveStore,
    worker: PersistenceWorker,
    repository: AirportRepository,
    clock: SimulatedTime,
) -> None:
    """The task really is attached — the tests elsewhere drive `consider` directly."""
    service = AirportContextService(live=live, persistence=worker, repository=repository)
    await seed_index(repository, service, FIXTURE_AIRPORTS)
    await service.start()
    try:
        for sample in approach_track():
            clock.advance(sample.after_s)
            observe(
                live,
                clock,
                position=north_of(BOEING_FIELD, sample.range_nm),
                altitude_ft=sample.altitude_ft,
                vertical_rate_fpm=sample.vertical_rate_fpm,
                on_ground=sample.on_ground,
            )
            await _settle()
    finally:
        await service.stop()

    context = service.context_for(ICAO)
    assert context is not None
    assert context.phase is InferredPhase.ARRIVING


async def _settle() -> None:
    """Let the service's reader task drain what the store just published."""
    import asyncio

    for _ in range(4):
        await asyncio.sleep(0)


@pytest.mark.parametrize("queue_size", [0, -1])
async def test_an_unusable_queue_size_is_refused(
    live: LiveStore, worker: PersistenceWorker, repository: AirportRepository, queue_size: int
) -> None:
    with pytest.raises(ValueError, match="queue_size"):
        AirportContextService(
            live=live, persistence=worker, repository=repository, queue_size=queue_size
        )


# -------------------------------------------------- naming somebody else's ident


async def test_the_service_names_an_ident_from_the_imported_dataset(
    service: AirportContextService,
) -> None:
    """``route.origin_name`` (``docs/API.md`` §2.6) is answered from the same
    index the nearest-airport inference uses, and makes no claim of its own."""
    assert service.name_for("KBFI") == "Boeing Field"
    assert service.name_for("ZZZZ") is None


async def test_the_service_names_nothing_before_an_import(
    live: LiveStore, worker: PersistenceWorker, repository: AirportRepository
) -> None:
    """A stock install: every name is null and no payload changes shape for it."""
    unseeded = AirportContextService(live=live, persistence=worker, repository=repository)

    assert unseeded.known_airports == 0
    assert unseeded.name_for("KBFI") is None


async def test_a_reimport_renames_a_field(
    service: AirportContextService, repository: AirportRepository
) -> None:
    """The index swap is what makes a name current, exactly as it is for the
    nearest-airport answers built from the same reference."""
    await seed_index(repository, service, [airport("KBFI", *BOEING_FIELD, name="Old Name")])
    assert service.name_for("KBFI") == "Old Name"

    await seed_index(repository, service, [airport("KBFI", *BOEING_FIELD, name="New Name")])

    assert service.name_for("KBFI") == "New Name"
