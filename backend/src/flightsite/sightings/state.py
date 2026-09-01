"""The in-memory accumulator for one open sighting.

A sighting is written to SQLite a handful of times over its life, not once per
decoder update. At 1 Hz across a few hundred aircraft, a write per update would
be tens of thousands of transactions an hour on an SD card, for a row whose
final content is a dozen extremes — so the running values live here, in memory,
and reach the database on the flush policy
:mod:`flightsite.sightings.worker` applies (periodically, on a flight-context
change, and at close).

Everything folded in here comes from a
:class:`~flightsite.live.aircraft.LiveAircraft` record carried on a live event.
:meth:`ActiveSighting.observe` is therefore pure in-memory arithmetic with no
database access and no clock of its own: the only instant it uses is the
record's own ``last_seen``, which is the decoder's UTC timestamp for the
observation (SPEC §15).

Extremes carry the moment they were set. ``closest_approach_nm`` without
``closest_approach_ms`` would let the UI say how close an aircraft came but not
when, and the lifetime records on ``aircraft`` need both.
"""

from __future__ import annotations

from dataclasses import dataclass

from flightsite.db.clock import to_epoch_ms
from flightsite.live import GroundState, LiveAircraft
from flightsite.sightings.vocabulary import EMERGENCY_SQUAWKS


