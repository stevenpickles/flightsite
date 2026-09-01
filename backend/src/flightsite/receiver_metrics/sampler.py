"""Turning one instant of the live set (plus the decoder's counters) into a sample.

This is where the FlightSite-computed half of SPEC §60 lives: simultaneous
aircraft, positions/sec, messages/sec, and the furthest aircraft in each
bearing sector. It reads the live store's snapshot and nothing else — no
database, no network, no event subscription — so a sample costs one pass over a
few hundred immutable records and can be taken from any task at any time.

Rates, and where they come from
-------------------------------

A rate is always a difference between two cumulative counters divided by the
time between them, and there are two places to get the counters:

* **The decoder's own**, from ``stats.json``. Preferred, because they count
  every message the decoder accepted, including from aircraft that came and
  went between two of FlightSite's samples.
* **The live set's**, when the decoder serves no statistics. Every live record
  carries the decoder's per-aircraft message count and an append-only track, so
  summing each aircraft's increase across two snapshots gives real message and
  position counts for the interval.

The fallback deliberately counts **only aircraft present in both snapshots**.
An aircraft that appeared during the interval arrives carrying however many
messages the decoder had already logged against it — a number about the past,
not about these fifteen seconds — and adding it in would produce a spike out of
an aircraft that merely came into range. So the fallback slightly *understates*
a busy sky, which is the right direction for a number that is only used when
the authoritative source is unavailable, and the sample records which source it
came from nowhere: a rate is a rate.

Both paths refuse to produce a rate at all when they cannot produce a true one:
the first sample after a start, a gap longer than
:data:`~flightsite.receiver_metrics.aggregate.MAX_RATE_GAP_MS`, or a counter
that went *backwards* — which is a decoder that restarted, and whose next
interval is the first honest one. In each case the rate is ``None``, not zero
(SPEC §39).

Range by bearing
----------------

Every positioned aircraft in the snapshot contributes its distance to the 5°
sector its bearing falls in, and the sector keeps the furthest. Distance and
bearing are the live store's own derived fields
(:mod:`flightsite.live.geo`), so the polar plot and the range rings are drawn
from one computation rather than two that could disagree. A receiver with no
configured location produces neither, and therefore no range records at all —
the honest outcome, since range from an unknown point is not a measurement.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from flightsite.db.clock import MS_PER_SECOND
from flightsite.live.aircraft import LiveAircraft
from flightsite.receiver_metrics.aggregate import MAX_RATE_GAP_MS
from flightsite.receiver_metrics.model import (
    DecoderStats,
    MetricSample,
    RangeRecord,
    better_range,
)


@dataclass(frozen=True, slots=True)
class SampleResult:
    """One sample and the range records the same instant produced."""

    sample: MetricSample
    ranges: tuple[RangeRecord, ...] = ()


@dataclass(slots=True)
class _Counters:
    """The cumulative counters one snapshot's rates will be differenced from."""

    ts_ms: int
    messages_total: int | None = None
    positions_total: int | None = None
    #: Per-aircraft decoder message counts, for the live-set fallback.
    messages_by_icao: dict[str, int] = field(default_factory=dict)
    #: Per-aircraft position-report counts, for the live-set fallback.
    positions_by_icao: dict[str, int] = field(default_factory=dict)


def _reported_positions(aircraft: LiveAircraft) -> int:
    """How many positions this aircraft has reported since it appeared.

    The live track is append-only and bounded, so its length alone would stop
    growing at capacity; adding what it has dropped restores the monotonic
    count the difference needs.
    """
    return len(aircraft.track) + aircraft.track.dropped


def _live_counters(ts_ms: int, aircraft: Sequence[LiveAircraft]) -> _Counters:
    return _Counters(
        ts_ms=ts_ms,
        messages_by_icao={a.icao: a.messages for a in aircraft if a.messages is not None},
        positions_by_icao={a.icao: _reported_positions(a) for a in aircraft},
    )


def _rate(current: int | None, previous: int | None, elapsed_s: float) -> float | None:
    """A per-second rate from two cumulative counters, or ``None``.

    ``None`` covers every case where no true rate exists: either counter
    missing, or a counter that went backwards because the decoder restarted.
    """
    if current is None or previous is None or current < previous:
        return None
    return (current - previous) / elapsed_s


def _summed_increase(current: dict[str, int], previous: dict[str, int]) -> int:
    """Total increase across keys present in both, ignoring counter resets.

    Per aircraft rather than in aggregate, because the aggregate over a
    changing population is not a counter at all — see the module docstring.
    """
    return sum(
        max(0, count - previous[icao]) for icao, count in current.items() if icao in previous
    )


