"""Writing years of synthetic history into a real FlightSite database.

:class:`HistoryGenerator` turns the traffic model in :mod:`.traffic` into rows
in the actual schema, through the actual :class:`~flightsite.db.Database`, under
the actual single-writer discipline (ADR-0001/ADR-0008). Nothing here reaches
around the application to a private connection: a generator that wrote through
a side channel would be qualifying storage the product does not use.

Why it writes rows rather than driving the pipeline
---------------------------------------------------

Slice 049's harness drives the real ingestion pipeline one 1 Hz tick at a time,
which is the only honest way to measure that pipeline. It is also, for this
slice, arithmetically impossible: three years is ninety-five million ticks, and
at the product's own cadence the dataset would take three years to build.

So this generator writes the *result* of that pipeline — the rows a persistence
worker would have committed — directly. That makes fidelity the whole game, and
it is enforced rather than asserted: ``tests/perf/storage/test_fidelity.py``
checks the generated rows against the cross-table invariants the production
writer maintains (``docs/DATA_MODEL.md`` §2, ADR-0005), so a synthetic database
is one the product could have produced, not merely one of the right size.

Two things are deliberately *not* faked, because production code exists to do
them and running it is worth more than reproducing it:

* **Analytics rollups** are built by the real
  :class:`~flightsite.analytics.backfill.AnalyticsBackfill` over the generated
  sightings. They are therefore consistent with the history by construction,
  and the cost of building them is itself a multi-year figure worth reporting.
* **Receiver-metric downsampling and pruning** are left to the real
  :class:`~flightsite.receiver_metrics.service.ReceiverMetricsService`. The
  generator seeds a deliberate backlog of high-resolution rows (see
  :attr:`GenerationConfig.high_res_backlog_days`) so that a qualification run
  has something for that code to actually prune.

Per-table byte attribution
--------------------------

``dbstat`` — SQLite's per-table page accounting — is a compile-time option and
is absent from the interpreter this suite runs on, so table sizes are measured
by difference instead: each day's rows are written in table order inside one
transaction, and ``PRAGMA page_count`` is read between phases. The delta across
a phase is the pages that phase caused SQLite to allocate, which counts the
table *and its indexes* — the number an operator actually cares about, and the
one ``docs/DATA_MODEL.md`` §9's per-row estimates are implicitly against.

The measurement is sound here because the database starts empty and is never
deleted from during generation, so ``page_count`` only ever grows and no phase
can be credited with pages recycled from another's freelist. It is an
attribution, not an audit: a page that a later phase's B-tree split happens to
claim is charged to the phase that allocated it.

Writing one day per transaction also keeps the on-disk interleaving honest. A
generator that wrote every sighting, then every track, then every event would
produce a far more clustered file than a receiver does, and would flatter every
query measured against it.
"""

from __future__ import annotations

import json
import math
import random
import time
from array import array
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db import Database
from flightsite.db.models import (
    ActivityEvent,
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    AlertMatch,
    LifetimeStat,
    Meta,
    OperatorGroup,
    RangeByBearingDaily,
    ReceiverMetricDaily,
    ReceiverMetricHourly,
    ReceiverMetricRaw,
    Sighting,
    SightingEvent,
    SightingTrack,
)
from flightsite.perf.storage_qualification.scenarios import METRIC_SAMPLES_PER_DAY, Scenario
from flightsite.perf.storage_qualification.traffic import (
    AircraftPool,
    SyntheticSighting,
    TrackPool,
    sightings_for_day,
    sightings_on,
)

#: Seed for every random decision. Fixed so a growth figure is comparable
#: between runs and a change in it means a change in the product.
DEFAULT_SEED: Final = 20_500

#: Days of high-resolution receiver telemetry seeded *beyond* the retention
#: window, representing a receiver whose maintenance pass has not run for a
#: while — a restart, a busy period, an owner who had the Pi switched off.
#: Without a backlog there is nothing for the prune to prune and the retention
#: measurement would be of a no-op.
DEFAULT_HIGH_RES_BACKLOG_DAYS: Final = 7

#: Rows per ``executemany``. Large enough to amortize the round trip, small
#: enough that a day of the design envelope does not build one enormous
#: parameter list.
DEFAULT_BATCH_ROWS: Final = 5_000

#: Curated operator groupings. A real install has tens, not thousands: the
#: grouping is editorial (``docs/DATA_MODEL.md`` §3.5), and it is what
#: ``daily_operator_stats`` and the top-operators analytics rank over.
OPERATOR_GROUP_COUNT: Final = 40

#: Bearing sectors in ``range_by_bearing_daily``: 72 sectors of 5 degrees
#: (``flightsite.receiver_metrics``' ``BEARING_BUCKETS``).
BEARING_BUCKETS: Final = 72