@dataclass(slots=True)
class ActiveSighting:
    """Running state of one sighting that has not been closed yet.

    Mutable by design — it is the worker's private per-aircraft scratch space,
    never shared with the live store or handed to a caller.

    ``sighting_id`` and ``aircraft_id`` are ``None`` until the row has actually
    been committed, and the worker sets them only after its transaction
    succeeds. A failed cycle therefore leaves an accumulator that still knows
    it needs inserting, rather than one holding the id of a row that was rolled
    back.
    """

    icao: str
    started_ms: int
    last_seen_ms: int

    aircraft_id: int | None = None
    sighting_id: int | None = None

    #: True when the aircraft is new to the database as well as to this
    #: sighting. Set by the repository at open; used only for logging.
    first_ever: bool = False

    callsign_first: str | None = None
    callsign_last: str | None = None
    squawk_last: str | None = None
    had_emergency: bool = False

    any_position: bool = False
    mlat_used: bool = False
    ground_seen: bool = False

    closest_approach_nm: float | None = None
    closest_approach_ms: int | None = None
    max_range_nm: float | None = None
    max_range_ms: int | None = None
    lowest_alt_ft: int | None = None
    lowest_alt_ms: int | None = None
    highest_alt_ft: int | None = None
    highest_alt_ms: int | None = None

    #: Unwritten changes are pending.
    dirty: bool = True
    #: A flight-context change happened; flush at the next cycle rather than
    #: waiting out the interval.
    flush_immediately: bool = False
    #: Worker-clock reading of the last successful flush, or ``None`` if the
    #: row has never been written.
    last_flush_ms: int | None = None
    #: Epoch-ms instant at which this sighting closes if the aircraft is not
    #: heard again. Set when the aircraft leaves the live set; cleared when it
    #: comes back. ``None`` means the aircraft is currently live.
    close_deadline_ms: int | None = None

    @property
    def duration_ms(self) -> int:
        """Observed length so far: last observation minus the first.

        Never negative: a rehydrated sighting whose stored ``started_ms``
        somehow post-dates its last known observation yields zero rather than
        a duration that would corrupt the airframe's cumulative total.
        """
        return max(0, self.last_seen_ms - self.started_ms)

    def observe(self, record: LiveAircraft) -> None:
        """Fold one live record into the running state.

        Idempotent for extremes (they are minima and maxima) and monotonic for
        ``last_seen_ms``, so replaying an event — which the overflow resync
        path does — cannot move a value backwards.
        """
        at_ms = to_epoch_ms(record.last_seen)
        if at_ms > self.last_seen_ms:
            self.last_seen_ms = at_ms

        self._observe_flight_context(record)
        self._observe_position_character(record)
        self._observe_extremes(record, at_ms)
        self.dirty = True

    def _observe_flight_context(self, record: LiveAircraft) -> None:
        """Track callsign, squawk and the emergency record (SPEC §17)."""
        callsign = record.callsign
        if callsign is not None and callsign != self.callsign_last:
            if self.callsign_first is None:
                self.callsign_first = callsign
            self.callsign_last = callsign
            # A callsign change is one of the transitions slice 052 records as
            # a sighting event; until then it is at least a reason to write
            # rather than sit on the change for the rest of the flush interval.
            self.flush_immediately = True

        squawk = record.squawk
        if squawk is not None and squawk != self.squawk_last:
            self.squawk_last = squawk
            self.flush_immediately = True
        if squawk in EMERGENCY_SQUAWKS and not self.had_emergency:
            self.had_emergency = True
            self.flush_immediately = True

    def _observe_position_character(self, record: LiveAircraft) -> None:
        """Record what *kind* of observation this sighting has contained.

        All three are latching: an aircraft that reported one MLAT position and
        then a hundred ADS-B ones was still MLAT-tracked at some point, and a
        sighting that touched the ground stays a ground sighting (SPEC §36).
        """
        if record.has_position:
            self.any_position = True
        if record.position_source == "mlat":
            self.mlat_used = True
        if record.ground_state is GroundState.ON_GROUND:
            self.ground_seen = True

    def _observe_extremes(self, record: LiveAircraft, at_ms: int) -> None:
        """Update the per-sighting range and altitude extremes (SPEC §57).

        Distance comes straight off the live record, which has already derived
        it from the receiver location — the worker does no geometry of its own.
        An unconfigured receiver simply means no range extremes, exactly as the
        live record has no ``distance_nm``.
        """
        distance_nm = record.distance_nm
        if distance_nm is not None:
            if self.closest_approach_nm is None or distance_nm < self.closest_approach_nm:
                self.closest_approach_nm = distance_nm
                self.closest_approach_ms = at_ms
            if self.max_range_nm is None or distance_nm > self.max_range_nm:
                self.max_range_nm = distance_nm
                self.max_range_ms = at_ms

        # Barometric altitude is the aviation figure and the one both supported
        # decoders report; geometric altitude is a different measurement and is
        # not mixed into these records.
        if record.altitude_ft is not None:
            altitude_ft = round(record.altitude_ft)
            if self.lowest_alt_ft is None or altitude_ft < self.lowest_alt_ft:
                self.lowest_alt_ft = altitude_ft
                self.lowest_alt_ms = at_ms
            if self.highest_alt_ft is None or altitude_ft > self.highest_alt_ft:
                self.highest_alt_ft = altitude_ft
                self.highest_alt_ms = at_ms

    def needs_flush(self, now_ms: int, interval_ms: int, *, force: bool = False) -> bool:
        """Whether the row should be written this cycle.

        Clean state is never written. Otherwise: immediately after a
        flight-context change, immediately when ``force`` (shutdown), and
        otherwise once the flush interval has elapsed since the last write.
        """
        if not self.dirty:
            return False
        if force or self.flush_immediately or self.last_flush_ms is None:
            return True
        return now_ms - self.last_flush_ms >= interval_ms

    def mark_flushed(self, now_ms: int) -> None:
        """Record that the running state reached the database at ``now_ms``."""
        self.dirty = False
        self.flush_immediately = False
        self.last_flush_ms = now_ms


def open_from(record: LiveAircraft) -> ActiveSighting:
    """Start a new accumulator from an aircraft's first live record.

    ``started_ms`` is the aircraft's ``first_seen`` in the *live* store — the
    moment this entry into the live set began — not the airframe's first-ever
    appearance, which lives on the ``aircraft`` row.
    """
    sighting = ActiveSighting(
        icao=record.icao,
        started_ms=to_epoch_ms(record.first_seen),
        last_seen_ms=to_epoch_ms(record.first_seen),
    )
    sighting.observe(record)
    return sighting


__all__ = ["ActiveSighting", "open_from"]
