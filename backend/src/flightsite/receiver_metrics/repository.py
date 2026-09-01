"""Persistence for the receiver-metric tables — the only SQL in this package.

Everything above this module works in
:mod:`flightsite.receiver_metrics.model` values; everything below it is
SQLite. That split is what lets the retention arithmetic be property-tested
without a database and the transaction discipline be tested without arithmetic.

Which writer this is
--------------------

The single-writer discipline (ADR-0001, ADR-0008) is a property of
:meth:`~flightsite.db.engine.Database.writer_session`: it is guarded by an
``asyncio.Lock`` and bound to an engine holding exactly one connection, so
every caller in the process is serialized into one stream of short
transactions. This repository takes that lock like every other writer in
FlightSite — the metadata import and the airport dataset already do — rather
than routing through the sighting worker's cycle, because it shares no row and
no accumulator with it. What it does share is the guarantee: while a metrics
transaction is open, no other write is interleaved with it.

Nothing here is ever awaited by ingestion, by the live store or by an API
request. A stalled disk costs the metrics service a delayed flush and, at
worst, a retried batch.

Transaction boundaries, and why they are where they are
-------------------------------------------------------

* **One flush = one transaction.** The raw samples, the range records they
  produced and the lifetime totals they increment land together. A partial
  landing would mean a lifetime total counting traffic whose samples are not
  there — precisely the drift ADR-0009's "never lose a record" invariant is
  about, in the other direction.
* **The lifetime read happens inside that transaction.** It is a
  read-modify-write of a maximum, so reading it outside would let the
  maintenance pass's own lifetime write slip between the read and the write.
* **Pruning is chunked across transactions.** A catch-up prune after a long
  outage can be tens of thousands of rows; deleting them in one statement
  would hold the writer lock for as long as it takes. Chunks release the lock
  between them, so a sighting flush waiting behind the prune waits for one
  chunk rather than for all of it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db import (
    Database,
    LifetimeStat,
    RangeByBearingDaily,
    ReceiverMetricDaily,
    ReceiverMetricHourly,
    ReceiverMetricRaw,
)
from flightsite.receiver_metrics.lifetime import (
    LifetimeDelta,
    LifetimeValue,
    merged,
    merged_busiest_day,
)
from flightsite.receiver_metrics.model import MetricSample, MetricSummary, RangeRecord

#: Raw rows deleted per transaction during a prune. Sized so an ordinary pass
#: (one interval's worth of expiry, a handful of rows) finishes in one chunk
#: while a catch-up prune after a long outage still releases the writer lock
#: regularly.
PRUNE_CHUNK_ROWS: Final = 2_000

#: Columns of a summary row, in the order the shared shape declares them.
_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "messages_total",
    "positions_total",
    "msgs_per_sec_avg",
    "msgs_per_sec_max",
    "pos_per_sec_avg",
    "pos_per_sec_max",
    "aircraft_avg",
    "aircraft_max",
    "max_range_nm",
    "rssi_avg_db",
    "rssi_peak_db",
    "sample_count",
)

_RAW_FIELDS: Final[tuple[str, ...]] = (
    "messages_per_sec",
    "positions_per_sec",
    "aircraft_visible",
    "aircraft_with_pos",
    "max_range_nm",
    "rssi_avg_db",
    "rssi_peak_db",
)


def _summary_values(summary: MetricSummary) -> dict[str, Any]:
    return {name: getattr(summary, name) for name in _SUMMARY_FIELDS}


def _as_summary(row: Any) -> MetricSummary:
    return MetricSummary(**{name: getattr(row, name) for name in _SUMMARY_FIELDS})


@dataclass(frozen=True, slots=True)
class MetricsRepository:
    """Reads and writes the five tables of ``docs/DATA_MODEL.md`` §6."""

    database: Database

    # ------------------------------------------------------------- the flush

    async def record(
        self,
        samples: Sequence[MetricSample],
        ranges: Mapping[str, Sequence[RangeRecord]],
        delta: LifetimeDelta,
        *,
        at_ms: int,
    ) -> None:
        """Write one flush: raw samples, range records and lifetime increments.

        ``ranges`` is keyed by receiver-local day, because that is the key the
        table is bucketed on and the caller — which knows the configured
        timezone — is where that conversion belongs.

        One transaction for all of it, and it either commits or raises. The
        caller keeps its in-memory state until this returns, so a raise means
        the next flush carries the same work rather than losing it.
        """
        async with self.database.writer_session() as session:
            if samples:
                await self._insert_samples(session, samples)
            for day, records in ranges.items():
                if records:
                    await self._merge_ranges(session, day, records)
            if not delta.is_empty:
                stored = await self._lifetime(session)
                await self._write_lifetime(session, merged(stored, delta), at_ms=at_ms)

    async def _insert_samples(self, session: AsyncSession, samples: Sequence[MetricSample]) -> None:
        """Insert raw rows, replacing any that share a timestamp.

        A repeated ``ts_ms`` means the same instant was sampled twice — a
        clock that did not advance between two ticks, or a retried flush after
        a partial failure. Replacing makes the write idempotent; appending
        would be impossible (the timestamp is the key) and failing would stall
        a flush over a duplicate that carries no new information.
        """
        rows = [
            {"ts_ms": sample.ts_ms, **{name: getattr(sample, name) for name in _RAW_FIELDS}}
            for sample in samples
        ]
        statement = sqlite_insert(ReceiverMetricRaw).values(rows)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["ts_ms"],
                set_={name: getattr(statement.excluded, name) for name in _RAW_FIELDS},
            )
        )

    async def _merge_ranges(
        self, session: AsyncSession, day: str, records: Sequence[RangeRecord]
    ) -> None:
        """Raise each sector's daily record, and only where it was beaten.

        The ``WHERE`` on the conflict clause is what makes this a *record*
        rather than a last-writer-wins overwrite: an aircraft closer in than
        today's best leaves the row exactly as it was, timestamp and
        attribution included.
        """
        rows = [
            {
                "day": day,
                "bearing_bucket": record.bearing_bucket,
                "max_range_nm": record.max_range_nm,
                "at_ms": record.at_ms,
                "icao24": record.icao24,
            }
            for record in records
        ]
        statement = sqlite_insert(RangeByBearingDaily).values(rows)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["day", "bearing_bucket"],
                set_={
                    "max_range_nm": statement.excluded.max_range_nm,
                    "at_ms": statement.excluded.at_ms,
                    "icao24": statement.excluded.icao24,
                },
                where=statement.excluded.max_range_nm > RangeByBearingDaily.max_range_nm,
            )
        )

    # ------------------------------------------------------------ the reads

    async def samples_between(self, start_ms: int, end_ms: int) -> tuple[MetricSample, ...]:
        """Raw samples in ``[start_ms, end_ms)``, ordered by time."""
        statement = (
            select(ReceiverMetricRaw)
            .where(ReceiverMetricRaw.ts_ms >= start_ms, ReceiverMetricRaw.ts_ms < end_ms)
            .order_by(ReceiverMetricRaw.ts_ms)
        )
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            MetricSample(ts_ms=row.ts_ms, **{name: getattr(row, name) for name in _RAW_FIELDS})
            for row in rows
        )

    async def sample_before(self, ts_ms: int) -> MetricSample | None:
        """The last retained sample strictly before ``ts_ms``, if any.

        What the aggregation needs to attribute the first interval of a bucket
        to the traffic it actually measured. ``None`` after a prune has taken
        the predecessor, which is why an already-written summary is never
        recomputed once its raw rows are near the window's edge.
        """
        statement = (
            select(ReceiverMetricRaw)
            .where(ReceiverMetricRaw.ts_ms < ts_ms)
            .order_by(ReceiverMetricRaw.ts_ms.desc())
            .limit(1)
        )
        async with self.database.read_session() as session:
            row = (await session.scalars(statement)).first()
        if row is None:
            return None
        return MetricSample(ts_ms=row.ts_ms, **{name: getattr(row, name) for name in _RAW_FIELDS})

    async def raw_span(self) -> tuple[int, int] | None:
        """``(earliest, latest)`` raw timestamps, or ``None`` if there are none."""
        statement = select(func.min(ReceiverMetricRaw.ts_ms), func.max(ReceiverMetricRaw.ts_ms))
        async with self.database.read_session() as session:
            earliest, latest = (await session.execute(statement)).one()
        if earliest is None or latest is None:
            return None
        return int(earliest), int(latest)

    async def raw_count(self) -> int:
        """How many raw samples are retained."""
        async with self.database.read_session() as session:
            return int(
                await session.scalar(select(func.count()).select_from(ReceiverMetricRaw)) or 0
            )

    async def existing_hours(self, from_ms: int) -> set[int]:
        """Hour buckets at or after ``from_ms`` that already have a summary."""
        statement = select(ReceiverMetricHourly.hour_start_ms).where(
            ReceiverMetricHourly.hour_start_ms >= from_ms
        )
        async with self.database.read_session() as session:
            return {int(value) for value in (await session.scalars(statement)).all()}

    async def existing_days(self, from_day: str) -> set[str]:
        """Local days at or after ``from_day`` that already have a summary."""
        statement = select(ReceiverMetricDaily.day).where(ReceiverMetricDaily.day >= from_day)
        async with self.database.read_session() as session:
            return {str(value) for value in (await session.scalars(statement)).all()}

    async def hourly_between(self, start_ms: int, end_ms: int) -> dict[int, MetricSummary]:
        """Hourly summaries in ``[start_ms, end_ms)``."""
        statement = (
            select(ReceiverMetricHourly)
            .where(
                ReceiverMetricHourly.hour_start_ms >= start_ms,
                ReceiverMetricHourly.hour_start_ms < end_ms,
            )
            .order_by(ReceiverMetricHourly.hour_start_ms)
        )
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return {int(row.hour_start_ms): _as_summary(row) for row in rows}

    async def daily_all(self) -> dict[str, MetricSummary]:
        """Every daily summary, keyed by receiver-local day."""
        statement = select(ReceiverMetricDaily).order_by(ReceiverMetricDaily.day)
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return {str(row.day): _as_summary(row) for row in rows}

    async def ranges_for_day(self, day: str) -> dict[int, RangeRecord]:
        """The stored per-sector records for ``day``, keyed by sector.

        Reconstructed with the sector's midpoint as the bearing: the table
        stores the sector, not the exact bearing that set it (the exact one
        lives on the lifetime record — see
        :class:`~flightsite.receiver_metrics.model.RangeRecord`).
        """
        statement = (
            select(RangeByBearingDaily)
            .where(RangeByBearingDaily.day == day)
            .order_by(RangeByBearingDaily.bearing_bucket)
        )
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return {
            int(row.bearing_bucket): RangeRecord(
                bearing_deg=int(row.bearing_bucket) * 5.0 + 2.5,
                max_range_nm=float(row.max_range_nm),
                at_ms=int(row.at_ms),
                icao24=row.icao24,
            )
            for row in rows
        }

    async def lifetime(self) -> dict[str, LifetimeValue]:
        """Every lifetime record, keyed by statistic name."""
        async with self.database.read_session() as session:
            return await self._lifetime(session)

    async def latest_sample(self) -> MetricSample | None:
        """The most recently retained raw sample, or ``None`` if there are none.

        Slice 034's scorecard (SPEC §61) reads this for "current" messages/sec
        and positions/sec — the most recent tick's own rate, not an average
        over a window.
        """
        statement = select(ReceiverMetricRaw).order_by(ReceiverMetricRaw.ts_ms.desc()).limit(1)
        async with self.database.read_session() as session:
            row = (await session.scalars(statement)).first()
        if row is None:
            return None
        return MetricSample(ts_ms=row.ts_ms, **{name: getattr(row, name) for name in _RAW_FIELDS})

    async def daily_between(self, start_day: str, end_day: str) -> dict[str, MetricSummary]:
        """Daily summaries with ``day`` in ``[start_day, end_day)``.

        Day strings compare lexicographically in the same order as
        chronologically for ``YYYY-MM-DD``, so this is :meth:`hourly_between`'s
        counterpart for the daily tier — slice 034's time-series endpoint uses
        whichever of the two matches the requested resolution.
        """
        statement = (
            select(ReceiverMetricDaily)
            .where(ReceiverMetricDaily.day >= start_day, ReceiverMetricDaily.day < end_day)
            .order_by(ReceiverMetricDaily.day)
        )
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return {str(row.day): _as_summary(row) for row in rows}

    async def ranges_all(self) -> tuple[tuple[str, RangeRecord], ...]:
        """Every stored per-day range record, oldest day first.

        ``range_by_bearing_daily`` is retained indefinitely (§6.3), so this is
        the whole history in one read. Slice 034's polar plot reduces it down
        to one all-time record per sector with
        :func:`~flightsite.api.receiver_stats.ever_ranges`, using the same
        :func:`~flightsite.receiver_metrics.model.better_range` comparison
        production uses so a lifetime maximum can never be recomputed
        differently by the two.
        """
        statement = select(RangeByBearingDaily).order_by(
            RangeByBearingDaily.day, RangeByBearingDaily.bearing_bucket
        )
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            (
                str(row.day),
                RangeRecord(
                    bearing_deg=int(row.bearing_bucket) * 5.0 + 2.5,
                    max_range_nm=float(row.max_range_nm),
                    at_ms=int(row.at_ms),
                    icao24=row.icao24,
                ),
            )
            for row in rows
        )

    # ------------------------------------------------------- the maintenance

    async def write_summaries(
        self,
        hourly: Mapping[int, MetricSummary],
        daily: Mapping[str, MetricSummary],
        *,
        at_ms: int,
    ) -> None:
        """Replace the given hourly and daily summaries, and re-derive the record.

        A full replacement per bucket, never an accumulation, which is what
        makes re-running a downsampling pass over the same raw rows a no-op
        (ADR-0009: *"Downsampling is idempotent so crash/restart cannot
        double-count"*).

        The busiest-day record is updated in the same transaction as the daily
        rows it is derived from, so the two can never disagree.
        """
        if not hourly and not daily:
            return
        async with self.database.writer_session() as session:
            if hourly:
                statement = sqlite_insert(ReceiverMetricHourly).values(
                    [
                        {"hour_start_ms": hour, **_summary_values(summary)}
                        for hour, summary in sorted(hourly.items())
                    ]
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["hour_start_ms"],
                        set_={name: getattr(statement.excluded, name) for name in _SUMMARY_FIELDS},
                    )
                )
            if daily:
                statement = sqlite_insert(ReceiverMetricDaily).values(
                    [
                        {"day": day, **_summary_values(summary)}
                        for day, summary in sorted(daily.items())
                    ]
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["day"],
                        set_={name: getattr(statement.excluded, name) for name in _SUMMARY_FIELDS},
                    )
                )
                stored = await self._lifetime(session)
                totals = {day: summary.messages_total for day, summary in daily.items()}
                await self._write_lifetime(session, merged_busiest_day(stored, totals), at_ms=at_ms)

    async def prune_raw(self, before_ms: int, *, chunk_rows: int = PRUNE_CHUNK_ROWS) -> int:
        """Delete raw samples older than ``before_ms``; return how many went.

        Chunked across transactions so the writer lock is released between
        chunks — see the module docstring. The boundary is exclusive: a sample
        stamped exactly at ``before_ms`` is inside the window and stays.
        """
        if chunk_rows < 1:
            raise ValueError("chunk_rows must be at least one")

        removed = 0
        while True:
            async with self.database.writer_session() as session:
                expired = list(
                    (
                        await session.scalars(
                            select(ReceiverMetricRaw.ts_ms)
                            .where(ReceiverMetricRaw.ts_ms < before_ms)
                            .order_by(ReceiverMetricRaw.ts_ms)
                            .limit(chunk_rows)
                        )
                    ).all()
                )
                if expired:
                    await session.execute(
                        delete(ReceiverMetricRaw).where(ReceiverMetricRaw.ts_ms.in_(expired))
                    )
            removed += len(expired)
            if len(expired) < chunk_rows:
                return removed

    # -------------------------------------------------------------- helpers

    @staticmethod
    async def _lifetime(session: AsyncSession) -> dict[str, LifetimeValue]:
        rows = (await session.scalars(select(LifetimeStat))).all()
        return {
            str(row.key): LifetimeValue(value_num=row.value_num, value_text=row.value_text)
            for row in rows
        }

    @staticmethod
    async def _write_lifetime(
        session: AsyncSession, updates: Mapping[str, LifetimeValue], *, at_ms: int
    ) -> None:
        if not updates:
            return
        statement = sqlite_insert(LifetimeStat).values(
            [
                {
                    "key": key,
                    "value_num": value.value_num,
                    "value_text": value.value_text,
                    "updated_ms": at_ms,
                }
                for key, value in sorted(updates.items())
            ]
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value_num": statement.excluded.value_num,
                    "value_text": statement.excluded.value_text,
                    "updated_ms": statement.excluded.updated_ms,
                },
            )
        )


def group_by_day(records: Iterable[tuple[str, RangeRecord]]) -> dict[str, list[RangeRecord]]:
    """Collect ``(day, record)`` pairs into the per-day mapping :meth:`record` takes."""
    grouped: dict[str, list[RangeRecord]] = {}
    for day, record in records:
        grouped.setdefault(day, []).append(record)
    return grouped


__all__ = ["PRUNE_CHUNK_ROWS", "MetricsRepository", "group_by_day"]
