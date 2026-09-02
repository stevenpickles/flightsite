"""Lifecycle transitions under simulated time.

The thresholds are asserted at their exact boundary — one microsecond short and
one exactly on — because "roughly 15 seconds" is not a contract anybody can
build a sighting engine on. Nothing here sleeps.
"""

from __future__ import annotations

from typing import Any

import pytest

from flightsite.ingest import Position
from flightsite.live import (
    AircraftAppeared,
    AircraftRemoved,
    AircraftStale,
    AircraftUpdated,
    EventSubscription,
    LiveState,
    LiveStore,
)

from .conftest import BASE_TIME, ICAO, ManualClock, make_batch, make_update


@pytest.fixture
def events(live_store: LiveStore) -> EventSubscription:
    return live_store.subscribe("test")


def observe(live_store: LiveStore, *, offset_s: float = 0.0) -> None:
    live_store.apply(make_batch(make_update(offset_s=offset_s), offset_s=offset_s))


def test_a_new_aircraft_starts_live(live_store: LiveStore) -> None:
    observe(live_store)

    aircraft = live_store.get(ICAO)

    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE


def test_an_aircraft_is_still_live_just_short_of_the_stale_threshold(
    live_store: LiveStore, clock: ManualClock
) -> None:
    observe(live_store)
    clock.advance(live_store.stale_s - 0.000_001)

    live_store.sweep()

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE


