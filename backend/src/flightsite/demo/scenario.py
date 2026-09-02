"""Turns a tick index into one decoder batch — the scenario's pure core.

:func:`batch_at` is the whole demo scenario: given a roster (built once from
a seed by :mod:`flightsite.demo.roster`) and a tick index, it computes every
active aircraft's state directly from elapsed time and returns a batch. No
mutable simulation state is threaded through — tick 4000 is computed exactly
the same way whether or not tick 3999 was ever asked for — which is what
makes :class:`~flightsite.demo.adapter.DemoAdapter` deterministic (roadmap
slice 011: "same seed + elapsed time => identical state").

One tick is one simulated second (the product's 1 Hz cadence). A profile is
"on the air" for ``[spawn_tick, spawn_tick + active_ticks)`` within each
:data:`~flightsite.demo.roster.PERIOD_S`-second period; outside that window it
simply produces no update for the tick, which is what lets the live store's
ordinary stale/remove lifecycle turn "stopped transmitting" into "goes stale,
then disappears" without this module knowing anything about that lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from flightsite.demo.motion import altitude_at, position_at
from flightsite.demo.roster import PERIOD_S, AircraftProfile
from flightsite.ingest.types import AircraftStateBatch, AircraftStateUpdate

#: Default reference instant a batch's timestamp is computed from
#: (``epoch + tick_index`` seconds). A demo scenario is defined purely in terms
#: of elapsed ticks, and the functions here are pure in ``(roster, tick_index,
#: epoch)`` — that is what makes two runs with the same seed and the same epoch
#: produce byte-identical update sequences (roadmap slice 011 acceptance
#: criterion), independent of when either run happened to start.
#:
#: It is a *default*, not the value a running demo stack uses.
#: :class:`~flightsite.demo.adapter.DemoAdapter` anchors to the wall clock
#: instead, because these timestamps become real stored data: they are what
#: :mod:`flightsite.live.aircraft` records as ``first_seen``/``last_seen`` and
#: what the sighting worker writes as ``started_ms``. Anchored here, every demo
#: sighting landed on 2026-01-01 while the analytics rollups, receiver metrics
#: and the ``today`` window all resolve against the real clock, so the Live Map
#: Today panel and the Analytics ``today`` preset read zero forever on a demo
#: install (issue #107). See :class:`~flightsite.demo.adapter.DemoAdapter`.
SCENARIO_EPOCH: Final = datetime(2026, 1, 1, tzinfo=UTC)


def _active_age_s(profile: AircraftProfile, tick_index: int) -> float | None:
    """Seconds since spawn if ``profile`` is transmitting at ``tick_index``, else ``None``."""
    loop, phase = divmod(tick_index, PERIOD_S)
    if profile.once and loop > 0:
        return None
    if profile.rare_loop_modulus > 1 and loop % profile.rare_loop_modulus != 0:
        return None
    if not (profile.spawn_tick <= phase < profile.spawn_tick + profile.active_ticks):
        return None
    return float(phase - profile.spawn_tick)


def _squawk_at(profile: AircraftProfile, age_s: float) -> str:
    event = profile.emergency
    if event is None:
        return profile.squawk
    event_end = event.start_offset_s + event.duration_s
    if event.start_offset_s <= age_s < event_end:
        return event.squawk
    return profile.squawk


def update_at(
    profile: AircraftProfile,
    tick_index: int,
    *,
    epoch: datetime = SCENARIO_EPOCH,
) -> AircraftStateUpdate | None:
    """The one observation ``profile`` produces at ``tick_index``, or ``None``.

    ``None`` means the aircraft is not transmitting this tick — either it has
    not spawned yet, has fallen silent, or (for ``rare``/``first_ever``
    profiles) this period is one it sits out entirely.

    ``epoch`` is the instant tick 0 is stamped at; see :data:`SCENARIO_EPOCH`.
    """
    age_s = _active_age_s(profile, tick_index)
    if age_s is None:
        return None

    timestamp = epoch + timedelta(seconds=tick_index)

    position = None
    track_deg = None
    ground_speed_kt = None
    if profile.start is not None:
        position, heading_now = position_at(
            profile.start,
            heading_deg=profile.heading_deg,
            speed_kt=profile.speed_kt,
            turn_rate_deg_s=profile.turn_rate_deg_s,
            age_s=age_s,
        )
        if profile.reports_speed_and_track:
            track_deg = heading_now
            ground_speed_kt = profile.speed_kt

    altitude_ft = None
    vertical_rate_fpm = None
    if profile.base_altitude_ft is not None:
        altitude_ft, vertical_rate_fpm = altitude_at(
            base_altitude_ft=profile.base_altitude_ft,
            climb_fpm=profile.climb_fpm,
            age_s=age_s,
            min_altitude_ft=profile.min_altitude_ft,
            max_altitude_ft=profile.max_altitude_ft,
        )

    return AircraftStateUpdate(
        icao=profile.icao,
        timestamp=timestamp,
        position_source=profile.position_source if position is not None else "none",
        callsign=profile.callsign,
        squawk=_squawk_at(profile, age_s),
        position=position,
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        track_deg=track_deg,
        vertical_rate_fpm=vertical_rate_fpm,
        on_ground=profile.on_ground,
        rssi_db=profile.rssi_db,
        messages=int(age_s) + 1,
        seen_s=0.0,
        seen_pos_s=0.0 if position is not None else None,
    )


def batch_at(
    roster: tuple[AircraftProfile, ...],
    tick_index: int,
    *,
    epoch: datetime = SCENARIO_EPOCH,
) -> AircraftStateBatch:
    """The full decoder batch at ``tick_index`` — one update per active aircraft.

    A pure function of ``(roster, tick_index, epoch)``; since ``roster`` is
    itself a pure function of the seed
    (:func:`flightsite.demo.roster.build_roster`), this is the
    ``(seed, tick_index, epoch) -> batch`` determinism the roadmap requires.
    ``epoch`` only shifts every timestamp by a constant: it changes *when* the
    scenario is said to have happened, never what happens in it.
    """
    if tick_index < 0:
        raise ValueError("tick_index must be non-negative")
    updates = tuple(
        update
        for profile in roster
        if (update := update_at(profile, tick_index, epoch=epoch)) is not None
    )
    timestamp = epoch + timedelta(seconds=tick_index)
    return AircraftStateBatch(timestamp=timestamp, updates=updates)


__all__ = ["SCENARIO_EPOCH", "batch_at", "update_at"]
