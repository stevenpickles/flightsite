"""Downsampling: raw samples in, hourly and daily summaries out.

This module is the arithmetic half of ADR-0009, and it is deliberately pure —
no database, no clock, no configuration. Every retention decision that has a
*correct answer* is computed here so it can be property-tested against a
brute-force recomputation over fixtures (SPEC §84 lists retention as a
critical-coverage domain).

Idempotence
-----------

ADR-0009 requires downsampling that a crash or a restart cannot make
double-count. The guarantee here is structural rather than transactional:
:func:`summarize` is a **total function of the raw rows in a bucket**, so
re-running it over the same rows produces the same summary, and the writer
replaces the row rather than adding to it. Nothing accumulates, so nothing can
accumulate twice. (The lifetime totals, which genuinely *are* accumulated, are
never computed here — they ride the sample as it is first recorded. See
:mod:`flightsite.receiver_metrics.sampler`.)

Counts from rates
-----------------

``receiver_metrics_raw`` stores rates, and §6.2 wants totals. The two are the
same information: a sample's ``messages_per_sec`` was measured as the decoder's
counter delta divided by the interval since the previous sample, so multiplying
it back by that interval recovers the delta exactly. :func:`summarize` therefore
walks samples in order, reconstructs each delta from the gap to the sample
before it, and sums them into the bucket the *later* sample falls in — which is
the bucket during which those messages were actually counted.

Two consequences follow, and both are deliberate:

* A sample whose rate is ``None`` contributes no delta. That is the honest
  reading: a rate is ``None`` exactly when there was no usable previous sample
  to difference against (a restart, a decoder counter reset, a gap too long to
  trust), so no interval's worth of traffic is attributable.
* The first sample of a sequence contributes no delta unless the caller
  supplies the sample immediately before it. The repository does supply it —
  that is what :meth:`~flightsite.receiver_metrics.repository.MetricsRepository.samples_from`
  fetches a preceding row for — so in production only the very first sample the
  install ever took is unattributed.

Day bucketing and DST
---------------------

Hour buckets are UTC (``docs/DATA_MODEL.md`` §6.2 keys them by
``hour_start_ms``); day buckets are the **receiver-local calendar date** in the
configured IANA zone (§10). :func:`local_day` does the conversion with
:mod:`zoneinfo`, so a 23-hour or 25-hour local day rolls up as the day it
actually was, and no arithmetic on fixed offsets is performed anywhere.

Note that a local day is *not* a whole number of UTC hours in every zone —
``Asia/Kolkata`` is +05:30, ``Australia/Adelaide`` +09:30, ``Pacific/Chatham``
+12:45 — which is why the daily tier is folded from **raw samples** rather than
from the hourly rows. Both tiers are recomputed from the same source, so both
are exact, and the layering ADR-0009 describes (a pruned high-resolution window
beneath two permanent summary tiers) is unaffected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, time
from statistics import fmean
from typing import Final
from zoneinfo import ZoneInfo

from flightsite.db.clock import MS_PER_SECOND
from flightsite.receiver_metrics.model import MetricSample, MetricSummary

MS_PER_HOUR: Final = 3_600 * MS_PER_SECOND

#: Longest gap between two samples that a rate may still be differenced over.
#:
#: At the ~15 s sampling cadence a gap this long means something stopped —
#: FlightSite, the decoder, or the machine — and the counter on the far side of
#: it is not a measurement of the interval it appears to span. Averaging an
#: outage into a rate would understate every chart it appears in and could
#: invent a "peak" out of a decoder that restarted its counters, so the sample
#: carries no rate at all instead.
MAX_RATE_GAP_MS: Final = 5 * 60 * MS_PER_SECOND


def hour_start_ms(ts_ms: int) -> int:
    """The UTC hour ``ts_ms`` falls in, as the epoch ms of that hour's start."""
    return ts_ms - ts_ms % MS_PER_HOUR


def local_day(ts_ms: int, zone: ZoneInfo) -> str:
    """The receiver-local calendar date of ``ts_ms`` as ``YYYY-MM-DD`` (§10)."""
    return datetime.fromtimestamp(ts_ms / MS_PER_SECOND, tz=zone).date().isoformat()


def local_day_start_ms(day: str, zone: ZoneInfo) -> int:
    """Epoch ms of local midnight opening ``day`` in ``zone``.

    Used by the retention pass to decide whether a day is still fully covered
    by retained raw samples. On the rare zone whose DST transition happens *at*
    midnight, the local time named by this date does not exist; Python resolves
    that by fold rules to a real instant on the correct day, which is the right
    answer for a boundary test.
    """
    midnight = datetime.combine(datetime.fromisoformat(day).date(), time.min, tzinfo=zone)
    return int(midnight.timestamp() * MS_PER_SECOND)