#: Milliseconds in a day and an hour, spelled once.
MS_PER_HOUR: Final = 3_600_000
MS_PER_DAY: Final = 86_400_000

#: Sentinel for an integer accumulator that has never been set. Chosen far
#: outside any altitude so it can never be confused with a real reading.
_INT_UNSET: Final = -(2**62)

#: Sighting-event types, weighted the way a real sighting produces them.
_EVENT_TYPES: Final[tuple[tuple[str, float], ...]] = (
    ("callsign_change", 0.34),
    ("squawk_change", 0.24),
    ("route_enriched", 0.16),
    ("classification_available", 0.14),
    ("alert_matched", 0.08),
    ("alert_severity_upgraded", 0.04),
)

#: Activity-feed event types this generator emits (the vocabulary is open —
#: ``flightsite.activity.model.ActivityEventType``).
_ACTIVITY_TYPES: Final[tuple[str, ...]] = (
    "first_ever_sighting",
    "rare_aircraft",
    "range_record",
    "milestone",
    "alert_match",
)


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """How much history to synthesize, and with what character.

    Args:
        scenario: which ``docs/DATA_MODEL.md`` §9 receiver to model.
        days: days of history to generate, ending at :attr:`end`.
        seed: drives every random decision, in a fixed order.
        end: the instant history runs up to; defaults to now. History covering
            the present is what makes the ``today``/``7d``/``30d`` analytics
            presets return anything, so a qualification run measures the
            queries a user actually issues rather than empty windows.
        high_res_backlog_days: high-resolution telemetry seeded beyond the
            retention window, for the prune to clear.
        timezone: IANA zone the analytics rollups bucket local days by.
        build_rollups: run the real analytics backfill over the generated
            history. Only turned off by tests measuring the generator alone.
        batch_rows: rows per ``executemany``.
    """

    scenario: Scenario
    days: int
    seed: int = DEFAULT_SEED
    end: datetime | None = None
    high_res_backlog_days: int = DEFAULT_HIGH_RES_BACKLOG_DAYS
    timezone: str = "UTC"
    build_rollups: bool = True
    batch_rows: int = DEFAULT_BATCH_ROWS

    def __post_init__(self) -> None:
        if self.days < 1:
            raise ValueError("days must be at least 1")
        if self.high_res_backlog_days < 0:
            raise ValueError("high_res_backlog_days cannot be negative")
        if self.batch_rows < 1:
            raise ValueError("batch_rows must be at least 1")

    @property
    def end_at(self) -> datetime:
        """The instant history runs up to, as an aware UTC datetime."""
        return self.end if self.end is not None else datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TableGrowth:
    """What one table (and its indexes) cost on disk.

    Args:
        table: the table name, as ``docs/DATA_MODEL.md`` spells it.
        rows: rows the generator wrote.
        bytes: pages the writes allocated, times the page size.
    """

    table: str
    rows: int
    bytes: int

    @property
    def bytes_per_row(self) -> float:
        """On-disk cost of one row, including its share of the indexes."""
        return self.bytes / self.rows if self.rows else 0.0


@dataclass(slots=True)
class GenerationResult:
    """Everything one generation run produced and what it cost.

    Args:
        config: the run that was asked for.
        days: days of history actually written.
        sightings: sighting rows written.
        aircraft: distinct airframes created.
        track_points: points across every packed track.
        tracks: packed track rows written (fewer than ``sightings``: a Mode S
            aircraft that never reports a position gets no track row).
        growth: per-table byte attribution, in write order.
        db_bytes: size of the database file at the end.
        wal_bytes: size of the write-ahead log at the end.
        page_size: SQLite page size, for turning pages back into bytes.
        duration_s: wall-clock time generating and writing history.
        rollup_s: of which, the real analytics backfill.
    """

    config: GenerationConfig
    days: int = 0
    sightings: int = 0
    aircraft: int = 0
    track_points: int = 0
    tracks: int = 0
    growth: tuple[TableGrowth, ...] = ()
    db_bytes: int = 0
    wal_bytes: int = 0
    page_size: int = 0
    duration_s: float = 0.0
    rollup_s: float = 0.0
    rollup_days: int = 0

    @property
    def bytes_per_sighting(self) -> float:
        """The scale-free growth figure ``budgets.py`` judges (§9's arithmetic)."""
        return self.db_bytes / self.sightings if self.sightings else 0.0

    @property
    def mean_track_points(self) -> float:
        """Points per packed track — ``docs/DATA_MODEL.md`` §9 sizes at ~60."""
        return self.track_points / self.tracks if self.tracks else 0.0

    def table(self, name: str) -> TableGrowth | None:
        """Growth attributed to one table, or ``None`` if it was not written."""
        for entry in self.growth:
            if entry.table == name:
                return entry
        return None


