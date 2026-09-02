"""The live record for one aircraft, and the rules that build it.

A :class:`LiveAircraft` is the accumulated view of one ICAO address: the most
recent value of every field any decoder update has reported, plus the fields
FlightSite derives from them, plus the timing a lifecycle decision needs. It is
immutable — every merge produces a new record — so a snapshot handed to a REST
handler, the WebSocket broadcaster or a queued event can never be mutated
underneath its reader. The one deliberately mutable thing a record references
is its :class:`~flightsite.live.track.CurrentTrack`, which is append-only and
shared across successive records of the same aircraft.

Merge semantics
---------------

Decoders report sparsely: a poll may carry a position and nothing else, or a
callsign and nothing else. A ``None`` in an update therefore means "not
reported this time", never "no longer known", so a partial update never erases
a field the live record already holds (SPEC §39 — FlightSite does not
fabricate, and it does not forget either). Three consequences worth naming:

* **Position is sticky.** An aircraft that drops to Mode S-only keeps its last
  known position and that position's ``position_source``; ``position_seen``
  records when it was last actually reported, so a consumer can age it. A
  non-positioned aircraft that has *never* reported one has ``position: None``
  and ``position_source: "none"`` — a first-class live entry (SPEC §20).
* **Identity fields carry their own timestamps.** ``callsign_seen`` and
  ``squawk_seen`` are separate from ``position_seen`` and from ``last_seen``,
  because "when did this aircraft last transmit a callsign" is a different
  question from "when did we last hear it at all", and slice 009's flight
  context needs the former.
* **One exception, and it is the decoder's own statement.** When a decoder
  reports the aircraft as on the ground it is not omitting barometric altitude,
  it is saying there is none to report (readsb and dump1090-fa both encode this
  as the ``"ground"`` altitude sentinel, which the adapter normalizes to
  ``on_ground=True`` with no altitude). That update clears ``altitude_ft``
  rather than leaving a stale cruise level attached to a parked aircraft.

Observation age
---------------

A poll is not an observation. Both supported decoders retain an aircraft in
their output for minutes after they last heard it, re-listing the entry — with
a growing reported age — on every poll, so "this entry was in the document we
just fetched" says nothing about when the aircraft last transmitted. The
decoder answers that itself: ``seen_s`` is how long ago it last heard anything
from this aircraft, and ``seen_pos_s`` how long ago it last decoded a position.

:func:`appear` and :func:`merge` therefore date every observation ``seen_s``
seconds *before* the clock reading they are handed, rather than at it. Without
that, a silent aircraft's clock restarted on every poll and it could never age
past one polling interval while the decoder still listed it — the live set
carried the decoder's whole retention window instead of what is actually
audible, and the store's stale and removal sweeps fired minutes late (issue
#134).

This preserves the store's monotonic-only discipline (see
:mod:`flightsite.live.store`): ``seen_s`` is a *relative* age reported by the
decoder, not a wall-clock instant read from a machine whose clock may jump.
Subtracting it from the injected monotonic reading yields a monotonic instant.

The wall-clock companions are aged the same way and by the same amount: the
ingest adapter already dates ``update.timestamp`` at ``reference minus
seen_s``. The two are not derived from the same instant, though —
``update.timestamp`` counts back from the fetch, ``observed_at`` from a clock
read after parsing — so expect a small, consistent sub-second offset between a
record's wall-clock and monotonic views of the same observation. Nothing in
this codebase compares them across that boundary, and no threshold here is
fine-grained enough to care.

Provenance
----------

``docs/API.md`` §2.6 and ``docs/DATA_MODEL.md`` §8: fields without a
:attr:`LiveAircraft.provenance` entry are decoder-direct. Entries appear for
exactly the values this layer computes or decides — ``distance_nm``,
``bearing_deg`` and ``ground_state`` — so a consumer never has to guess whether
a number came off the wire or out of a formula.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from flightsite.ingest import AircraftStateUpdate, Position, PositionSource
from flightsite.live.geo import distance_and_bearing
from flightsite.live.track import DEFAULT_TRACK_CAPACITY, CurrentTrack, TrackPoint


class LiveState(StrEnum):
    """Lifecycle position within the live set (``docs/API.md`` §3.3 ``state``).

    Removal is not a state: an aircraft past the removal threshold is gone from
    the live set entirely, announced by
    :class:`~flightsite.live.events.AircraftRemoved`.
    """

    LIVE = "live"
    STALE = "stale"


class GroundState(StrEnum):
    """Airborne / on-ground determination, decoder-preferred.

    ``unknown`` is a real, common and acceptable answer (``docs/API.md`` §2.7):
    FlightSite states what it knows rather than guessing.
    """

    AIRBORNE = "airborne"
    ON_GROUND = "on_ground"
    UNKNOWN = "unknown"


class Provenance(StrEnum):
    """Where a live field's value came from (``docs/API.md`` §2.8).

    The live store produces only these two of the canonical provenance values;
    the enrichment sources (``mictronics``, ``faa``, ``aerodatabox``,
    ``heuristic``) belong to later slices and to other layers.
    """

    DECODER = "decoder"
    DERIVED = "derived"


#: Barometric altitude at or above which an aircraft is certainly airborne.
#:
#: This is the *only* ground-state inference FlightSite makes, and it is
#: deliberately one-directional. Above FL180 no aircraft is on a runway
#: anywhere on Earth — the world's highest airport (Daocheng Yading) sits near
#: 14 500 ft, so 18 000 ft clears every field on the planet by thousands of
#: feet even before allowing for altimeter setting.
#:
#: The reverse inference — "slow and low, therefore on the ground" — is *not*
#: attempted. Deciding that requires knowing the terrain or field elevation
#: beneath the aircraft, and FlightSite has no airport or elevation dataset
#: until slice 027; without it, a helicopter at 300 ft AGL over a valley and an
#: airliner taxiing at a mile-high airport are indistinguishable from altitude
#: and ground speed alone. Calling either one wrongly would be a safety-
#: relevant display error, so the answer stays :attr:`GroundState.UNKNOWN`
#: unless the decoder itself states otherwise — which in practice it usually
#: does, since both supported decoders report the ground sentinel directly.
AIRBORNE_INFERENCE_ALTITUDE_FT: Final = 18_000.0

#: Fields compared between successive records to build the changed-field hints
#: on :class:`~flightsite.live.events.AircraftUpdated`.
#:
#: The per-observation bookkeeping (``last_seen``, ``seen_s``, ``seen_pos_s``)
#: is excluded on purpose: those change on literally every poll, so including
#: them would make the hint set constant and therefore useless for the
#: consumers it exists for (flight-context changes in slice 009, alert
#: re-evaluation in slice 038).
CHANGE_TRACKED_FIELDS: Final[tuple[str, ...]] = (
    "state",
    "callsign",
    "squawk",
    "position",
    "position_source",
    "altitude_ft",
    "altitude_geometric_ft",
    "ground_speed_kt",
    "track_deg",
    "vertical_rate_fpm",
    "on_ground",
    "ground_state",
    "distance_nm",
    "bearing_deg",
    "rssi_db",
    "messages",
)

_NO_PROVENANCE: Final[MappingProxyType[str, Provenance]] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class LiveAircraft:
    """The current live view of one aircraft.

    Wall-clock instants (``first_seen``, ``last_seen``, ``position_seen``, ...)
    are the *decoder's* UTC timestamps, because the decoder is the authority on
    when an observation happened. The ``*_monotonic`` companions come from the
    store's injected monotonic clock and are what every lifecycle decision uses
    — a monotonic source cannot jump backwards when NTP corrects a Pi that
    booted without an RTC, which is exactly the failure a wall-clock timer
    would turn into a mass false expiry.

    :attr:`last_seen` is the value slice 009 needs for sighting closure (the
    600 s threshold is that slice's, not this one's).
    """

    icao: str

    first_seen: datetime
    last_seen: datetime
    first_seen_monotonic: float
    last_seen_monotonic: float
    state: LiveState
    #: The live, append-only position track. Deliberately the one mutable
    #: thing a record references: successive records of the same aircraft
    #: share it, and it is dropped when the aircraft leaves the live set.
    track: CurrentTrack

    position: Position | None = None
    position_source: PositionSource = "none"
    position_seen: datetime | None = None
    position_seen_monotonic: float | None = None

    callsign: str | None = None
    callsign_seen: datetime | None = None
    squawk: str | None = None
    squawk_seen: datetime | None = None

    altitude_ft: float | None = None
    altitude_geometric_ft: float | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    vertical_rate_fpm: float | None = None
    on_ground: bool | None = None
    ground_state: GroundState = GroundState.UNKNOWN

    rssi_db: float | None = None
    messages: int | None = None
    seen_s: float | None = None
    seen_pos_s: float | None = None

    distance_nm: float | None = None
    bearing_deg: float | None = None

    observations: int = 0
    provenance: MappingProxyType[str, Provenance] = _NO_PROVENANCE

    @property
    def has_position(self) -> bool:
        """True once a usable position has been reported at least once."""
        return self.position is not None

    @property
    def is_stale(self) -> bool:
        """True while the aircraft is past the stale threshold but still live."""
        return self.state is LiveState.STALE

    def age_s(self, now: float) -> float:
        """Seconds of monotonic time since the last observation of any kind."""
        return now - self.last_seen_monotonic

    def position_age_s(self, now: float) -> float | None:
        """Seconds since a position was last reported, or ``None`` if never."""
        if self.position_seen_monotonic is None:
            return None
        return now - self.position_seen_monotonic


def _ground_state(
    *, on_ground: bool | None, altitude_ft: float | None
) -> tuple[GroundState, Provenance | None]:
    """Resolve airborne/on-ground, preferring the decoder's own determination.

    Returns the state and the provenance to record for it, or ``None``
    provenance when nothing is known and the answer is ``unknown``.
    """
    if on_ground is not None:
        return (GroundState.ON_GROUND if on_ground else GroundState.AIRBORNE), Provenance.DECODER
    if altitude_ft is not None and altitude_ft >= AIRBORNE_INFERENCE_ALTITUDE_FT:
        return GroundState.AIRBORNE, Provenance.DERIVED
    return GroundState.UNKNOWN, None


def _provenance(
    *,
    ground: Provenance | None,
    has_range: bool,
) -> MappingProxyType[str, Provenance]:
    """Build the provenance map for the fields this layer decides."""
    entries: dict[str, Provenance] = {}
    if has_range:
        entries["distance_nm"] = Provenance.DERIVED
        entries["bearing_deg"] = Provenance.DERIVED
    if ground is not None:
        entries["ground_state"] = ground
    return MappingProxyType(entries) if entries else _NO_PROVENANCE


def _range_to(
    receiver: Position | None, position: Position | None
) -> tuple[float | None, float | None]:
    """Distance and bearing from the receiver, or ``(None, None)``.

    An unconfigured receiver location is the normal first-run state (the setup
    wizard collects it in slice 018), so it is answered with nulls rather than
    an error: the live picture is fully usable without a receiver position, it
    simply has no receiver-relative fields.
    """
    if receiver is None or position is None:
        return None, None
    return distance_and_bearing(receiver, position)


def reported_silence_s(update: AircraftStateUpdate) -> float:
    """How long ago the decoder says it last heard this aircraft, sanitized.

    The single sanitizing step every age-derived value in this module goes
    through, so none of them can disagree about what one update means.

    ``None`` means the source reports no age — a replayed fixture that never
    captured one, or a future adapter for a decoder that does not offer it —
    and the observation is then taken at face value, age zero. A negative age
    would date the observation in the future, which no clock reading may be,
    so it too reads as zero. Public because the store needs the same number to
    decide whether an observation is admissible at all.
    """
    age_s = update.seen_s
    if age_s is None or age_s <= 0.0:
        return 0.0
    return age_s


def _position_lag_s(update: AircraftStateUpdate) -> float:
    """How much older this update's position is than the update itself.

    Both decoders report ``seen_pos_s >= seen_s`` — a position cannot have been
    decoded more recently than the last message carrying it — so this is the
    non-negative gap between ``update.timestamp`` (already dated at
    ``reference minus seen_s`` by the adapter) and the moment the position was
    actually decoded. Zero whenever the decoder reports no separate position
    age, which leaves the position dated with the update.

    It measures the gap against the *sanitized* silence, so a nonsensical
    negative ``seen_s`` cannot inflate the position's age past its own report.
    """
    if update.seen_pos_s is None:
        return 0.0
    return max(update.seen_pos_s - reported_silence_s(update), 0.0)


def _track_point(update: AircraftStateUpdate, position: Position) -> TrackPoint:
    return TrackPoint(
        timestamp=update.timestamp,
        latitude=position.latitude,
        longitude=position.longitude,
        position_source=update.position_source,
        altitude_ft=update.altitude_ft,
        ground_speed_kt=update.ground_speed_kt,
        track_deg=update.track_deg,
    )


def appear(
    update: AircraftStateUpdate,
    *,
    now: float,
    receiver: Position | None = None,
    track_capacity: int = DEFAULT_TRACK_CAPACITY,
) -> LiveAircraft:
    """Build the first live record for an aircraft from its first observation.

    The record starts :attr:`LiveState.LIVE` even when the decoder reports it
    already long silent: an aircraft has to be in the live set before the sweep
    can age it out, and the sweep — the sole authority on the stale and removal
    thresholds — will do exactly that on its next pass, because the timing this
    record carries is the decoder's, not the poll's.
    """
    position = update.position
    ground_state, ground_provenance = _ground_state(
        on_ground=update.on_ground, altitude_ft=update.altitude_ft
    )
    distance, bearing = _range_to(receiver, position)

    track = CurrentTrack(track_capacity)
    if position is not None:
        track.append(_track_point(update, position))

    observed_at = now - reported_silence_s(update)
    position_lag_s = _position_lag_s(update)

    return LiveAircraft(
        icao=update.icao,
        first_seen=update.timestamp,
        last_seen=update.timestamp,
        first_seen_monotonic=observed_at,
        last_seen_monotonic=observed_at,
        state=LiveState.LIVE,
        position=position,
        position_source=update.position_source,
        position_seen=(
            update.timestamp - timedelta(seconds=position_lag_s) if position is not None else None
        ),
        position_seen_monotonic=observed_at - position_lag_s if position is not None else None,
        callsign=update.callsign,
        callsign_seen=update.timestamp if update.callsign is not None else None,
        squawk=update.squawk,
        squawk_seen=update.timestamp if update.squawk is not None else None,
        altitude_ft=update.altitude_ft,
        altitude_geometric_ft=update.altitude_geometric_ft,
        ground_speed_kt=update.ground_speed_kt,
        track_deg=update.track_deg,
        vertical_rate_fpm=update.vertical_rate_fpm,
        on_ground=update.on_ground,
        ground_state=ground_state,
        rssi_db=update.rssi_db,
        messages=update.messages,
        seen_s=update.seen_s,
        seen_pos_s=update.seen_pos_s,
        distance_nm=distance,
        bearing_deg=bearing,
        observations=1,
        provenance=_provenance(ground=ground_provenance, has_range=distance is not None),
        track=track,
    )


def merge(
    current: LiveAircraft,
    update: AircraftStateUpdate,
    *,
    now: float,
    stale_s: float,
    receiver: Position | None = None,
) -> tuple[LiveAircraft, frozenset[str]]:
    """Fold ``update`` into ``current``; return the new record and what changed.

    The returned record shares ``current``'s track object, to which this call
    has already appended the update's position if it carried a new one.

    ``stale_s`` is the store's configured stale threshold, and merging is the
    *only* place a record leaves :attr:`LiveState.STALE`: an aircraft heard
    again is live again, and the transition rides out on the resulting
    :class:`~flightsite.live.events.AircraftUpdated` as a changed ``state``.
    The reverse transition stays with the sweep, which owns it along with the
    :class:`~flightsite.live.events.AircraftStale` event that announces it, so
    an update never silently re-states an aircraft's lifecycle.

    What decides the revival is the *aged* observation, not the poll. A decoder
    that re-lists an aircraft it has not heard for two minutes is not evidence
    the aircraft is back, so such an update leaves the state alone; only an
    observation younger than ``stale_s`` brings a stale record back to life.
    The parameter is required rather than defaulted: a hard-coded 15 s would
    quietly disagree with a store the owner configured differently.
    """
    has_position = update.position is not None
    position = update.position if has_position else current.position
    position_source = update.position_source if has_position else current.position_source

    # A decoder that reports the aircraft on the ground is stating that there
    # is no barometric altitude, not omitting one — see the module docstring.
    altitude_ft = (
        None
        if update.on_ground is True
        else (update.altitude_ft if update.altitude_ft is not None else current.altitude_ft)
    )
    on_ground = update.on_ground if update.on_ground is not None else current.on_ground
    ground_state, ground_provenance = _ground_state(on_ground=on_ground, altitude_ft=altitude_ft)
    distance, bearing = _range_to(receiver, position)

    if has_position and position is not None:
        current.track.append(_track_point(update, position))

    silence_s = reported_silence_s(update)
    observed_at = now - silence_s
    position_lag_s = _position_lag_s(update)
    heard_recently = silence_s < stale_s

    merged = replace(
        current,
        last_seen=update.timestamp,
        last_seen_monotonic=observed_at,
        state=LiveState.LIVE if heard_recently else current.state,
        position=position,
        position_source=position_source,
        position_seen=(
            update.timestamp - timedelta(seconds=position_lag_s)
            if has_position
            else current.position_seen
        ),
        position_seen_monotonic=(
            observed_at - position_lag_s if has_position else current.position_seen_monotonic
        ),
        callsign=update.callsign if update.callsign is not None else current.callsign,
        callsign_seen=update.timestamp if update.callsign is not None else current.callsign_seen,
        squawk=update.squawk if update.squawk is not None else current.squawk,
        squawk_seen=update.timestamp if update.squawk is not None else current.squawk_seen,
        altitude_ft=altitude_ft,
        altitude_geometric_ft=(
            update.altitude_geometric_ft
            if update.altitude_geometric_ft is not None
            else current.altitude_geometric_ft
        ),
        ground_speed_kt=(
            update.ground_speed_kt
            if update.ground_speed_kt is not None
            else current.ground_speed_kt
        ),
        track_deg=update.track_deg if update.track_deg is not None else current.track_deg,
        vertical_rate_fpm=(
            update.vertical_rate_fpm
            if update.vertical_rate_fpm is not None
            else current.vertical_rate_fpm
        ),
        on_ground=on_ground,
        ground_state=ground_state,
        rssi_db=update.rssi_db if update.rssi_db is not None else current.rssi_db,
        messages=update.messages if update.messages is not None else current.messages,
        seen_s=update.seen_s,
        seen_pos_s=update.seen_pos_s if update.seen_pos_s is not None else current.seen_pos_s,
        distance_nm=distance,
        bearing_deg=bearing,
        observations=current.observations + 1,
        provenance=_provenance(ground=ground_provenance, has_range=distance is not None),
    )

    changed = frozenset(
        name for name in CHANGE_TRACKED_FIELDS if getattr(merged, name) != getattr(current, name)
    )
    return merged, changed


def mark_stale(current: LiveAircraft) -> LiveAircraft:
    """Return ``current`` moved into :attr:`LiveState.STALE`."""
    return replace(current, state=LiveState.STALE)


__all__ = [
    "AIRBORNE_INFERENCE_ALTITUDE_FT",
    "CHANGE_TRACKED_FIELDS",
    "GroundState",
    "LiveAircraft",
    "LiveState",
    "Provenance",
    "appear",
    "mark_stale",
    "merge",
    "reported_silence_s",
]