def counter_delta(
    sample: MetricSample, previous: MetricSample | None, rate: float | None
) -> int | None:
    """The counter increment ``rate`` represents, or ``None`` if unattributable.

    Rounded per sample rather than after summing: each term *is* an integer
    count that a float division and multiplication has been round-tripped
    through, so rounding it individually recovers the original exactly, while
    rounding a sum of the residues would not.
    """
    if rate is None or previous is None:
        return None
    elapsed_ms = sample.ts_ms - previous.ts_ms
    if elapsed_ms <= 0 or elapsed_ms > MAX_RATE_GAP_MS:
        return None
    return round(rate * elapsed_ms / MS_PER_SECOND)


def _present(values: Iterable[float | None]) -> list[float]:
    """The non-``None`` members, which are the only ones an aggregate sees."""
    return [value for value in values if value is not None]


def _mean(values: Iterable[float | None]) -> float | None:
    present = _present(values)
    return fmean(present) if present else None


def _max(values: Iterable[float | None]) -> float | None:
    present = _present(values)
    return max(present) if present else None


def _total(deltas: Iterable[int | None]) -> int | None:
    """The bucket's count, or ``None`` when nothing in it was attributable."""
    present = [delta for delta in deltas if delta is not None]
    return sum(present) if present else None


def summarize(
    samples: Sequence[MetricSample], previous: MetricSample | None = None
) -> MetricSummary:
    """Fold one bucket's raw samples into its summary row.

    ``samples`` must be ordered by ``ts_ms`` and must be the *whole* bucket;
    ``previous`` is the sample immediately before the first of them, wherever
    one is still retained, and is used only to attribute the first interval's
    counts.

    Raises:
        ValueError: if ``samples`` is empty. A bucket with no samples has no
            row — writing one with ``sample_count = 0`` would claim the
            receiver was up and heard nothing.
    """
    if not samples:
        raise ValueError("cannot summarize an empty bucket")

    predecessors: list[MetricSample | None] = [previous, *samples[:-1]]
    message_deltas = [
        counter_delta(sample, before, sample.messages_per_sec)
        for sample, before in zip(samples, predecessors, strict=True)
    ]
    position_deltas = [
        counter_delta(sample, before, sample.positions_per_sec)
        for sample, before in zip(samples, predecessors, strict=True)
    ]
    aircraft_max = _max(
        float(s.aircraft_visible) for s in samples if s.aircraft_visible is not None
    )

    return MetricSummary(
        sample_count=len(samples),
        messages_total=_total(message_deltas),
        positions_total=_total(position_deltas),
        msgs_per_sec_avg=_mean(s.messages_per_sec for s in samples),
        msgs_per_sec_max=_max(s.messages_per_sec for s in samples),
        pos_per_sec_avg=_mean(s.positions_per_sec for s in samples),
        pos_per_sec_max=_max(s.positions_per_sec for s in samples),
        aircraft_avg=_mean(
            float(s.aircraft_visible) if s.aircraft_visible is not None else None for s in samples
        ),
        aircraft_max=None if aircraft_max is None else int(aircraft_max),
        max_range_nm=_max(s.max_range_nm for s in samples),
        rssi_avg_db=_mean(s.rssi_avg_db for s in samples),
        rssi_peak_db=_max(s.rssi_peak_db for s in samples),
    )


def summarize_by[BucketKey: (int, str)](
    samples: Sequence[MetricSample],
    key: Callable[[int], BucketKey],
    *,
    previous: MetricSample | None = None,
) -> dict[BucketKey, MetricSummary]:
    """Group ``samples`` by ``key(ts_ms)`` and summarize each bucket.

    One pass over an ordered run of samples produces every bucket it touches,
    which is what lets a summary carry counts across a bucket boundary: the
    first sample of an hour is differenced against the last sample of the hour
    before, not against nothing.

    ``samples`` must be ordered by ``ts_ms``. ``previous`` is the retained
    sample immediately before them, if any.
    """
    buckets: dict[BucketKey, list[MetricSample]] = {}
    for sample in samples:
        buckets.setdefault(key(sample.ts_ms), []).append(sample)

    predecessor = previous
    summaries: dict[BucketKey, MetricSummary] = {}
    for bucket_key, bucket in buckets.items():
        summaries[bucket_key] = summarize(bucket, predecessor)
        predecessor = bucket[-1]
    return summaries


def hourly(
    samples: Sequence[MetricSample], *, previous: MetricSample | None = None
) -> dict[int, MetricSummary]:
    """Summaries keyed by the UTC hour each sample falls in."""
    return summarize_by(samples, hour_start_ms, previous=previous)


def daily(
    samples: Sequence[MetricSample], zone: ZoneInfo, *, previous: MetricSample | None = None
) -> dict[str, MetricSummary]:
    """Summaries keyed by the receiver-local calendar day (§10, DST-correct)."""
    return summarize_by(samples, lambda ts_ms: local_day(ts_ms, zone), previous=previous)


__all__ = [
    "MAX_RATE_GAP_MS",
    "MS_PER_HOUR",
    "counter_delta",
    "daily",
    "hour_start_ms",
    "hourly",
    "local_day",
    "local_day_start_ms",
    "summarize",
    "summarize_by",
]
