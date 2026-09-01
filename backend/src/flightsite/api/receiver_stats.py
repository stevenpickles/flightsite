"""Receiver stats API — query layer and pure helpers (roadmap slice 034).

``docs/API.md`` §3.8 publishes five endpoints: a scorecard, a generic
time-series, the range-by-bearing polar histogram, the signal-strength
distribution, and lifetime statistics. :mod:`flightsite.receiver_metrics` owns
the storage those first four partly read (SPEC §60/§64, ADR-0009); this module
owns everything that data does not answer on its own:

* **Unique aircraft** (today, since T0, and per-day for the ``unique_aircraft``
  chart) is deliberately *not* here — it is read straight from roadmap slice
  031's daily rollups via :class:`~flightsite.analytics.queries.AnalyticsQueries`
  (:meth:`~flightsite.api.context.LiveApiContext.receiver_scorecard` and
  :meth:`~flightsite.api.context.LiveApiContext.receiver_metric_series`), so
  this figure and the Analytics page's own "unique aircraft" stat tile answer
  from one query rather than two that could disagree.
* **Total sightings** and the lifetime "most/common" records below still are —
  the ``aircraft``/``sightings`` tables, which slice 031's rollups do not
  cover.
* **The signal-strength distribution** — per-sighting ``rssi_avg_db``
  (slice 052), explicitly *not* the raw-sample RSSI ``receiver_metrics``
  stores (see the note in ``flightsite.receiver_metrics``'s module docstring
  and roadmap slice 033's ``out_of_scope`` entry).
* **Lifetime "most/common" records** — joins over ``aircraft`` and resolved
  metadata that have nothing to do with metric retention.
* **The "ever" range-by-bearing reduction** — a pure fold of every stored
  daily record (``range_by_bearing_daily`` is retained indefinitely, §6.3)
  down to one all-time record per sector, using the same
  :func:`~flightsite.receiver_metrics.model.better_range` comparison
  production uses so the two can never disagree about what "further" means.

Every read here goes through :meth:`~flightsite.db.engine.Database.read_session`
(ADR-0001), exactly like :mod:`flightsite.api.history` and
:mod:`flightsite.api.sightings` — this module can never become a second
writer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import ColumnElement, func, select

from flightsite.db import Database
from flightsite.db.models import Aircraft, AircraftMetadataResolved, Sighting
from flightsite.receiver_metrics.model import RangeRecord, better_range

#: Default RSSI histogram bucket width, dB. Coarse enough that a receiver's
#: typical signal spread fills a readable number of bars — SPEC §62 asks for a
#: distribution a person can read, not a per-tenth-of-a-dB table nobody acts on.
DEFAULT_SIGNAL_BUCKET_WIDTH_DB: Final = 3.0
MIN_SIGNAL_BUCKET_WIDTH_DB: Final = 0.5
MAX_SIGNAL_BUCKET_WIDTH_DB: Final = 20.0

#: SPEC §62's v1 chart catalog, minus the two endpoints with their own shape
#: (range-by-bearing, signal-distribution). ``unique_aircraft`` has no entry
#: here because it is never read from ``receiver_metrics_raw``/``*_summary``
#: at all — it comes from the analytics rollups (module docstring).
RAW_FIELD_FOR_METRIC: Final[Mapping[str, str]] = {
    "messages_per_sec": "messages_per_sec",
    "positions_per_sec": "positions_per_sec",
    "aircraft_count": "aircraft_visible",
    "max_range_nm": "max_range_nm",
}

#: The same catalog's summary-column counterpart, read once samples have been
#: folded into an hourly or daily bucket. ``aircraft_count`` reads the
#: bucket's *peak* simultaneous count (``aircraft_max``) rather than its
#: average: "simultaneous aircraft over time" (SPEC §62) is a chart of load,
#: and a peak is what a receiver operator actually wants to see per bucket.
SUMMARY_FIELD_FOR_METRIC: Final[Mapping[str, str]] = {
    "messages_per_sec": "msgs_per_sec_avg",
    "positions_per_sec": "pos_per_sec_avg",
    "aircraft_count": "aircraft_max",
    "max_range_nm": "max_range_nm",
    "messages_total": "messages_total",
    "positions_total": "positions_total",
}

#: Metrics with no raw-resolution representation: ``receiver_metrics_raw``
#: stores rates, not the totals these two name (see
#: :mod:`flightsite.receiver_metrics.aggregate`'s "Counts from rates" note).
SUMMARY_ONLY_METRICS: Final = frozenset({"messages_total", "positions_total"})

#: Default lookback applied when a series request omits ``from``, keyed by the
#: *effective* resolution — matching the frontend's 24h/7d/30d window selector
#: to the tier that can actually answer it: raw retains a couple of weeks at
#: most (ADR-0009), hourly and daily are permanent.
_MS_PER_DAY: Final = 24 * 3_600 * 1_000
DEFAULT_LOOKBACK_MS: Final[Mapping[str, int]] = {
    "high": 1 * _MS_PER_DAY,
    "hourly": 7 * _MS_PER_DAY,
    "daily": 30 * _MS_PER_DAY,
}


class ReceiverMetricQueryError(ValueError):
    """An unsupported ``metric``/``resolution`` pairing for the series endpoint.

    Raised for the two combinations ``docs/API.md`` §3.8 does not offer an
    answer to: ``unique_aircraft`` at anything but ``resolution=daily``, and a
    :data:`SUMMARY_ONLY_METRICS` metric at ``resolution=high``. The endpoint
    catches this and answers the §2.5 error envelope with a 400, the same
    pattern :func:`flightsite.airports.overlay.parse_bbox` uses for a
    malformed ``bbox``.
    """


def next_local_day(day: str) -> str:
    """The calendar day after ``day`` (``YYYY-MM-DD``), by date arithmetic alone.

    No timezone is involved: two consecutive local-day strings are always
    exactly one calendar day apart regardless of what a DST transition does to
    the *duration* between them, so this needs nothing
    :func:`~flightsite.receiver_metrics.aggregate.local_day` does not already
    guarantee about its own output.
    """
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def ever_ranges(rows: Iterable[tuple[str, RangeRecord]]) -> dict[int, RangeRecord]:
    """Reduce every stored ``(day, RangeRecord)`` pair to one record per sector.

    ``rows`` must be ordered oldest-day-first:
    :func:`~flightsite.receiver_metrics.model.better_range` keeps its
    ``current`` argument on a tie, so processing chronologically is what makes
    a tie resolve to *when the receiver first reached that far* — the same
    rule the lifetime max-range record uses.
    """
    best: dict[int, RangeRecord] = {}
    for _day, record in rows:
        bucket = record.bearing_bucket
        best[bucket] = better_range(best.get(bucket), record)
    return best


@dataclass(frozen=True, slots=True)
class SignalHistogramBucket:
    """One bar of the signal-strength distribution."""

    min_db: float
    max_db: float
    count: int


@dataclass(frozen=True, slots=True)
class SignalHistogram:
    """The signal-strength distribution — SPEC §62, from per-sighting RSSI."""

    bucket_width_db: float
    buckets: tuple[SignalHistogramBucket, ...]
    sample_count: int
    min_db: float | None
    max_db: float | None
    avg_db: float | None


def signal_histogram(
    values: Sequence[float], *, bucket_width_db: float = DEFAULT_SIGNAL_BUCKET_WIDTH_DB
) -> SignalHistogram:
    """Bucket ``values`` (per-sighting ``rssi_avg_db`` readings) into a fixed-width histogram.

    Pure and total: an empty ``values`` answers zero buckets and ``null``
    extremes rather than dividing by zero or fabricating a range (SPEC §39) —
    "no sighting in this window had a signal reading" is a real, ordinary
    first-run answer.
    """
    if bucket_width_db <= 0:
        raise ValueError("bucket_width_db must be greater than zero")
    if not values:
        return SignalHistogram(
            bucket_width_db=bucket_width_db,
            buckets=(),
            sample_count=0,
            min_db=None,
            max_db=None,
            avg_db=None,
        )

    low = min(values)
    high = max(values)
    start = math.floor(low / bucket_width_db) * bucket_width_db
    # At least one bucket even when every value is identical (high == low).
    bucket_count = max(1, math.ceil((high - start) / bucket_width_db))
    counts = [0] * bucket_count
    for value in values:
        index = min(max(int((value - start) / bucket_width_db), 0), bucket_count - 1)
        counts[index] += 1

    buckets = tuple(
        SignalHistogramBucket(
            min_db=start + index * bucket_width_db,
            max_db=start + (index + 1) * bucket_width_db,
            count=count,
        )
        for index, count in enumerate(counts)
    )
    return SignalHistogram(
        bucket_width_db=bucket_width_db,
        buckets=buckets,
        sample_count=len(values),
        min_db=low,
        max_db=high,
        avg_db=sum(values) / len(values),
    )


@dataclass(frozen=True, slots=True)
class MostFrequentAircraft:
    """The airframe with the most sightings — one entry of SPEC §63."""

    icao24: str
    registration: str | None
    sighting_count: int


@dataclass(frozen=True, slots=True)
class CommonRecord:
    """One "most common X" record — SPEC §63's type/model/operator entries."""

    value: str
    aircraft_count: int


