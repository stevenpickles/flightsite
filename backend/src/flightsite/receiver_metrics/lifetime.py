"""Lifetime aggregates and records — the half of ADR-0009 pruning may not touch.

SPEC §63 asks for since-T0 figures: total messages, total positions, the
furthest detection ever and when, the busiest day, the highest rates seen.
ADR-0009 adds the constraint that makes them hard: they must survive every
downsampling and pruning cycle, forever, on a database whose high-resolution
tier is deliberately thrown away every fortnight.

The rule that makes that structural
-----------------------------------

**Nothing here is ever derived from prunable data.** A lifetime total is
accumulated from the *increment* each sample represents, at the moment that
sample is first recorded, in the same transaction that records it. It is never
recomputed by summing ``receiver_metrics_raw``, so there is no query whose
answer changes when those rows are deleted — and equally, no way for a
re-processing pass to add the same interval twice.

Records (maxima) work the same way: each new observation is compared against
the stored record and replaces it or does not. That comparison is a total
function of "what is stored" and "what was just seen", so it is idempotent
under repetition and independent of how much history still exists.

The one figure with a different source is the busiest day, which is a maximum
over the **daily summary table** — permanent by ADR-0009, so reading it breaks
no invariant. It is re-derived as each daily row is written, which means a
correction to a day's total corrects the record too.

Values, not columns
-------------------

``lifetime_stats`` is a key/value table (``docs/DATA_MODEL.md`` §6.4), so this
module works in :class:`LifetimeValue` — one nullable number and one nullable
string per key — and :func:`merged` returns the complete set of rows a caller
should write. Keeping the merge pure is what lets the "records survive N
downsample-and-prune cycles" property be tested as arithmetic rather than as a
database drill (though it is tested as one of those too).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from flightsite.receiver_metrics.aggregate import counter_delta
from flightsite.receiver_metrics.model import (
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_BEARING,
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
    LIFETIME_PEAK_MSG_RATE,
    LIFETIME_PEAK_POS_RATE,
    LIFETIME_TOTAL_MESSAGES,
    LIFETIME_TOTAL_POSITIONS,
    MetricSample,
    RangeRecord,
    better_range,
)


@dataclass(frozen=True, slots=True)
class LifetimeValue:
    """One ``lifetime_stats`` row's payload: a number, a string, or both."""

    value_num: float | None = None
    value_text: str | None = None


@dataclass(frozen=True, slots=True)
class LifetimeDelta:
    """What a batch of samples adds to the lifetime record set.

    Totals are increments to be *added*; the rest are candidates to be
    compared against what is stored. Keeping the two kinds apart in the type
    is what stops a maximum from ever being accumulated or a total from ever
    being maximised.
    """

    messages: int = 0
    positions: int = 0
    max_range: RangeRecord | None = None
    max_simultaneous: int | None = None
    peak_msg_rate: float | None = None
    peak_pos_rate: float | None = None

    @property
    def is_empty(self) -> bool:
        """True when there is nothing to write.

        A batch of samples from a silent receiver is genuinely empty: no
        traffic, no aircraft, no records. Writing it would be a transaction
        that changes nothing.
        """
        return (
            self.messages == 0
            and self.positions == 0
            and self.max_range is None
            and self.max_simultaneous is None
            and self.peak_msg_rate is None
            and self.peak_pos_rate is None
        )


class LifetimeAccumulator:
    """Folds samples into a pending :class:`LifetimeDelta`.

    Held in memory between flushes and drained into the transaction that
    writes the samples themselves, so the totals and the rows they were
    counted from land together or not at all.
    """

    __slots__ = ("_delta",)

    def __init__(self) -> None:
        self._delta = LifetimeDelta()

    @property
    def pending(self) -> LifetimeDelta:
        """The delta accumulated but not yet drained. Read-only; for tests."""
        return self._delta

    def observe(
        self,
        sample: MetricSample,
        *,
        previous: MetricSample | None,
        ranges: Sequence[RangeRecord] = (),
    ) -> None:
        """Fold one sample and its range observations into the pending delta.

        ``previous`` is the sample immediately before this one, which is what
        turns the sample's rates back into the counts they were measured from
        — using exactly the function the hourly and daily summaries use, so a
        lifetime total and the sum of the summaries over the same interval
        agree by construction rather than by coincidence.
        """
        delta = self._delta
        messages = counter_delta(sample, previous, sample.messages_per_sec) or 0
        positions = counter_delta(sample, previous, sample.positions_per_sec) or 0

        furthest = delta.max_range
        for observation in ranges:
            furthest = better_range(furthest, observation)

        self._delta = replace(
            delta,
            messages=delta.messages + messages,
            positions=delta.positions + positions,
            max_range=furthest,
            max_simultaneous=_greater_count(delta.max_simultaneous, sample.aircraft_visible),
            peak_msg_rate=_greater(delta.peak_msg_rate, sample.messages_per_sec),
            peak_pos_rate=_greater(delta.peak_pos_rate, sample.positions_per_sec),
        )

    def drain(self) -> LifetimeDelta:
        """Take the pending delta and start a fresh one.

        Called by the writer *after* its transaction has committed, so a
        failed flush leaves the delta intact and the next flush carries it.
        Draining first would lose an interval's traffic to a transient
        ``SQLITE_BUSY``.
        """
        drained, self._delta = self._delta, LifetimeDelta()
        return drained

    def restore(self, delta: LifetimeDelta) -> None:
        """Put a drained delta back, merged with anything since. For retries."""
        pending = self._delta
        self._delta = LifetimeDelta(
            messages=delta.messages + pending.messages,
            positions=delta.positions + pending.positions,
            max_range=better_range(delta.max_range, pending.max_range)
            if pending.max_range is not None
            else delta.max_range,
            max_simultaneous=_greater_count(delta.max_simultaneous, pending.max_simultaneous),
            peak_msg_rate=_greater(delta.peak_msg_rate, pending.peak_msg_rate),
            peak_pos_rate=_greater(delta.peak_pos_rate, pending.peak_pos_rate),
        )