@dataclass(slots=True)
class _Accumulators:
    """Per-airframe lifetime aggregates, kept compactly.

    ``array`` rather than lists of Python objects: three years of the design
    envelope creates six hundred thousand airframes, and a dozen boxed integers
    each would cost hundreds of megabytes for information that fits in tens.
    The generator has to hold this for the whole run because
    ``aircraft.sighting_count`` and the lifetime records are only final once
    the last day has been written.
    """

    first_seen: array[int] = field(default_factory=lambda: array("q"))
    last_seen: array[int] = field(default_factory=lambda: array("q"))
    sighting_count: array[int] = field(default_factory=lambda: array("l"))
    total_observed: array[int] = field(default_factory=lambda: array("q"))
    closest_nm: array[float] = field(default_factory=lambda: array("d"))
    closest_ms: array[int] = field(default_factory=lambda: array("q"))
    max_range_nm: array[float] = field(default_factory=lambda: array("d"))
    max_range_ms: array[int] = field(default_factory=lambda: array("q"))
    lowest_alt: array[int] = field(default_factory=lambda: array("q"))
    lowest_alt_ms: array[int] = field(default_factory=lambda: array("q"))
    highest_alt: array[int] = field(default_factory=lambda: array("q"))
    highest_alt_ms: array[int] = field(default_factory=lambda: array("q"))

    def extend_to(self, size: int) -> None:
        """Grow every accumulator so index ``size - 1`` is addressable."""
        while len(self.first_seen) < size:
            self.first_seen.append(0)
            self.last_seen.append(0)
            self.sighting_count.append(0)
            self.total_observed.append(0)
            self.closest_nm.append(math.nan)
            self.closest_ms.append(0)
            self.max_range_nm.append(math.nan)
            self.max_range_ms.append(0)
            self.lowest_alt.append(_INT_UNSET)
            self.lowest_alt_ms.append(0)
            self.highest_alt.append(_INT_UNSET)
            self.highest_alt_ms.append(0)

    def record(self, sighting: SyntheticSighting) -> None:
        """Fold one sighting into its airframe's lifetime aggregates.

        Mirrors ``SightingRepository._merge_records``: a record moves only on a
        strictly better value, and its ``_ms`` companion moves with it, so the
        UI can always say *when* a record was set.
        """
        index = sighting.airframe
        self.sighting_count[index] += 1
        self.total_observed[index] += sighting.duration_ms
        if self.first_seen[index] == 0 or sighting.started_ms < self.first_seen[index]:
            self.first_seen[index] = sighting.started_ms
        if sighting.ended_ms > self.last_seen[index]:
            self.last_seen[index] = sighting.ended_ms

        near = sighting.closest_approach_nm
        if near is not None and (
            math.isnan(self.closest_nm[index]) or near < self.closest_nm[index]
        ):
            self.closest_nm[index] = near
            self.closest_ms[index] = sighting.started_ms
        far = sighting.max_range_nm
        if far is not None and (
            math.isnan(self.max_range_nm[index]) or far > self.max_range_nm[index]
        ):
            self.max_range_nm[index] = far
            self.max_range_ms[index] = sighting.started_ms
        low = sighting.lowest_alt_ft
        if low is not None and (
            self.lowest_alt[index] == _INT_UNSET or low < self.lowest_alt[index]
        ):
            self.lowest_alt[index] = low
            self.lowest_alt_ms[index] = sighting.started_ms
        high = sighting.highest_alt_ft
        if high is not None and (
            self.highest_alt[index] == _INT_UNSET or high > self.highest_alt[index]
        ):
            self.highest_alt[index] = high
            self.highest_alt_ms[index] = sighting.started_ms