class ReceiverStatsRepository:
    """Queries the scorecard, lifetime and signal-distribution endpoints need
    beyond what :class:`~flightsite.receiver_metrics.repository.MetricsRepository`
    already answers — see the module docstring.
    """

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    # -------------------------------------------------------------- charts

    async def total_sightings(self) -> int:
        """Every sighting ever recorded (SPEC §65: retained indefinitely)."""
        async with self._database.read_session() as session:
            return int(await session.scalar(select(func.count()).select_from(Sighting)) or 0)

    async def signal_values(self, *, from_ms: int | None, to_ms: int | None) -> tuple[float, ...]:
        """Per-sighting ``rssi_avg_db`` readings with ``started_at`` in ``[from_ms, to_ms]``.

        ``None`` bounds are unrestricted: an install with no explicit window
        gets the distribution over every sighting ever recorded, mirroring how
        ``GET /api/v1/sightings`` treats an absent ``from``/``to`` (§3.6).
        """
        conditions: list[ColumnElement[bool]] = [Sighting.rssi_avg_db.is_not(None)]
        if from_ms is not None:
            conditions.append(Sighting.started_ms >= from_ms)
        if to_ms is not None:
            conditions.append(Sighting.started_ms <= to_ms)
        statement = select(Sighting.rssi_avg_db).where(*conditions)
        async with self._database.read_session() as session:
            values = (await session.scalars(statement)).all()
        return tuple(float(value) for value in values if value is not None)

    # ------------------------------------------------------------- lifetime

    async def most_frequent_aircraft(self) -> MostFrequentAircraft | None:
        """The airframe with the most sightings, or ``None`` on an empty install."""
        statement = (
            select(
                Aircraft.icao24,
                Aircraft.sighting_count,
                AircraftMetadataResolved.registration,
            )
            .outerjoin(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .where(Aircraft.sighting_count > 0)
            .order_by(Aircraft.sighting_count.desc(), Aircraft.icao24.asc())
            .limit(1)
        )
        async with self._database.read_session() as session:
            row = (await session.execute(statement)).first()
        if row is None:
            return None
        return MostFrequentAircraft(
            icao24=row.icao24, registration=row.registration, sighting_count=row.sighting_count
        )

    async def common_type(self) -> CommonRecord | None:
        """The type code shared by the most distinct sighted airframes."""
        return await self._common(AircraftMetadataResolved.type_code)

    async def common_model(self) -> CommonRecord | None:
        """The model shared by the most distinct sighted airframes."""
        return await self._common(AircraftMetadataResolved.model)

    async def common_operator(self) -> CommonRecord | None:
        """The operator shared by the most distinct sighted airframes."""
        return await self._common(AircraftMetadataResolved.operator_name)

    async def _common(self, column: Any) -> CommonRecord | None:
        """The most frequent non-``null`` value of ``column``, among airframes
        this receiver has actually sighted.

        INNER JOINs to ``aircraft`` deliberately: ``aircraft_metadata_resolved``
        is a whole imported registry (FAA, Mictronics — SPEC §44's rarity
        checks read the same table), most of which this receiver has never
        heard. SPEC §63 asks for records about *this receiver's* lifetime, so
        the population here is airframes it has sighted, not the registry.
        """
        count = func.count(func.distinct(Aircraft.icao24))
        statement = (
            select(column.label("value"), count.label("aircraft_count"))
            .select_from(Aircraft)
            .join(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .where(column.is_not(None))
            .group_by(column)
            .order_by(count.desc(), column.asc())
            .limit(1)
        )
        async with self._database.read_session() as session:
            row = (await session.execute(statement)).first()
        if row is None:
            return None
        return CommonRecord(value=row.value, aircraft_count=row.aircraft_count)


__all__ = [
    "DEFAULT_LOOKBACK_MS",
    "DEFAULT_SIGNAL_BUCKET_WIDTH_DB",
    "MAX_SIGNAL_BUCKET_WIDTH_DB",
    "MIN_SIGNAL_BUCKET_WIDTH_DB",
    "RAW_FIELD_FOR_METRIC",
    "SUMMARY_FIELD_FOR_METRIC",
    "SUMMARY_ONLY_METRICS",
    "CommonRecord",
    "MostFrequentAircraft",
    "ReceiverMetricQueryError",
    "ReceiverStatsRepository",
    "SignalHistogram",
    "SignalHistogramBucket",
    "ever_ranges",
    "next_local_day",
    "signal_histogram",
]
