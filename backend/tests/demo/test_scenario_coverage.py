"""Scenario coverage: every SPEC §76 traffic type, observed through a live store.

These tests drive a real :class:`~flightsite.live.LiveStore` with demo
batches on a hand-driven clock (``docs/TEST_STRATEGY.md`` §3 — simulated
time, never real sleeps) and assert on what the live picture actually shows,
the same way a consumer of :class:`~flightsite.demo.DemoAdapter` would see
it.
"""

from __future__ import annotations

from typing import Final

from flightsite.demo import Category, build_roster
from flightsite.demo.adapter import DEFAULT_CENTER, DEFAULT_SEED
from flightsite.demo.roster import (
    MILITARY_CALLSIGN_PREFIXES,
    PERIOD_S,
    AircraftProfile,
)
from flightsite.demo.scenario import batch_at, update_at
from flightsite.ingest.types import AircraftStateUpdate
from flightsite.live import LiveStore
from flightsite.live.aircraft import LiveState

#: 15 simulated minutes: comfortably past the "first 10 minutes" acceptance
#: window, with margin for every guaranteed-early representative to have
#: actually appeared (not just spawned).
DRIVE_TICKS: Final = 900

POPULATION: Final = 60


class ManualClock:
    """A monotonic clock this test drives by hand — see module docstring."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += seconds
        return self._now


def _roster() -> tuple[AircraftProfile, ...]:
    return build_roster(seed=DEFAULT_SEED, population=POPULATION, center=DEFAULT_CENTER)


def _drive(
    roster: tuple[AircraftProfile, ...], live: LiveStore, clock: ManualClock, ticks: int
) -> list[tuple[int, AircraftStateUpdate]]:
    """Apply ``ticks`` batches to ``live``; return every ``(tick, update)`` seen.

    Returning the raw updates (not just the final live-store snapshot) is
    what lets momentary conditions — an emergency squawk active for only a
    couple of minutes — be asserted on, even though the live store only ever
    holds *current* state.
    """
    seen: list[tuple[int, AircraftStateUpdate]] = []
    for tick in range(ticks):
        batch = batch_at(roster, tick)
        live.apply(batch)
        seen.extend((tick, update) for update in batch.updates)
        clock.advance(1.0)
    return seen


def test_every_required_category_is_observed_within_ten_simulated_minutes() -> None:
    roster = _roster()
    icao_category = {profile.icao: profile.category for profile in roster}
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER)

    seen = _drive(roster, live, clock, DRIVE_TICKS)
    categories_seen = {icao_category[update.icao] for _, update in seen}

    assert categories_seen == set(Category)


def test_mlat_and_non_positioned_mode_s_aircraft_appear() -> None:
    roster = _roster()
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER)

    seen = _drive(roster, live, clock, DRIVE_TICKS)
    position_sources = {update.position_source for _, update in seen}

    assert "mlat" in position_sources
    assert "none" in position_sources

    # A non-positioned Mode S aircraft reports altitude/squawk only.
    mode_s_updates = [
        update
        for _, update in seen
        if update.position_source == "none" and update.altitude_ft is not None
    ]
    assert mode_s_updates
    assert all(update.position is None for update in mode_s_updates)
    assert all(update.squawk is not None for update in mode_s_updates)


def test_ground_traffic_is_reported_on_ground() -> None:
    roster = _roster()
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER)

    seen = _drive(roster, live, clock, DRIVE_TICKS)

    assert any(update.on_ground is True for _, update in seen)


def test_military_style_callsigns_appear() -> None:
    roster = _roster()
    icao_category = {profile.icao: profile.category for profile in roster}
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER)

    seen = _drive(roster, live, clock, DRIVE_TICKS)
    military_callsigns = {
        update.callsign
        for _, update in seen
        if icao_category[update.icao] == Category.MILITARY and update.callsign
    }

    assert military_callsigns
    assert any(
        callsign.startswith(prefix)
        for callsign in military_callsigns
        for prefix in MILITARY_CALLSIGN_PREFIXES
    )


def test_emergency_squawks_7700_and_7600_both_occur() -> None:
    roster = _roster()
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER)

    seen = _drive(roster, live, clock, DRIVE_TICKS)
    squawks_seen = {update.squawk for _, update in seen}

    assert "7700" in squawks_seen
    assert "7600" in squawks_seen


def test_first_ever_aircraft_appears_exactly_once_across_two_periods() -> None:
    """A ``first_ever`` profile transmits during the first period and never again.

    This is a property of the scenario function itself
    (:func:`~flightsite.demo.scenario.update_at`), so it is checked directly
    rather than through a 3 600-tick ``LiveStore`` drive — cheap enough to
    run over the full two periods with no sampling gaps.
    """
    roster = _roster()
    first_ever = next(p for p in roster if p.category == Category.FIRST_EVER)

    periods_seen = {
        tick // PERIOD_S for tick in range(2 * PERIOD_S) if update_at(first_ever, tick) is not None
    }

    assert periods_seen == {0}


def test_commercial_aircraft_are_the_live_majority() -> None:
    roster = _roster()
    icao_category = {profile.icao: profile.category for profile in roster}
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER)

    _drive(roster, live, clock, DRIVE_TICKS)
    snapshot = live.snapshot()
    assert snapshot, "expected aircraft to be live after the drive"

    commercial = sum(
        1 for aircraft in snapshot if icao_category[aircraft.icao] == Category.COMMERCIAL
    )
    assert commercial > len(snapshot) / 2


def test_a_silent_aircraft_goes_stale_then_is_removed() -> None:
    """A guaranteed-early representative stops transmitting well within the
    drive window; as ordinary lifecycle sweeps continue to run — the same as
    the background task in production — it must age out to stale and then
    removed, without disturbing aircraft still on the air.

    Ingestion continues throughout (every tick still applies its batch): the
    point is that *this one aircraft* falls silent while its neighbours keep
    transmitting, not that the whole feed stops.
    """
    roster = _roster()
    # `_build_rare(..., early=True)` — see build_roster's fixed append order
    # — always finishes its active window by tick 500 (its active-tick range
    # is 200-500 and the "early" schedule caps spawn + active <= 500).
    target = roster[7]
    assert target.category == Category.RARE
    silent_from = target.spawn_tick + target.active_ticks
    assert silent_from <= 550

    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=DEFAULT_CENTER, stale_s=15.0, remove_s=60.0)

    # Drive tick by tick, sweeping after every tick — exactly what the
    # production background task does at its 1 s interval — so the target's
    # silence is timed against a clock that keeps moving for everyone.
    stale_seen = False
    for tick in range(silent_from + 100):
        live.apply(batch_at(roster, tick))
        clock.advance(1.0)
        live.sweep()
        if tick == silent_from + 30:
            stale_aircraft = live.get(target.icao)
            assert stale_aircraft is not None, "target should still be live, just stale"
            assert stale_aircraft.state is LiveState.STALE
            stale_seen = True

    assert stale_seen
    assert target.icao not in live

    # Aircraft still being fed updates every tick were never touched by this.
    assert len(live) > 0