def test_an_aircraft_goes_stale_exactly_on_the_threshold(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    observe(live_store)
    clock.advance(live_store.stale_s)

    live_store.sweep()

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.STALE
    assert aircraft.is_stale is True
    assert [type(event) for event in events.drain()[1:]] == [AircraftStale]


def test_a_stale_aircraft_stays_in_the_live_set_with_its_track(
    live_store: LiveStore, clock: ManualClock
) -> None:
    live_store.apply_updates([make_update(position=None)])
    clock.advance(live_store.stale_s)
    live_store.sweep()

    assert ICAO in live_store
    assert len(live_store) == 1


def test_staleness_fires_once_until_the_aircraft_is_heard_again(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    observe(live_store)
    clock.advance(live_store.stale_s)
    live_store.sweep()
    clock.advance(1.0)
    live_store.sweep()
    clock.advance(1.0)
    live_store.sweep()

    stale_events = [event for event in events.drain() if isinstance(event, AircraftStale)]

    assert len(stale_events) == 1


def test_an_update_clears_staleness_and_restarts_the_clock(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    observe(live_store)
    clock.advance(live_store.stale_s)
    live_store.sweep()

    clock.advance(1.0)
    observe(live_store, offset_s=16.0)

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE
    # The lifecycle transition is reported as a changed field, so a consumer
    # sees the aircraft come back without diffing snapshots itself.
    updates = [event for event in events.drain() if isinstance(event, AircraftUpdated)]
    assert "state" in updates[-1].changed


def test_staleness_can_fire_again_after_a_refresh(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    observe(live_store)
    clock.advance(live_store.stale_s)
    live_store.sweep()
    clock.advance(1.0)
    observe(live_store, offset_s=16.0)
    clock.advance(live_store.stale_s)
    live_store.sweep()

    stale_events = [event for event in events.drain() if isinstance(event, AircraftStale)]

    assert len(stale_events) == 2


def test_an_aircraft_is_still_live_just_short_of_the_removal_threshold(
    live_store: LiveStore, clock: ManualClock
) -> None:
    observe(live_store)
    clock.advance(live_store.remove_s - 0.000_001)

    live_store.sweep()

    assert ICAO in live_store


def test_an_aircraft_is_removed_exactly_on_the_removal_threshold(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    observe(live_store)
    clock.advance(live_store.stale_s)
    live_store.sweep()
    clock.advance(live_store.remove_s - live_store.stale_s)

    counts = live_store.sweep()

    assert live_store.get(ICAO) is None
    assert ICAO not in live_store
    assert counts.total == 0
    removals = [event for event in events.drain() if isinstance(event, AircraftRemoved)]
    assert len(removals) == 1
    assert removals[0].icao == ICAO


def test_removal_carries_the_last_record_and_its_track(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    # This event is slice 009's only chance to persist the track: the store
    # keeps no reference afterwards.
    live_store.apply_updates([make_update(position=Position(latitude=47.0, longitude=-122.0))])
    clock.advance(live_store.remove_s)
    live_store.sweep()

    removal = next(event for event in events.drain() if isinstance(event, AircraftRemoved))

    assert removal.aircraft.callsign is None
    assert len(removal.aircraft.track) == 1
    assert removal.at == removal.aircraft.last_seen


def test_crossing_both_thresholds_between_sweeps_removes_without_a_stale_event(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    # A delayed sweep must state the truth — the aircraft is gone — rather than
    # manufacture a staleness transition that never had an observable moment.
    observe(live_store)
    clock.advance(live_store.remove_s)

    live_store.sweep()

    kinds = [type(event) for event in events.drain()[1:]]
    assert kinds == [AircraftRemoved]


def test_a_removed_aircraft_heard_again_re_enters_the_live_set(
    live_store: LiveStore, clock: ManualClock
) -> None:
    observe(live_store)
    clock.advance(live_store.remove_s)
    live_store.sweep()

    clock.advance(1.0)
    observe(live_store, offset_s=61.0)

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.observations == 1


def test_only_silent_aircraft_expire(live_store: LiveStore, clock: ManualClock) -> None:
    live_store.apply_updates([make_update("ae1463"), make_update("4ca7b3")])
    for step in range(1, 8):
        clock.advance(10.0)
        live_store.apply_updates([make_update("4ca7b3", offset_s=step * 10.0)])
        live_store.sweep()

    assert live_store.get("ae1463") is None
    assert live_store.get("4ca7b3") is not None


# -------------------------------------------------- decoder retention windows


def poll_ghost(live_store: LiveStore, *, seen_s: float) -> None:
    """Re-deliver an entry the decoder is still listing but no longer hearing.

    Its ``last_seen`` never moves — offset zero — while the age the decoder
    reports grows with every poll. That is exactly what ``aircraft.json``
    carries for the five minutes dump1090-fa retains a dead aircraft.
    """
    live_store.apply(make_batch(make_update(seen_s=seen_s)))


def test_a_ghost_the_decoder_keeps_listing_ages_out_on_the_documented_thresholds(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    # Issue #134: the poller re-delivers every entry every second, so before
    # the aircraft was aged by the decoder's own report its silence clock
    # restarted on every poll and it survived the whole retention window.
    poll_ghost(live_store, seen_s=0.0)

    went_stale_at: int | None = None
    removed_at: int | None = None
    for second in range(1, 91):
        clock.advance(1.0)
        poll_ghost(live_store, seen_s=float(second))
        live_store.sweep()
        aircraft = live_store.get(ICAO)
        if aircraft is None:
            removed_at = second
            break
        if aircraft.state is LiveState.STALE and went_stale_at is None:
            went_stale_at = second

    assert went_stale_at == 15
    assert removed_at == 60

    removals = [event for event in events.drain() if isinstance(event, AircraftRemoved)]
    assert len(removals) == 1
    assert removals[0].aircraft.icao == ICAO
    # The record is dated at the aircraft's last transmission, not at the last
    # poll that mentioned it, so a consumer measuring from it gets the truth.
    assert removals[0].aircraft.last_seen == BASE_TIME


def test_a_ghost_that_is_still_listed_never_flickers_back_to_live(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    poll_ghost(live_store, seen_s=0.0)
    for second in range(1, 50):
        clock.advance(1.0)
        poll_ghost(live_store, seen_s=float(second))
        live_store.sweep()

    stale_events = [event for event in events.drain() if isinstance(event, AircraftStale)]
    assert len(stale_events) == 1


def test_an_aircraft_the_decoder_is_still_hearing_never_expires(
    live_store: LiveStore, clock: ManualClock
) -> None:
    # The other half of the contract: a real 1 Hz observation stream reports a
    # sub-second age, which must keep the aircraft live indefinitely.
    for second in range(120):
        clock.advance(1.0)
        live_store.apply(make_batch(make_update(offset_s=float(second), seen_s=0.4)))
        live_store.sweep()

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE


def test_an_aircraft_heard_again_after_a_gap_comes_back_live(
    live_store: LiveStore, clock: ManualClock
) -> None:
    poll_ghost(live_store, seen_s=0.0)
    for second in range(1, 21):
        clock.advance(1.0)
        poll_ghost(live_store, seen_s=float(second))
        live_store.sweep()
    silent = live_store.get(ICAO)
    assert silent is not None
    assert silent.state is LiveState.STALE

    clock.advance(1.0)
    live_store.apply(make_batch(make_update(offset_s=21.0, seen_s=0.2)))

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE


def test_an_entry_the_decoder_reports_as_already_expired_is_never_admitted(
    live_store: LiveStore, events: EventSubscription
) -> None:
    # Restarting FlightSite against a running decoder hands the store the whole
    # retention window at once. An entry the decoder itself places outside the
    # live window is turned away: no record, and nothing announced about an
    # aircraft that was never live.
    poll_ghost(live_store, seen_s=282.0)

    assert ICAO not in live_store
    assert len(live_store) == 0
    assert events.drain() == ()


def test_an_entry_first_heard_inside_the_removal_window_is_admitted(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    # The refusal is drawn at remove_s, not at stale_s: 40 s of silence is
    # still inside the window the live set is defined by, so the aircraft is
    # admitted and then ages out on the ordinary schedule.
    poll_ghost(live_store, seen_s=40.0)

    admitted = live_store.get(ICAO)
    assert admitted is not None
    assert admitted.state is LiveState.LIVE

    live_store.sweep()
    swept = live_store.get(ICAO)
    assert swept is not None
    assert swept.state is LiveState.STALE

    clock.advance(21.0)
    live_store.sweep()

    assert ICAO not in live_store
    kinds = [type(event) for event in events.drain()]
    assert kinds == [AircraftAppeared, AircraftStale, AircraftRemoved]


def test_a_removed_ghost_is_not_re_admitted_by_the_polls_that_follow(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    # The regression this guards: the store removes the ghost at 60 s, the
    # decoder keeps listing it for minutes more, and every following poll used
    # to re-admit it for the next sweep to remove again — an appear/remove pair
    # per second, per ghost, for the rest of the retention window.
    poll_ghost(live_store, seen_s=0.0)
    for second in range(1, 73):
        clock.advance(1.0)
        poll_ghost(live_store, seen_s=float(second))
        live_store.sweep()

    assert ICAO not in live_store
    kinds = [type(event) for event in events.drain()]
    assert kinds.count(AircraftAppeared) == 1
    assert kinds.count(AircraftRemoved) == 1


def test_a_removed_aircraft_the_decoder_genuinely_hears_again_is_re_admitted(
    live_store: LiveStore, clock: ManualClock, events: EventSubscription
) -> None:
    # The refusal turns away re-listings, not re-acquisitions: once the decoder
    # reports a fresh age the aircraft is live again, appearing for a second
    # time exactly as a first-time contact would.
    poll_ghost(live_store, seen_s=0.0)
    for second in range(1, 73):
        clock.advance(1.0)
        poll_ghost(live_store, seen_s=float(second))
        live_store.sweep()
    assert ICAO not in live_store

    clock.advance(1.0)
    live_store.apply(make_batch(make_update(offset_s=73.0, seen_s=0.3)))

    aircraft = live_store.get(ICAO)
    assert aircraft is not None
    assert aircraft.state is LiveState.LIVE
    appearances = [event for event in events.drain() if isinstance(event, AircraftAppeared)]
    assert len(appearances) == 2


def test_the_live_count_is_the_audible_count_at_every_sampling_phase(
    live_store: LiveStore, clock: ManualClock
) -> None:
    # What the owner actually sees. One aircraft the decoder keeps hearing, one
    # it stopped hearing at second zero but keeps listing. The total must not
    # depend on whether the count is read just after a poll or just after a
    # sweep — the oscillation that reading gave while removals were undone.
    audible, ghost = "4ca7b3", ICAO
    after_poll: list[int] = []
    after_sweep: list[int] = []
    for second in range(1, 121):
        clock.advance(1.0)
        live_store.apply_updates(
            [
                make_update(audible, offset_s=float(second), seen_s=0.4),
                make_update(ghost, seen_s=float(second)),
            ]
        )
        after_poll.append(live_store.counts().total)
        live_store.sweep()
        after_sweep.append(live_store.counts().total)

    # Both aircraft count while the ghost's silence is under remove_s; the
    # sweep drops it at second 60 and no later poll brings it back. The one
    # second of overlap is the documented sweep-interval lag, not a bug.
    assert after_poll == [2] * 60 + [1] * 60
    assert after_sweep == [2] * 59 + [1] * 61


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"stale_s": 0.0}, "stale_s must be greater than zero"),
        ({"stale_s": 60.0, "remove_s": 60.0}, "remove_s must exceed stale_s"),
        ({"remove_s": 5.0}, "remove_s must exceed stale_s"),
        ({"sweep_interval_s": 0.0}, "sweep_interval_s must be greater than zero"),
    ],
)
def test_incoherent_thresholds_are_rejected(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        LiveStore(**kwargs)
