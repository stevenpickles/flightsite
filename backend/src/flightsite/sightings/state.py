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

What the accumulator holds of the track
---------------------------------------

Only the points that have not been checkpointed yet. The live store owns the
full-resolution track while the aircraft is in the live set, and
``sighting_track_checkpoints`` owns everything already written; keeping a third
copy of a whole flight per open sighting would multiply the resident cost of a
busy sky for no gain, since the close path reads the checkpoint rows back
anyway (ADR-0005: the checkpoint record is what a power cut leaves, and it is
also what close simplifies, together with this tail).

The tail is therefore bounded by one flush interval — roughly thirty points —
and :data:`MAX_PENDING_POINTS` is a backstop for the pathological case of a
writer that has been failing for hours, evicting oldest-first exactly as the
live track does.

Idempotence
-----------

The overflow resync path re-observes records the worker may already have
folded in, and a restart rehydrates from the row. Every value here is therefore
either a monotone extreme, a latching flag, or guarded by
:attr:`ActiveSighting.stats_ms` — the timestamp of the newest observation whose
*statistics* have been counted. Replaying an observation cannot move a value
backwards, count a message twice, or emit a second copy of an event.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, NamedTuple

from flightsite.db.clock import to_epoch_ms
from flightsite.live import GroundState, LiveAircraft
from flightsite.sightings.tracks import TrackSample, from_track_point, thin_for_checkpoint
from flightsite.sightings.vocabulary import EMERGENCY_SQUAWKS, ClosureReason, SightingEventType

#: Cap on un-checkpointed points held per sighting. Four hours at 1 Hz, the
#: same bound :data:`~flightsite.live.track.DEFAULT_TRACK_CAPACITY` puts on a
#: live track — reached only if the writer has been failing for that long, and
#: then losing the oldest points, which is the loss ADR-0005 already accepts
#: for a power cut.
MAX_PENDING_POINTS: Final = 14_400

#: Percent, for ``pos_time_pct``.
_PERCENT: Final = 100.0


class PendingEvent(NamedTuple):
    """A ``sighting_events`` row this accumulator has decided on but not written.

    Queued rather than written on the spot because the worker owns the
    transaction: the event lands in the same commit as the row whose change
    produced it, and a failed cycle leaves it queued for the next one, which is
    what makes "exactly once per change" survive a database error.
    """

    type: SightingEventType
    ts_ms: int
    payload: dict[str, str | None]

    @property
    def payload_json(self) -> str:
        """The payload as the compact JSON the column stores."""
        return json.dumps(self.payload, separators=(",", ":"), sort_keys=True)