class MetricSampler:
    """Builds one :class:`MetricSample` per tick from the live set and the decoder.

    Holds exactly one thing between calls: the previous tick's counters, which
    is what makes a rate possible at all. Nothing here is asynchronous and
    nothing here can fail.

    Args:
        max_gap_ms: longest interval a rate may be differenced over. Beyond it
            the interval is treated as an outage and no rate is reported.
    """

    __slots__ = ("_max_gap_ms", "_previous")

    def __init__(self, *, max_gap_ms: int = MAX_RATE_GAP_MS) -> None:
        if max_gap_ms <= 0:
            raise ValueError("max_gap_ms must be greater than zero")
        self._max_gap_ms = max_gap_ms
        self._previous: _Counters | None = None

    @property
    def has_baseline(self) -> bool:
        """True once a previous tick exists to difference the next one against."""
        return self._previous is not None

    def reset(self) -> None:
        """Forget the baseline, so the next sample reports no rates.

        Called when the process can no longer vouch for continuity with the
        last tick — a stop and restart of the service, most obviously.
        """
        self._previous = None

    def sample(
        self,
        *,
        ts_ms: int,
        aircraft: Sequence[LiveAircraft],
        stats: DecoderStats | None = None,
    ) -> SampleResult:
        """Take one sample of the receiver at ``ts_ms``.

        ``aircraft`` is the live snapshot; ``stats`` the decoder's counters if
        it served any. Aircraft counts and range come from the snapshot in
        every case, so a receiver whose decoder has no statistics endpoint
        still records simultaneous aircraft, maximum range and the polar plot.
        """
        current = _live_counters(ts_ms, aircraft)
        current.messages_total = None if stats is None else stats.messages_total
        current.positions_total = None if stats is None else stats.positions_total

        messages_per_sec, positions_per_sec = self._rates(current)
        visible = len(aircraft)
        positioned = sum(1 for a in aircraft if a.has_position)
        ranges = self._ranges(ts_ms, aircraft)

        self._previous = current
        return SampleResult(
            sample=MetricSample(
                ts_ms=ts_ms,
                messages_per_sec=messages_per_sec,
                positions_per_sec=positions_per_sec,
                aircraft_visible=visible,
                aircraft_with_pos=positioned,
                max_range_nm=max((r.max_range_nm for r in ranges), default=None),
                rssi_avg_db=None if stats is None else stats.rssi_avg_db,
                rssi_peak_db=None if stats is None else stats.rssi_peak_db,
            ),
            ranges=ranges,
        )

    def _rates(self, current: _Counters) -> tuple[float | None, float | None]:
        """Message and position rates for the interval ending at ``current``."""
        previous = self._previous
        if previous is None:
            return None, None
        elapsed_ms = current.ts_ms - previous.ts_ms
        if elapsed_ms <= 0 or elapsed_ms > self._max_gap_ms:
            return None, None
        elapsed_s = elapsed_ms / MS_PER_SECOND

        messages = _rate(current.messages_total, previous.messages_total, elapsed_s)
        if messages is None:
            messages = (
                _summed_increase(current.messages_by_icao, previous.messages_by_icao) / elapsed_s
            )
        positions = _rate(current.positions_total, previous.positions_total, elapsed_s)
        if positions is None:
            positions = (
                _summed_increase(current.positions_by_icao, previous.positions_by_icao) / elapsed_s
            )
        return messages, positions

    @staticmethod
    def _ranges(ts_ms: int, aircraft: Iterable[LiveAircraft]) -> tuple[RangeRecord, ...]:
        """The furthest aircraft in each 5° sector at this instant."""
        best: dict[int, RangeRecord] = {}
        for record in aircraft:
            distance, bearing = record.distance_nm, record.bearing_deg
            if distance is None or bearing is None:
                continue
            candidate = RangeRecord(
                bearing_deg=bearing,
                max_range_nm=distance,
                at_ms=ts_ms,
                icao24=record.icao,
            )
            bucket = candidate.bearing_bucket
            best[bucket] = better_range(best.get(bucket), candidate)
        return tuple(best[bucket] for bucket in sorted(best))


#: Nominal spacing between raw samples (``docs/DATA_MODEL.md`` §6.1).
#:
#: Not configurable, and deliberately so: it is the resolution the raw table's
#: row-count budget and ADR-0009's window sizing are both stated in, so making
#: it a setting would let a user silently multiply their database growth by
#: fifteen. The value is injectable for tests, which is a different thing.
DEFAULT_SAMPLE_INTERVAL_S: Final = 15.0


__all__ = [
    "DEFAULT_SAMPLE_INTERVAL_S",
    "MetricSampler",
    "SampleResult",
]