def _greater(current: float | None, candidate: float | None) -> float | None:
    """The larger of two optional numbers, preferring whichever exists."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


def _greater_count(current: int | None, candidate: int | None) -> int | None:
    """:func:`_greater` for counts, which stay integers rather than becoming floats."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


def _number(stored: Mapping[str, LifetimeValue], key: str) -> float | None:
    value = stored.get(key)
    return None if value is None else value.value_num


def merged(stored: Mapping[str, LifetimeValue], delta: LifetimeDelta) -> dict[str, LifetimeValue]:
    """The rows that should replace ``stored`` once ``delta`` is applied.

    Only changed keys are returned, so an ordinary flush of a quiet receiver
    writes one or two rows rather than eleven. Totals accumulate; maxima
    replace only when genuinely exceeded; and the four keys describing the
    furthest detection ever move together, because a range with somebody
    else's timestamp on it would be a record of nothing.
    """
    updates: dict[str, LifetimeValue] = {}

    if delta.messages:
        total = (_number(stored, LIFETIME_TOTAL_MESSAGES) or 0.0) + delta.messages
        updates[LIFETIME_TOTAL_MESSAGES] = LifetimeValue(value_num=total)
    if delta.positions:
        total = (_number(stored, LIFETIME_TOTAL_POSITIONS) or 0.0) + delta.positions
        updates[LIFETIME_TOTAL_POSITIONS] = LifetimeValue(value_num=total)

    candidate = delta.max_range
    if candidate is not None:
        record = _number(stored, LIFETIME_MAX_RANGE_NM)
        if record is None or candidate.max_range_nm > record:
            updates[LIFETIME_MAX_RANGE_NM] = LifetimeValue(value_num=candidate.max_range_nm)
            updates[LIFETIME_MAX_RANGE_AT_MS] = LifetimeValue(value_num=float(candidate.at_ms))
            updates[LIFETIME_MAX_RANGE_BEARING] = LifetimeValue(value_num=candidate.bearing_deg)
            updates[LIFETIME_MAX_RANGE_ICAO24] = LifetimeValue(value_text=candidate.icao24)

    for key, value in (
        (LIFETIME_MAX_SIMULTANEOUS, delta.max_simultaneous),
        (LIFETIME_PEAK_MSG_RATE, delta.peak_msg_rate),
        (LIFETIME_PEAK_POS_RATE, delta.peak_pos_rate),
    ):
        if value is None:
            continue
        record = _number(stored, key)
        if record is None or value > record:
            updates[key] = LifetimeValue(value_num=float(value))

    return updates


def merged_busiest_day(
    stored: Mapping[str, LifetimeValue], totals: Mapping[str, int | None]
) -> dict[str, LifetimeValue]:
    """The busiest-day rows implied by freshly written daily message totals.

    Ranked on ``messages_total`` because that is the one figure available for
    every deployment: the decoder supplies it directly, and where it does not,
    the live-set fallback still counts real messages. A day with no message
    total at all — one the receiver was up for but nothing was measurable on —
    is simply not a candidate, which is SPEC §60's graceful absence again.

    ``totals`` carries only the days just recomputed, so the standing record
    stands unless one of them beats it. The one exception is the standing
    record's *own* day being recomputed: its new total supersedes the stored
    one, up or down, because the record names that day and must describe it.

    The comparison is strictly greater, so a later day tying the record does
    not displace it: "the busiest day" should name the day it first happened.
    """
    stored_day = stored.get(LIFETIME_BUSIEST_DAY)
    stored_count = _number(stored, LIFETIME_BUSIEST_DAY_COUNT)

    day: str | None = None if stored_day is None else stored_day.value_text
    count: float | None = stored_count
    if day is not None and day in totals:
        recomputed = totals[day]
        # A day that no longer has a message total cannot hold the record.
        day, count = (None, None) if recomputed is None else (day, float(recomputed))

    for candidate_day, total in sorted(totals.items()):
        if total is not None and (count is None or total > count):
            day, count = candidate_day, float(total)

    if day is None or count is None:
        return {}
    if stored_day is not None and stored_day.value_text == day and stored_count == count:
        return {}
    return {
        LIFETIME_BUSIEST_DAY: LifetimeValue(value_text=day),
        LIFETIME_BUSIEST_DAY_COUNT: LifetimeValue(value_num=count),
    }


__all__ = [
    "LifetimeAccumulator",
    "LifetimeDelta",
    "LifetimeValue",
    "merged",
    "merged_busiest_day",
]