class CheckpointBatch(NamedTuple):
    """One flush cycle's worth of checkpoint rows, and what producing them ate.

    ``consumed`` counts the pending points the batch covers — more than
    ``len(rows)`` whenever thinning dropped something. The two are separate
    because the accumulator must drop everything the batch covered, not merely
    what it wrote.
    """

    consumed: int
    rows: tuple[tuple[int, TrackSample], ...]

    @property
    def last(self) -> TrackSample:
        """The newest sample in the batch."""
        return self.rows[-1][1]


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
    #: Whether the *current* squawk is an emergency code, as distinct from
    #: :attr:`had_emergency`, which latches for the life of the sighting. This
    #: is what makes ``emergency_start`` fire once per episode rather than once
    #: per observation.
    emergency_active: bool = False

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

    #: Decoder messages attributed to this sighting (SPEC §51).
    msg_count: int = 0
    #: Position reports received during this sighting.
    pos_count: int = 0
    rssi_peak_db: float | None = None
    rssi_min_db: float | None = None
    #: Running sum and count behind ``rssi_avg_db``: a mean of every reported
    #: ``rssi_db``, kept incrementally so no sample has to be retained.
    rssi_total_db: float = 0.0
    rssi_samples: int = 0
    #: Milliseconds of the sighting during which positions were arriving.
    positioned_ms: int = 0
    #: The decoder's cumulative message counter as of the last observation,
    #: used to turn it into a per-sighting delta.
    messages_seen: int | None = None
    #: ``position_seen`` of the last observation, used to recognize a *new*
    #: position report rather than the sticky last-known one.
    last_position_at: datetime | None = None
    #: Timestamp of the newest observation folded into the statistics; the
    #: guard that makes a replayed event free of effect.
    stats_ms: int | None = None

    #: Track points harvested from the live track and not yet checkpointed.
    pending_points: deque[TrackSample] = field(
        default_factory=lambda: deque(maxlen=MAX_PENDING_POINTS)
    )
    #: Timestamp of the newest point harvested, in the live track's own clock.
    last_point_at: datetime | None = None
    #: ...and in storage's, so that millisecond collisions cannot produce the
    #: non-increasing timestamps the packed encoding refuses.
    last_point_ms: int | None = None
    #: Next ``seq`` to assign to a checkpoint row.
    checkpoint_seq: int = 0
    #: The last checkpointed sample, which keeps thinning continuous across
    #: batches instead of restarting the run at every flush.
    checkpoint_anchor: TrackSample | None = None

    #: Events decided but not yet written.
    pending_events: list[PendingEvent] = field(default_factory=list)

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
    #: Reason to record when this sighting closes. ``gap_timeout`` for the
    #: ordinary case — an absence the running process actually observed.
    #: Startup recovery sets ``shutdown_recovery`` on a sighting whose repair
    #: transaction failed, so the worker's retry records the honest reason
    #: rather than claiming to have watched a gap nobody was there for; an
    #: aircraft heard again before that retry resets it, because then the
    #: sighting is alive and any later closure is an observed one.
    closure_reason: ClosureReason = ClosureReason.GAP_TIMEOUT

    @property
    def duration_ms(self) -> int:
        """Observed length so far: last observation minus the first.

        Never negative: a rehydrated sighting whose stored ``started_ms``
        somehow post-dates its last known observation yields zero rather than
        a duration that would corrupt the airframe's cumulative total.
        """
        return max(0, self.last_seen_ms - self.started_ms)

    @property
    def rssi_avg_db(self) -> float | None:
        """Mean of every reported ``rssi_db``, or ``None`` if none were."""
        if not self.rssi_samples:
            return None
        return self.rssi_total_db / self.rssi_samples

    @property
    def pos_time_pct(self) -> float | None:
        """Percentage of the sighting during which positions were arriving.

        Measured between consecutive observations: an interval counts as
        positioned when a *new* position report landed in it. That makes the
        figure say what it should — how much of the time this aircraft was
        actually being tracked, not merely how long ago it last reported one,
        which the live record's sticky position would answer instead.

        ``None`` for a sighting with no elapsed time, where the question has no
        answer.
        """
        duration_ms = self.duration_ms
        if duration_ms <= 0:
            return None
        return min(_PERCENT, self.positioned_ms * _PERCENT / duration_ms)

    def observe(self, record: LiveAircraft) -> None:
        """Fold one live record into the running state.

        Idempotent for extremes (they are minima and maxima) and monotonic for
        ``last_seen_ms``, so replaying an event — which the overflow resync
        path does — cannot move a value backwards.
        """
        at_ms = to_epoch_ms(record.last_seen)
        counted = self.stats_ms is None or at_ms > self.stats_ms
        if at_ms > self.last_seen_ms:
            self.last_seen_ms = at_ms

        self._observe_flight_context(record, at_ms)
        self._observe_position_character(record)
        self._observe_extremes(record, at_ms)
        if counted:
            self._observe_reception(record, at_ms)
            self.stats_ms = at_ms
        self._harvest_track(record)
        self.dirty = True

    def _observe_flight_context(self, record: LiveAircraft, at_ms: int) -> None:
        """Track callsign, squawk and the emergency record (SPEC §17, §52).

        Each transition is also a ``sighting_events`` row. The comparison is
        against the accumulator's own last known value, which is what makes the
        emission exactly-once across both a resync (the value is unchanged, so
        nothing fires) and a restart (the value was rehydrated from the row).
        """
        callsign = record.callsign
        if callsign is not None and callsign != self.callsign_last:
            if self.callsign_first is None:
                self.callsign_first = callsign
            elif self.callsign_last is not None:
                self._emit(
                    SightingEventType.CALLSIGN_CHANGE,
                    at_ms,
                    {"from": self.callsign_last, "to": callsign},
                )
            self.callsign_last = callsign
            self.flush_immediately = True

        squawk = record.squawk
        if squawk is not None and squawk != self.squawk_last:
            if self.squawk_last is not None:
                self._emit(
                    SightingEventType.SQUAWK_CHANGE,
                    at_ms,
                    {"from": self.squawk_last, "to": squawk},
                )
            self.squawk_last = squawk
            self.flush_immediately = True

        self._observe_emergency(squawk, at_ms)

    def _observe_emergency(self, squawk: str | None, at_ms: int) -> None:
        """Record an emergency squawk appearing, and clearing again.

        A ``None`` squawk means the decoder did not report one on this poll,
        never that the code was cancelled, so it ends nothing — the same rule
        the live record's merge semantics apply to every field.
        """
        if squawk is None:
            return
        emergency = squawk in EMERGENCY_SQUAWKS
        if emergency and not self.emergency_active:
            self.emergency_active = True
            self.had_emergency = True
            self.flush_immediately = True
            self._emit(SightingEventType.EMERGENCY_START, at_ms, {"squawk": squawk})
        elif not emergency and self.emergency_active:
            self.emergency_active = False
            self.flush_immediately = True
            self._emit(SightingEventType.EMERGENCY_END, at_ms, {"squawk": squawk})

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

    def _observe_reception(self, record: LiveAircraft, at_ms: int) -> None:
        """Accumulate the reception statistics of SPEC §51.

        Called only for an observation newer than every one already counted, so
        every figure here is a plain sum or extreme over the update stream —
        which is exactly what the brute-force test recomputes.

        Message counts arrive as the decoder's *cumulative* counter for the
        aircraft, so they are differenced; a counter that goes backwards means
        the decoder restarted its trackfile, and its new value is taken whole
        rather than treated as a negative delta.
        """
        previous_ms = self.stats_ms

        messages = record.messages
        if messages is not None:
            seen = self.messages_seen
            # A counter that went backwards is a restarted trackfile, not a
            # negative delta: take its new value whole.
            delta = messages if seen is None or messages < seen else messages - seen
            self.msg_count += max(0, delta)
            self.messages_seen = messages

        rssi = record.rssi_db
        if rssi is not None:
            self.rssi_peak_db = rssi if self.rssi_peak_db is None else max(self.rssi_peak_db, rssi)
            self.rssi_min_db = rssi if self.rssi_min_db is None else min(self.rssi_min_db, rssi)
            self.rssi_total_db += rssi
            self.rssi_samples += 1

        position_at = record.position_seen
        if position_at is not None and position_at != self.last_position_at:
            self.pos_count += 1
            if previous_ms is not None:
                self.positioned_ms += at_ms - previous_ms
            self.last_position_at = position_at

    def _harvest_track(self, record: LiveAircraft) -> None:
        """Take the live track's new points into the un-checkpointed tail.

        Points arrive in the live record's own clock, so the high-water mark is
        kept in both clocks: the ``datetime`` the live track compares against,
        and the epoch milliseconds storage uses. Two points inside one
        millisecond collapse to the first — the packed encoding needs strictly
        increasing timestamps, and a sub-millisecond pair says nothing a track
        can draw.
        """
        for point in record.track.points_since(self.last_point_at):
            self.last_point_at = point.timestamp
            sample = from_track_point(point)
            if self.last_point_ms is not None and sample.ts_ms <= self.last_point_ms:
                continue
            self.pending_points.append(sample)
            self.last_point_ms = sample.ts_ms

    def _emit(self, event: SightingEventType, at_ms: int, payload: dict[str, str | None]) -> None:
        self.pending_events.append(PendingEvent(type=event, ts_ms=at_ms, payload=payload))

    # ------------------------------------------------------------- the writes

    def checkpoint_batch(self) -> CheckpointBatch | None:
        """The thinned checkpoint rows owed for the un-checkpointed tail.

        ``None`` when there is nothing to write, which is the common case for a
        non-positioned aircraft and for any cycle between position reports.
        """
        if not self.pending_points:
            return None
        samples = tuple(self.pending_points)
        kept = thin_for_checkpoint(samples, previous=self.checkpoint_anchor)
        rows = tuple((self.checkpoint_seq + offset, sample) for offset, sample in enumerate(kept))
        return CheckpointBatch(consumed=len(samples), rows=rows)

    def mark_checkpointed(self, batch: CheckpointBatch) -> None:
        """Record that ``batch`` reached the database.

        Called only after the transaction commits, so a failed cycle leaves the
        same points pending and the next one rewrites them — the seq numbers
        were never consumed.
        """
        for _ in range(min(batch.consumed, len(self.pending_points))):
            self.pending_points.popleft()
        self.checkpoint_seq += len(batch.rows)
        self.checkpoint_anchor = batch.last

    def take_events(self) -> tuple[PendingEvent, ...]:
        """The events owed, without clearing them."""
        return tuple(self.pending_events)

    def mark_events_written(self, written: int) -> None:
        """Drop the first ``written`` events, once their transaction committed."""
        del self.pending_events[:written]

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


__all__ = [
    "MAX_PENDING_POINTS",
    "ActiveSighting",
    "CheckpointBatch",
    "PendingEvent",
    "open_from",
]