class HistoryGenerator:
    """Generates and writes a synthetic multi-year history.

    Args:
        database: the real application database, already migrated to head.
        config: how much history, and of what character.
    """

    def __init__(self, database: Database, config: GenerationConfig) -> None:
        self._database = database
        self._config = config
        self._rng = random.Random(config.seed)
        self._pool = AircraftPool(config.scenario.unique_aircraft_per_day, rng=self._rng)
        self._tracks = TrackPool(rng=self._rng)
        self._totals = _Accumulators()
        self._pages: dict[str, int] = {}
        self._rows: dict[str, int] = {}
        self._order: list[str] = []
        self._page_size = 4096
        self._page_size_known = False
        self._alert_rows: list[dict[str, Any]] = []
        self._next_sighting_id = 1
        self._next_event_id = 1
        self._next_activity_id = 1
        self._next_match_id = 1
        self._sightings_written = 0
        self._tracks_written = 0
        self._points_written = 0

    # ------------------------------------------------------------ measurement

    async def _page_count(self, session: AsyncSession) -> int:
        """Pages the database currently occupies, including this transaction's."""
        result = await session.execute(text("PRAGMA page_count"))
        return int(result.scalar_one())

    async def _mark(self, session: AsyncSession, table: str, rows: int, before: int) -> int:
        """Attribute pages allocated since ``before`` to ``table``.

        Returns the new page count so the caller can chain phases without a
        second read.
        """
        after = await self._page_count(session)
        if table not in self._pages:
            self._pages[table] = 0
            self._rows[table] = 0
            self._order.append(table)
        self._pages[table] += after - before
        self._rows[table] += rows
        return after

    async def _insert(
        self, session: AsyncSession, model: type[Any], rows: list[dict[str, Any]]
    ) -> None:
        """``executemany`` in batches, skipping the call entirely when empty."""
        if not rows:
            return
        size = self._config.batch_rows
        for start in range(0, len(rows), size):
            await session.execute(insert(model), rows[start : start + size])

    # -------------------------------------------------------------- the parts

    def _callsign(self, prefix: str) -> str:
        return f"{prefix}{self._rng.randrange(1, 4000)}"

    def _sighting_rows(
        self, day: list[SyntheticSighting]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Build one day's ``sightings``, ``sighting_tracks`` and event rows."""
        sightings: list[dict[str, Any]] = []
        tracks: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        for sighting in day:
            sighting_id = self._next_sighting_id
            self._next_sighting_id += 1
            airframe = self._pool.airframes[sighting.airframe]
            callsign = self._callsign(airframe.callsign_prefix)
            changed = self._rng.random() < 0.18
            duration = sighting.duration_ms

            sightings.append(
                {
                    "id": sighting_id,
                    "aircraft_id": sighting.airframe + 1,
                    "started_ms": sighting.started_ms,
                    "ended_ms": sighting.ended_ms,
                    "duration_ms": duration,
                    "closure_reason": "gap_timeout",
                    "callsign_first": callsign,
                    "callsign_last": self._callsign(airframe.callsign_prefix)
                    if changed
                    else callsign,
                    "squawk_last": sighting.squawk,
                    "had_emergency": int(sighting.had_emergency),
                    "origin_ident": None,
                    "destination_ident": None,
                    "route_source": None,
                    "inferred_airport_ident": None,
                    "inferred_phase": None,
                    "any_position": int(sighting.any_position),
                    "mlat_used": int(sighting.mlat_used),
                    "ground_seen": int(sighting.ground_seen),
                    "msg_count": sighting.msg_count,
                    "pos_count": sighting.pos_count,
                    "rssi_peak_db": sighting.rssi_peak_db,
                    "rssi_avg_db": sighting.rssi_avg_db,
                    "rssi_min_db": sighting.rssi_min_db,
                    # Positioned time as a percentage of the sighting, exactly
                    # as ActiveSighting computes it: never above 100, and NULL
                    # when there is no duration to be a percentage of.
                    "pos_time_pct": (
                        min(100.0, sighting.pos_count * 1_000.0 * 100.0 / duration)
                        if sighting.any_position and duration > 0
                        else None
                    ),
                    "closest_approach_nm": sighting.closest_approach_nm,
                    "max_range_nm": sighting.max_range_nm,
                    "lowest_alt_ft": sighting.lowest_alt_ft,
                    "highest_alt_ft": sighting.highest_alt_ft,
                    "max_alert_severity": sighting.alert_severity,
                }
            )

            if sighting.any_position and sighting.track_points >= 2:
                packed = self._tracks.blob_for(sighting.track_points)
                tracks.append(
                    {
                        "sighting_id": sighting_id,
                        "encoding_version": packed.encoding_version,
                        "point_count": packed.point_count,
                        "started_ms": sighting.started_ms,
                        "points_blob": packed.points_blob,
                    }
                )
                self._tracks_written += 1
                self._points_written += packed.point_count

            for _ in range(sighting.event_count):
                kind = self._rng.choices(
                    [name for name, _ in _EVENT_TYPES],
                    weights=[weight for _, weight in _EVENT_TYPES],
                    k=1,
                )[0]
                events.append(
                    {
                        "id": self._next_event_id,
                        "sighting_id": sighting_id,
                        "ts_ms": sighting.started_ms + self._rng.randrange(0, max(1, duration)),
                        "type": kind,
                        "payload_json": json.dumps(
                            {"to": callsign}, separators=(",", ":"), sort_keys=True
                        ),
                    }
                )
                self._next_event_id += 1

            # An alert match is the source of truth behind
            # sightings.max_alert_severity, so one is written exactly when that
            # column is set (docs/DATA_MODEL.md §4.3).
            if sighting.alert_severity is not None:
                self._alert_rows.append(
                    {
                        "id": self._next_match_id,
                        "rule_id": None,
                        "builtin_key": "emergency_squawk"
                        if sighting.had_emergency
                        else "watchlist_hit",
                        "sighting_id": sighting_id,
                        "aircraft_id": sighting.airframe + 1,
                        "matched_ms": sighting.started_ms + 1,
                        "severity": sighting.alert_severity,
                        "reason": "synthetic qualification match",
                        "notified": 0,
                    }
                )
                self._next_match_id += 1

            self._totals.record(sighting)

        self._sightings_written += len(sightings)
        return sightings, tracks, events

    def _activity_rows(self, day_start_ms: int, count: int) -> list[dict[str, Any]]:
        """One day of activity-feed rows, each with a unique dedupe key."""
        rows: list[dict[str, Any]] = []
        for _ in range(count):
            identifier = self._next_activity_id
            self._next_activity_id += 1
            rows.append(
                {
                    "id": identifier,
                    "ts_ms": day_start_ms + self._rng.randrange(0, MS_PER_DAY),
                    "type": self._rng.choice(_ACTIVITY_TYPES),
                    "severity": self._rng.choices(
                        ("info", "interesting", "high"), weights=(7, 3, 1), k=1
                    )[0],
                    "aircraft_id": None,
                    "sighting_id": None,
                    "payload_json": None,
                    "dedupe_key": f"synthetic-{identifier}",
                }
            )
        return rows

    def _bearing_rows(self, day: str, day_start_ms: int) -> list[dict[str, Any]]:
        """The day's range record per 5-degree bearing sector."""
        return [
            {
                "day": day,
                "bearing_bucket": bucket,
                "max_range_nm": self._rng.uniform(40.0, 250.0),
                "at_ms": day_start_ms + self._rng.randrange(0, MS_PER_DAY),
                "icao24": self._pool.airframes[self._rng.randrange(self._pool.size)].icao24
                if self._pool.size
                else None,
            }
            for bucket in range(BEARING_BUCKETS)
        ]

    # ------------------------------------------------------------------- run

    async def run(self) -> GenerationResult:
        """Generate the history and return what it cost."""
        started = time.perf_counter()
        config = self._config
        scenario = config.scenario
        zone = ZoneInfo(config.timezone)
        end = config.end_at.astimezone(zone)
        last_day = end.date()
        first_day = last_day - timedelta(days=config.days - 1)
        alert_share = scenario.alert_matches_per_day / scenario.sightings_per_day

        await self._write_operator_groups()

        day_names: list[str] = []
        new_carry = 0.0
        for offset in range(config.days):
            current = first_day + timedelta(days=offset)
            day_names.append(current.isoformat())
            day_start = datetime(current.year, current.month, current.day, tzinfo=zone).astimezone(
                UTC
            )
            day_start_ms = int(day_start.timestamp() * 1_000)

            new_carry += scenario.new_aircraft_per_day
            new_today = int(new_carry)
            new_carry -= new_today

            # Everything minted while drawing this day has to be inserted, not
            # just the planned first-ever contacts: a young pool also mints the
            # shortfall when it cannot yet offer enough distinct airframes, and
            # missing those would leave the day's sightings pointing at
            # aircraft rows that do not exist.
            known_airframes = self._pool.size
            airframes = self._pool.draw_day(
                unique_today=scenario.unique_aircraft_per_day, new_today=new_today
            )
            self._totals.extend_to(self._pool.size)

            day = sightings_for_day(
                self._rng,
                day_start_ms=day_start_ms,
                airframes=airframes,
                sightings_today=sightings_on(
                    current.weekday(), daily_average=scenario.sightings_per_day
                ),
                alert_share=alert_share,
            )
            await self._write_day(
                day=day,
                day_name=current.isoformat(),
                day_start_ms=day_start_ms,
                known_airframes=known_airframes,
            )

        await self._finalize_aircraft()
        await self._write_receiver_metrics(last_day=last_day, zone=zone, day_names=day_names)
        await self._write_meta()

        rollup_s = 0.0
        rollup_days = 0
        if config.build_rollups:
            rollup_s, rollup_days = await self._build_rollups(day_names, zone)

        return await self._result(started, rollup_s, rollup_days)

    async def _write_operator_groups(self) -> None:
        """The curated operator groupings the analytics rank over."""
        async with self._database.writer_session() as session:
            await self._insert(
                session,
                OperatorGroup,
                [
                    {
                        "id": index + 1,
                        "slug": f"group-{index + 1:03d}",
                        "name": f"Operator {index + 1}",
                    }
                    for index in range(OPERATOR_GROUP_COUNT)
                ],
            )

    async def _write_day(
        self,
        *,
        day: list[SyntheticSighting],
        day_name: str,
        day_start_ms: int,
        known_airframes: int,
    ) -> None:
        """Write one day of history in one transaction, phase by phase.

        The phase order is the foreign-key order — airframes before the
        sightings that reference them, sightings before their tracks and events
        — which is also the order production creates them in.
        """
        self._alert_rows = []
        sightings, tracks, events = self._sighting_rows(day)
        activity = self._activity_rows(day_start_ms, self._config.scenario.activity_events_per_day)
        matches = self._alert_rows

        aircraft_rows: list[dict[str, Any]] = []
        metadata_rows: list[dict[str, Any]] = []
        classification_rows: list[dict[str, Any]] = []
        for index in range(known_airframes, self._pool.size):
            airframe = self._pool.airframes[index]
            aircraft_rows.append(
                {
                    "id": index + 1,
                    "icao24": airframe.icao24,
                    # Placeholders: the real aggregates are only final once the
                    # last day is written, and are applied by
                    # _finalize_aircraft. Production updates these rows
                    # continuously too, so the resulting page churn is faithful.
                    "first_seen_ms": day_start_ms,
                    "last_seen_ms": day_start_ms,
                    "sighting_count": 0,
                    "total_observed_ms": 0,
                }
            )
            if airframe.type_code is not None:
                metadata_rows.append(
                    {
                        "icao24": airframe.icao24,
                        "registration": f"G-{airframe.icao24[:4].upper()}",
                        "registration_src": "synthetic",
                        "type_code": airframe.type_code,
                        "type_code_src": "synthetic",
                        "model": None,
                        "model_src": None,
                        "manufacture_year": None,
                        "year_src": None,
                        "operator_name": f"Operator {index % OPERATOR_GROUP_COUNT + 1}",
                        "operator_src": "synthetic",
                        "operator_group_id": index % OPERATOR_GROUP_COUNT + 1,
                        "owner": None,
                        "owner_src": None,
                        "updated_ms": day_start_ms,
                    }
                )
            if airframe.military or airframe.government:
                classification_rows.append(
                    {
                        "icao24": airframe.icao24,
                        "military": int(airframe.military),
                        "military_src": "synthetic" if airframe.military else None,
                        "military_conf": 0.9 if airframe.military else None,
                        "government": int(airframe.government),
                        "government_src": "synthetic" if airframe.government else None,
                        "government_conf": 0.9 if airframe.government else None,
                        "law_enforcement": 0,
                        "law_enforcement_src": None,
                        "law_enforcement_conf": None,
                        "mission_category": "military" if airframe.military else "government",
                        "mission_src": "synthetic",
                        "updated_ms": day_start_ms,
                    }
                )

        async with self._database.writer_session() as session:
            if not self._page_size_known:
                result = await session.execute(text("PRAGMA page_size"))
                self._page_size = int(result.scalar_one())
                self._page_size_known = True

            mark = await self._page_count(session)
            await self._insert(session, Aircraft, aircraft_rows)
            mark = await self._mark(session, "aircraft", len(aircraft_rows), mark)
            await self._insert(session, AircraftMetadataResolved, metadata_rows)
            mark = await self._mark(session, "aircraft_metadata_resolved", len(metadata_rows), mark)
            await self._insert(session, AircraftClassification, classification_rows)
            mark = await self._mark(
                session, "aircraft_classification", len(classification_rows), mark
            )
            await self._insert(session, Sighting, sightings)
            mark = await self._mark(session, "sightings", len(sightings), mark)
            await self._insert(session, SightingTrack, tracks)
            mark = await self._mark(session, "sighting_tracks", len(tracks), mark)
            await self._insert(session, SightingEvent, events)
            mark = await self._mark(session, "sighting_events", len(events), mark)
            await self._insert(session, AlertMatch, matches)
            mark = await self._mark(session, "alert_matches", len(matches), mark)
            await self._insert(session, ActivityEvent, activity)
            mark = await self._mark(session, "activity_events", len(activity), mark)
            bearing = self._bearing_rows(day_name, day_start_ms)
            await self._insert(session, RangeByBearingDaily, bearing)
            await self._mark(session, "range_by_bearing_daily", len(bearing), mark)

    async def _finalize_aircraft(self) -> None:
        """Apply the accumulated lifetime aggregates to every airframe."""
        totals = self._totals
        rows: list[dict[str, Any]] = []
        for index in range(self._pool.size):
            rows.append(
                {
                    "id": index + 1,
                    "first_seen_ms": totals.first_seen[index],
                    "last_seen_ms": totals.last_seen[index],
                    "sighting_count": totals.sighting_count[index],
                    "total_observed_ms": totals.total_observed[index],
                    "closest_approach_nm": None
                    if math.isnan(totals.closest_nm[index])
                    else totals.closest_nm[index],
                    "closest_approach_ms": totals.closest_ms[index] or None,
                    "max_range_nm": None
                    if math.isnan(totals.max_range_nm[index])
                    else totals.max_range_nm[index],
                    "max_range_ms": totals.max_range_ms[index] or None,
                    "lowest_alt_ft": None
                    if totals.lowest_alt[index] == _INT_UNSET
                    else totals.lowest_alt[index],
                    "lowest_alt_ms": totals.lowest_alt_ms[index] or None,
                    "highest_alt_ft": None
                    if totals.highest_alt[index] == _INT_UNSET
                    else totals.highest_alt[index],
                    "highest_alt_ms": totals.highest_alt_ms[index] or None,
                }
            )

        size = self._config.batch_rows
        async with self._database.writer_session() as session:
            for start in range(0, len(rows), size):
                await session.execute(update(Aircraft), rows[start : start + size])

    async def _write_receiver_metrics(
        self, *, last_day: date, zone: ZoneInfo, day_names: list[str]
    ) -> None:
        """Seed receiver telemetry in the state a running install would be in.

        Hourly and daily summaries cover the whole history; high-resolution raw
        samples cover only the recent window *plus* a deliberate backlog. That
        is a receiver whose maintenance pass has fallen behind — the state that
        gives :meth:`ReceiverMetricsService.run_maintenance` something real to
        downsample and prune, which is what SPEC §86's retention and
        downsampling items are asking about.
        """
        config = self._config
        window_days = config.high_res_backlog_days + 14
        end = datetime(last_day.year, last_day.month, last_day.day, tzinfo=zone) + timedelta(days=1)
        # Floored to a UTC hour start. `receiver_metrics_hourly` is keyed by
        # `hour_start_ms`, and `run_maintenance` replaces a bucket by that key:
        # rows seeded on a boundary the aggregator would never compute would be
        # written *alongside* the recomputed ones instead of being replaced,
        # leaving two summaries for one hour. Local midnight is a whole hour in
        # UTC for most zones but not all, so it is floored rather than assumed.
        end_ms = int(end.astimezone(UTC).timestamp() * 1_000) // MS_PER_HOUR * MS_PER_HOUR

        raw_rows: list[dict[str, Any]] = []
        interval_ms = MS_PER_DAY // METRIC_SAMPLES_PER_DAY
        start_ms = end_ms - window_days * MS_PER_DAY
        timestamp = start_ms
        while timestamp < end_ms:
            hour = (timestamp // MS_PER_HOUR) % 24
            busy = 0.35 + 0.65 * math.sin(math.pi * max(0.0, (hour - 4) / 18.0)) ** 2
            raw_rows.append(
                {
                    "ts_ms": timestamp,
                    "messages_per_sec": 320.0 * busy * self._rng.uniform(0.85, 1.15),
                    "positions_per_sec": 48.0 * busy * self._rng.uniform(0.85, 1.15),
                    "aircraft_visible": int(120 * busy * self._rng.uniform(0.8, 1.2)),
                    "aircraft_with_pos": int(96 * busy * self._rng.uniform(0.8, 1.2)),
                    "max_range_nm": self._rng.uniform(150.0, 250.0),
                    "rssi_avg_db": self._rng.uniform(-22.0, -14.0),
                    "rssi_peak_db": self._rng.uniform(-8.0, -2.0),
                }
            )
            timestamp += interval_ms

        # Summaries stop where the backlog begins: everything after that is
        # what the maintenance pass has yet to catch up on.
        summarized_days = max(0, len(day_names) - config.high_res_backlog_days)
        hourly_rows: list[dict[str, Any]] = []
        daily_rows: list[dict[str, Any]] = []
        history_start_ms = end_ms - len(day_names) * MS_PER_DAY
        for offset in range(summarized_days):
            day_start = history_start_ms + offset * MS_PER_DAY
            for hour in range(24):
                hourly_rows.append(
                    self._summary_row(
                        {"hour_start_ms": day_start + hour * MS_PER_HOUR}, samples=240
                    )
                )
            daily_rows.append(
                self._summary_row({"day": day_names[offset]}, samples=METRIC_SAMPLES_PER_DAY)
            )

        async with self._database.writer_session() as session:
            mark = await self._page_count(session)
            await self._insert(session, ReceiverMetricRaw, raw_rows)
            mark = await self._mark(session, "receiver_metrics_raw", len(raw_rows), mark)
            await self._insert(session, ReceiverMetricHourly, hourly_rows)
            mark = await self._mark(session, "receiver_metrics_hourly", len(hourly_rows), mark)
            await self._insert(session, ReceiverMetricDaily, daily_rows)
            mark = await self._mark(session, "receiver_metrics_daily", len(daily_rows), mark)
            await self._insert(session, LifetimeStat, self._lifetime_rows(end_ms))
            await self._mark(session, "lifetime_stats", 11, mark)

    def _summary_row(self, key: dict[str, Any], *, samples: int) -> dict[str, Any]:
        """One hourly or daily receiver summary, keyed by whatever ``key`` says."""
        return {
            **key,
            "messages_total": int(320 * samples * 15 * self._rng.uniform(0.8, 1.2)),
            "positions_total": int(48 * samples * 15 * self._rng.uniform(0.8, 1.2)),
            "msgs_per_sec_avg": self._rng.uniform(240.0, 400.0),
            "msgs_per_sec_max": self._rng.uniform(400.0, 620.0),
            "pos_per_sec_avg": self._rng.uniform(36.0, 60.0),
            "pos_per_sec_max": self._rng.uniform(60.0, 95.0),
            "aircraft_avg": self._rng.uniform(60.0, 140.0),
            "aircraft_max": self._rng.randrange(140, 260),
            "max_range_nm": self._rng.uniform(160.0, 250.0),
            "rssi_avg_db": self._rng.uniform(-22.0, -14.0),
            "rssi_peak_db": self._rng.uniform(-8.0, -2.0),
            "sample_count": samples,
        }

    def _lifetime_rows(self, now_ms: int) -> list[dict[str, Any]]:
        """The eleven lifetime aggregates ADR-0009 says must never be lost."""
        icao = self._pool.airframes[0].icao24 if self._pool.size else "000000"
        numeric = {
            "total_messages": 8.4e10,
            "total_positions": 1.2e10,
            "max_range_nm": 249.6,
            "max_range_at_ms": float(now_ms - MS_PER_DAY),
            "max_range_bearing_deg": 214.0,
            "busiest_day_count": 41_200.0,
            "max_simultaneous": 268.0,
            "peak_msg_rate": 921.0,
            "peak_pos_rate": 148.0,
        }
        rows: list[dict[str, Any]] = [
            {"key": key, "value_num": value, "value_text": None, "updated_ms": now_ms}
            for key, value in numeric.items()
        ]
        rows.append(
            {"key": "max_range_icao24", "value_num": None, "value_text": icao, "updated_ms": now_ms}
        )
        rows.append(
            {
                "key": "busiest_day",
                "value_num": None,
                "value_text": "2026-06-14",
                "updated_ms": now_ms,
            }
        )
        return rows

    async def _write_meta(self) -> None:
        """Stamp T0 — the moment history begins, which the ``t0`` preset reads."""
        first = min((value for value in self._totals.first_seen if value), default=0)
        async with self._database.writer_session() as session:
            await self._insert(
                session,
                Meta,
                [{"key": "t0_ms", "value": str(first), "updated_ms": first}],
            )

    async def _build_rollups(self, day_names: list[str], zone: ZoneInfo) -> tuple[float, int]:
        """Build the analytics rollups with the product's own backfill.

        Deliberately the real :class:`AnalyticsBackfill` rather than a
        hand-written fold: it makes the rollups consistent with the sightings
        by construction, and the time it takes is itself one of the multi-year
        figures SPEC §86 asks about.
        """
        from flightsite.analytics.backfill import AnalyticsBackfill
        from flightsite.analytics.repository import AnalyticsRepository
        from flightsite.db.meta import MetaRepository

        backfill = AnalyticsBackfill(
            repository=AnalyticsRepository(self._database),
            meta=MetaRepository(self._database),
            zone=zone,
            max_days=len(day_names) + 1,
        )
        now_ms = int(self._config.end_at.timestamp() * 1_000)
        started = time.perf_counter()
        await backfill.rebuild_days(day_names, now_ms=now_ms)
        await backfill.refresh_type_stats()
        return time.perf_counter() - started, len(day_names)

    async def _result(self, started: float, rollup_s: float, rollup_days: int) -> GenerationResult:
        """Assemble the report, reading the final file sizes from disk."""
        path = self._database.path
        wal = path.with_name(path.name + "-wal")
        db_bytes = path.stat().st_size if path.exists() else 0
        wal_bytes = wal.stat().st_size if wal.exists() else 0

        growth = tuple(
            TableGrowth(
                table=table,
                rows=self._rows[table],
                bytes=self._pages[table] * self._page_size,
            )
            for table in self._order
        )
        return GenerationResult(
            config=self._config,
            days=self._config.days,
            sightings=self._sightings_written,
            aircraft=self._pool.size,
            track_points=self._points_written,
            tracks=self._tracks_written,
            growth=growth,
            db_bytes=db_bytes,
            wal_bytes=wal_bytes,
            page_size=self._page_size,
            duration_s=time.perf_counter() - started,
            rollup_s=rollup_s,
            rollup_days=rollup_days,
        )


async def generate_history(database: Database, config: GenerationConfig) -> GenerationResult:
    """Generate ``config``'s history into ``database`` and report what it cost."""
    return await HistoryGenerator(database, config).run()


__all__ = [
    "DEFAULT_BATCH_ROWS",
    "DEFAULT_HIGH_RES_BACKLOG_DAYS",
    "DEFAULT_SEED",
    "GenerationConfig",
    "GenerationResult",
    "HistoryGenerator",
    "TableGrowth",
    "generate_history",
]
