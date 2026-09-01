"""The read surface, the sweep task, and the no-database invariant."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import flightsite.live
from flightsite.ingest import AircraftStateBatch, Position
from flightsite.live import DEFAULT_TRACK_CAPACITY, LiveState, LiveStore

from .conftest import BASE_TIME, ICAO, SEATTLE, ManualClock, make_batch, make_update

POSITION = Position(latitude=47.0, longitude=-122.0)


def test_the_live_package_never_reaches_for_the_database() -> None:
    # The no-SQLite-on-the-live-path invariant (docs/ARCHITECTURE.md §3.1) is
    # structural, so it is asserted structurally: a future edit that imports a
    # session fails here rather than in a latency graph months later.
    package_dir = Path(flightsite.live.__file__).parent

    for module in sorted(package_dir.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        assert "flightsite.db" not in source, f"{module.name} imports the database layer"
        assert "sqlalchemy" not in source, f"{module.name} imports SQLAlchemy"


def test_get_returns_none_for_an_unknown_aircraft(live_store: LiveStore) -> None:
    assert live_store.get("ffffff") is None
    assert "ffffff" not in live_store


def test_snapshot_holds_every_live_aircraft(live_store: LiveStore) -> None:
    live_store.apply_updates([make_update("ae1463"), make_update("4ca7b3", position=POSITION)])

    snapshot = live_store.snapshot()

    assert isinstance(snapshot, tuple)
    assert {aircraft.icao for aircraft in snapshot} == {"ae1463", "4ca7b3"}


def test_a_snapshot_is_not_disturbed_by_later_updates(live_store: LiveStore) -> None:
    live_store.apply_updates([make_update(callsign="RCH492")])
    snapshot = live_store.snapshot()

    live_store.apply_updates([make_update(offset_s=1.0, callsign="RCH493")])

    assert snapshot[0].callsign == "RCH492"
    assert live_store.snapshot()[0].callsign == "RCH493"


def test_counts_separate_positioned_from_non_positioned(live_store: LiveStore) -> None:
    live_store.apply_updates(
        [
            make_update("ae1463", position=POSITION),
            make_update("4ca7b3", position=POSITION, position_source="mlat"),
            make_update("a12345"),
        ]
    )

    counts = live_store.counts()

    assert counts.total == 3
    assert counts.positioned == 2
    assert counts.non_positioned == 1
    assert counts.stale == 0
    assert len(live_store) == 3


def test_stale_aircraft_are_counted_without_leaving_their_category(
    live_store: LiveStore, clock: ManualClock
) -> None:
    live_store.apply_updates([make_update("ae1463", position=POSITION), make_update("4ca7b3")])
    clock.advance(live_store.stale_s)

    counts = live_store.sweep()

    assert counts.total == 2
    assert counts.positioned == 1
    assert counts.stale == 2


def test_an_empty_store_counts_zero(live_store: LiveStore) -> None:
    assert live_store.counts().total == 0


def test_an_empty_batch_is_a_no_op(live_store: LiveStore) -> None:
    live_store.apply(AircraftStateBatch(timestamp=BASE_TIME))

    assert len(live_store) == 0


def test_a_batch_is_applied_as_the_ingestion_consumer_callback(live_store: LiveStore) -> None:
    # `LiveStore.apply` is what the app hands to IngestionService, so it must
    # accept an AircraftStateBatch verbatim.
    live_store.apply(make_batch(make_update(), make_update("4ca7b3")))

    assert len(live_store) == 2


def test_every_update_in_a_batch_shares_one_clock_reading(
    live_store: LiveStore, clock: ManualClock
) -> None:
    live_store.apply(make_batch(make_update("ae1463"), make_update("4ca7b3")))

    ages = {aircraft.last_seen_monotonic for aircraft in live_store.snapshot()}

    assert ages == {clock()}


def test_the_receiver_location_is_reported_and_replaceable(live_store: LiveStore) -> None:
    assert live_store.receiver_location == SEATTLE

    live_store.set_receiver_location(None)
    live_store.apply_updates([make_update(position=POSITION)])

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.distance_nm is None


def test_a_newly_configured_receiver_takes_effect_on_the_next_observation() -> None:
    # The first-run path: the store starts with no location, the wizard sets
    # one, and derived range appears without a restart.
    store = LiveStore(clock=ManualClock(), receiver_location=None)
    store.apply_updates([make_update(position=POSITION)])
    assert store.snapshot()[0].distance_nm is None

    store.set_receiver_location(SEATTLE)
    store.apply_updates([make_update(offset_s=1.0, position=POSITION)])

    assert store.snapshot()[0].distance_nm == pytest.approx(29.82, abs=0.05)


def test_the_track_capacity_is_configurable() -> None:
    store = LiveStore(clock=ManualClock(), track_capacity=2)
    for step in range(4):
        store.apply_updates(
            [
                make_update(
                    offset_s=float(step),
                    position=Position(latitude=47.0 + step * 0.1, longitude=-122.0),
                )
            ]
        )

    aircraft = store.get(ICAO)
    assert aircraft is not None
    assert len(aircraft.track) == 2
    assert aircraft.track.dropped == 2


def test_the_default_track_capacity_is_used_when_unspecified(live_store: LiveStore) -> None:
    live_store.apply_updates([make_update(position=POSITION)])

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.track.capacity == DEFAULT_TRACK_CAPACITY


# ------------------------------------------------------------- sweep task


async def test_the_sweep_task_expires_aircraft_without_being_asked(
    clock: ManualClock,
) -> None:
    # The thresholds themselves are asserted against simulated time elsewhere;
    # what this proves is that the background task actually runs the sweep.
    store = LiveStore(clock=clock, sweep_interval_s=0.001)
    store.apply_updates([make_update()])
    await store.start()
    assert store.sweeping is True

    clock.advance(store.remove_s)
    for _ in range(200):
        if len(store) == 0:
            break
        await asyncio.sleep(0.005)

    await store.stop()
    assert len(store) == 0
    assert store.sweeping is False


async def test_starting_and_stopping_are_idempotent(live_store: LiveStore) -> None:
    await live_store.stop()

    await live_store.start()
    await live_store.start()
    assert live_store.sweeping is True

    await live_store.stop()
    await live_store.stop()
    assert live_store.sweeping is False


async def test_a_stopped_store_still_answers_reads(live_store: LiveStore) -> None:
    live_store.apply_updates([make_update()])
    await live_store.start()
    await live_store.stop()

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE
