"""One place where API payloads are assembled from application state.

``GET /api/v1/aircraft/current`` and the WebSocket's ``snapshot`` frame must
describe the same instant identically — roadmap slice 010's first acceptance
criterion — and the cheapest way to guarantee that is to give them one
implementation rather than two that agree by inspection. Both call
:meth:`LiveApiContext.aircraft`; the same is true of the receiver block, which
appears in ``GET /api/v1/receiver`` and in every snapshot.

The context reads ``app.state`` lazily on every call rather than capturing its
contents at construction. That is not indirection for its own sake: ``PUT
/api/internal/config`` replaces ``app.state.settings`` on a running app, so a
captured ``Settings`` would serve a stale receiver block for the rest of the
process's life. Reading late also means the context can be built before the
lifespan hook has started anything.

Nothing here touches SQLite on the aircraft path — the live registry answers
from memory, and so do the metadata cache, the airport context service's
in-memory index, and the persistence worker's accumulators (which carry the
open sighting's id and its enriched route), which is the invariant
``docs/ARCHITECTURE.md`` §3.1 states as "no live request or decoder poll ever
waits on SQLite" and §3.3 restates as "metadata joins and rarity checks hit a
cache, not the database". The one database read in this module is T0 for the
receiver block, which is a single indexed lookup on a write-once key, made on a
REST request or a WebSocket connect and never per frame.

An aircraft the cache has not resolved yet serializes with ``null`` metadata
rather than waiting for it. That is the deliberate trade of ``docs/API.md``
§2.7: metadata is enrichment, a live aircraft is fully usable without it, and a
frame that blocked on a lookup would trade the live picture's latency for a
field that will arrive a fraction of a second later anyway.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from fastapi import FastAPI

from flightsite.activity.repository import ActivityRepository
from flightsite.airports.overlay import AirportOverlayRepository, AirportSizeClass, BoundingBox
from flightsite.airports.records import AirportRecord
from flightsite.airports.service import AirportContextService
from flightsite.airspace.loader import load_airspace
from flightsite.analytics.bucketing import Preset, Window, explicit_window, resolve_window
from flightsite.analytics.queries import AnalyticsQueries
from flightsite.api.history import AircraftHistoryRepository
from flightsite.api.receiver_stats import (
    DEFAULT_LOOKBACK_MS,
    RAW_FIELD_FOR_METRIC,
    SUMMARY_FIELD_FOR_METRIC,
    SUMMARY_ONLY_METRICS,
    ReceiverMetricQueryError,
    ReceiverStatsRepository,
    ever_ranges,
    next_local_day,
    signal_histogram,
)
from flightsite.api.serializers import (
    activity_event_payload,
    aircraft_detail_payload,
    aircraft_history_row_payload,
    aircraft_payload,
    analytics_window_payload,
    receiver_lifetime_stats_payload,
    receiver_metric_series_payload,
    receiver_payload,
    receiver_range_by_bearing_payload,
    receiver_scorecard_payload,
    receiver_signal_distribution_payload,
    sighting_detail_payload,
    sighting_row_payload,
)
from flightsite.api.sightings import SightingsRepository
from flightsite.config import Settings
from flightsite.db import Database, MetaRepository, from_epoch_ms, to_epoch_ms, utc_now_ms
from flightsite.live import LiveAircraft, LiveStore
from flightsite.metadata import MetadataCache, MetadataService
from flightsite.receiver_metrics import MetricsRepository, ReceiverMetricsService
from flightsite.receiver_metrics.aggregate import local_day, local_day_start_ms
from flightsite.sightings import PersistenceWorker
from flightsite.watchlists import WatchlistService
from flightsite.watchlists.matcher import WatchlistMatcher

logger = structlog.get_logger(__name__)


def _wanted(record: LiveAircraft, positioned: bool | None) -> bool:
    """Apply the §3.3 ``positioned`` filter; ``None`` means "everything"."""
    return positioned is None or record.has_position is positioned


class LiveApiContext:
    """Assembles the live API payloads from a running app's state.

    Args:
        app: the application whose ``state`` holds the live registry, the
            persistence worker, the database and the effective settings.
    """

    __slots__ = ("_app",)

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    # ----------------------------------------------------------------- state

    @property
    def live(self) -> LiveStore:
        """The in-memory live aircraft registry."""
        store: LiveStore = self._app.state.live
        return store

    @property
    def settings(self) -> Settings:
        """The currently effective configuration."""
        settings: Settings = self._app.state.settings
        return settings

    @property
    def demo_mode(self) -> bool:
        """True when this process serves simulated traffic (SPEC §76)."""
        demo: bool = self._app.state.demo_enabled
        return demo

    @property
    def metadata(self) -> MetadataCache:
        """The in-memory metadata, rarity and classification cache.

        Read on the aircraft path, which is why it is the *cache* and not the
        service: :meth:`~flightsite.metadata.cache.MetadataCache.get` is a dict
        lookup with no ``await`` and no session, so the invariant this module's
        docstring states — nothing here touches SQLite on the aircraft path —
        survives metadata joining the payload.
        """
        service: MetadataService = self._app.state.metadata
        return service.cache

    @property
    def watchlist_matches(self) -> WatchlistMatcher:
        """The in-memory watchlist match index (SPEC §42, roadmap slice 037).

        Read on the aircraft path for the same reason the metadata *cache*
        is: :meth:`~flightsite.watchlists.matcher.WatchlistMatcher.matches`
        is a dict lookup with no ``await`` and no session.
        """
        service: WatchlistService = self._app.state.watchlists
        return service.matcher

    @property
    def airports(self) -> AirportContextService:
        """The nearest-airport context service (slice 027).

        Read on the aircraft path for the same reason the metadata *cache* is:
        :meth:`~flightsite.airports.service.AirportContextService.context_for`
        is a dict lookup with no ``await`` and no session, because the whole
        airport dataset is held in memory as a grid index.
        """
        service: AirportContextService = self._app.state.airports
        return service

    @property
    def metrics(self) -> MetricsRepository:
        """The receiver-metric tables' query layer (slice 033's five tables)."""
        database: Database = self._app.state.database
        return MetricsRepository(database)

    @property
    def receiver_stats(self) -> ReceiverStatsRepository:
        """The Receiver page's own query layer — see
        :mod:`flightsite.api.receiver_stats` for what it answers that
        :attr:`metrics` does not.
        """
        database: Database = self._app.state.database
        return ReceiverStatsRepository(database)

    @property
    def receiver_metrics_service(self) -> ReceiverMetricsService:
        """The running sampler/maintenance service — decoder uptime and
        statistics-support state live here, not in any table (they are
        statements about *right now*, not something a request should persist).
        """
        service: ReceiverMetricsService = self._app.state.receiver_metrics
        return service

    @property
    def _receiver_timezone(self) -> ZoneInfo:
        """The configured IANA zone, for the receiver-local day bucketing
        every receiver-stats endpoint below uses (``docs/DATA_MODEL.md`` §10).
        """
        return ZoneInfo(self.settings.timezone)

    # -------------------------------------------------------------- payloads

    def aircraft(self, *, positioned: bool | None = None) -> list[dict[str, Any]]:
        """The live set as §3.3 aircraft objects, ordered by ICAO address.

        Sorted so that two reads of the same instant — one over REST, one over
        the WebSocket — are identical documents rather than merely equal sets.
        Sorting a few hundred already-interned strings costs far less than the
        serialization it accompanies.

        Args:
            positioned: ``True`` for aircraft with a known position, ``False``
                for those tracked without one (SPEC §20), ``None`` for the full
                live picture, which is the default and the documented one.
        """
        worker: PersistenceWorker = self._app.state.persistence
        cache = self.metadata
        airports = self.airports
        watchlists = self.watchlist_matches
        records = sorted(self.live.snapshot(), key=lambda record: record.icao)
        return [
            aircraft_payload(
                record,
                sighting_id=worker.sighting_id_for(record.icao),
                metadata=cache.get(record.icao),
                route=worker.route_for(record.icao),
                airport=airports.context_for(record.icao),
                watchlists=watchlists.matches(record.icao),
            )
            for record in records
            if _wanted(record, positioned)
        ]

    def aircraft_for(self, icaos: Iterable[str]) -> list[dict[str, Any]]:
        """Serialize the named aircraft, in the order given, skipping absentees.

        Used to build a delta's ``updated`` list from the ICAOs one tick's
        events named. The payload is read from the live store *now* rather than
        from the records the events carried, so a burst of updates for one
        aircraft costs one serialization of its latest state instead of several
        of its intermediate ones. An ICAO that left the live set between the
        event and this call is simply absent — the same tick's ``removed`` list
        is the notice that matters.
        """
        worker: PersistenceWorker = self._app.state.persistence
        live = self.live
        cache = self.metadata
        airports = self.airports
        watchlists = self.watchlist_matches
        payloads: list[dict[str, Any]] = []
        for icao in icaos:
            record = live.get(icao)
            if record is not None:
                payloads.append(
                    aircraft_payload(
                        record,
                        sighting_id=worker.sighting_id_for(icao),
                        metadata=cache.get(icao),
                        route=worker.route_for(icao),
                        airport=airports.context_for(icao),
                        watchlists=watchlists.matches(icao),
                    )
                )
        return payloads

    @property
    def history(self) -> AircraftHistoryRepository:
        """The Aircraft page's query layer, built from the running database."""
        database: Database = self._app.state.database
        return AircraftHistoryRepository(database)

    async def aircraft_history(
        self,
        *,
        limit: int,
        offset: int,
        sort: str,
        order: str,
        classification: str | None = None,
        operator_group: str | None = None,
        type_code: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of the Aircraft page's list, serialized — §3.5."""
        rows, total = await self.history.list_aircraft(
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            classification=classification,
            operator_group=operator_group,
            type_code=type_code,
        )
        return [aircraft_history_row_payload(row) for row in rows], total

    async def aircraft_detail(self, icao24: str) -> dict[str, Any] | None:
        """One airframe's full detail, or ``None`` if never sighted — §3.5.

        ``live`` reads the live registry at the moment of the request rather
        than anything the history query touched: the two are different data
        sources answering the same instant, exactly as
        :meth:`aircraft` and the WebSocket snapshot do.
        """
        row = await self.history.get_aircraft(icao24)
        if row is None:
            return None
        return aircraft_detail_payload(row, live=self.live.get(icao24) is not None)

    # ---------------------------------------------------------------- overlays

    @property
    def airport_overlay(self) -> AirportOverlayRepository:
        """The map overlay's query layer over the ``airports`` table (slice 028).

        A fresh repository per call, exactly like :attr:`history` above — this
        is a REST read on the request path (a viewport bbox query, fired once
        per debounced map move), not a per-observation live-path lookup, so
        there is no in-memory index to keep warm between calls the way
        :attr:`airports` (the *nearest-airport* service) has.
        """
        database: Database = self._app.state.database
        return AirportOverlayRepository(database)

    async def airport_overlay_features(
        self, *, bbox: BoundingBox | None, min_size: AirportSizeClass | None
    ) -> list[AirportRecord]:
        """Airports for the map overlay — ``GET /api/v1/airports`` (slice 028)."""
        return await self.airport_overlay.query(bbox=bbox, min_size=min_size)

    def airspace_feature_collection(self) -> dict[str, Any]:
        """The validated user-supplied airspace overlay, or an empty one.

        ``GET /api/v1/airspace`` (slice 028, ``docs/adr/0012-airspace-data-
        source.md``). A plain file read and JSON validation, not a database
        call — nothing here can block on SQLite or on anything else this
        context's other methods wait on.
        """
        return load_airspace(self.settings.data_dir)

    @property
    def sightings(self) -> SightingsRepository:
        """The Sightings page's query layer, built from the running database."""
        database: Database = self._app.state.database
        return SightingsRepository(database)

    async def sighting_list(
        self,
        *,
        limit: int,
        offset: int,
        sort: str,
        order: str,
        icao: str | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        interesting: bool | None = None,
        open_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        """One page of the sightings log, serialized — §3.6.

        Shared by ``GET /api/v1/sightings`` and
        ``GET /api/v1/aircraft/{icao}/sightings`` (the per-aircraft log),
        which is that same query with ``icao`` fixed to one address.
        """
        rows = await self.sightings.list_sightings(
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            icao=icao,
            from_ms=from_ms,
            to_ms=to_ms,
            interesting=interesting,
            open_only=open_only,
        )
        return [sighting_row_payload(row) for row in rows]

    async def sighting_detail(self, sighting_id: int) -> dict[str, Any] | None:
        """One sighting's full detail, or ``None`` if it doesn't exist — §3.6."""
        repository = self.sightings
        row = await repository.get_sighting(sighting_id)
        if row is None:
            return None
        is_open = row["ended_ms"] is None
        events = await repository.get_events(sighting_id)
        path = await repository.get_path(sighting_id, is_open=is_open)
        return sighting_detail_payload(row, events=events, path=path)

    # ------------------------------------------------------------ analytics

    @property
    def analytics(self) -> AnalyticsQueries:
        """The §3.7 query layer, built from the running database and timezone.

        Built per call rather than cached, for the same reason this context
        reads ``app.state`` lazily everywhere else: ``PUT
        /api/internal/config`` can replace the settings — the receiver's
        timezone among them — on a running app, and a captured zone would
        keep resolving "today" against the old one for the rest of the
        process's life.
        """
        database: Database = self._app.state.database
        return AnalyticsQueries(database, timezone=self.settings.timezone)

    async def analytics_window(
        self,
        *,
        preset: str | None,
        from_ms: int | None,
        to_ms: int | None,
    ) -> Window:
        """Resolve §3.7's ``preset`` or explicit bounds into a window.

        Explicit bounds win when both are given: a client that has computed a
        range is being specific, and silently preferring a preset over it would
        answer a question it did not ask. A ``from`` with no ``to`` runs to now;
        a ``to`` with no ``from`` starts at T0, which is the only lower bound
        the receiver has.
        """
        zone = ZoneInfo(self.settings.timezone)
        now_ms = utc_now_ms()
        t0_ms = await self._t0_ms()
        if from_ms is not None or to_ms is not None:
            return explicit_window(
                from_ms if from_ms is not None else (t0_ms if t0_ms is not None else now_ms),
                to_ms if to_ms is not None else now_ms,
                zone=zone,
                t0_ms=t0_ms,
            )
        return resolve_window(
            Preset(preset) if preset is not None else Preset.TODAY,
            now_ms=now_ms,
            zone=zone,
            t0_ms=t0_ms,
        )

    def analytics_window_block(self, window: Window, *, preset: str | None) -> dict[str, Any]:
        """The window block every §3.7 response carries."""
        return analytics_window_payload(window, preset=preset, timezone=self.settings.timezone)

    async def _t0_ms(self) -> int | None:
        """T0 as epoch milliseconds, or ``None`` — see :meth:`_t0`."""
        t0 = await self._t0()
        return None if t0 is None else to_epoch_ms(t0)

    async def receiver(self) -> dict[str, Any]:
        """The §3.2 receiver info block, including T0.

        The location comes from the live store rather than from settings: it
        is the position distances and bearings are actually measured from, so
        it is the one a client should draw its receiver marker and range rings
        at. They differ only in demo mode, which injects a location into an
        otherwise unconfigured install.
        """
        return receiver_payload(
            self.settings,
            demo_mode=self.demo_mode,
            t0=await self._t0(),
            location=self.live.receiver_location,
        )

    async def _t0(self) -> datetime | None:
        """T0 as an aware UTC datetime, or ``None`` if it is unavailable.

        A database that failed to migrate leaves ``/api/v1/ready`` answering
        503 but must not take the receiver block down with it: the rest of that
        payload is pure configuration, and the live picture behind it is fine.
        An unreadable T0 is therefore reported as "unknown" (§2.7) rather than
        as a 500, with the reason logged once per read.
        """
        database: Database = self._app.state.database
        try:
            t0_ms = await MetaRepository(database).get_t0()
        except Exception as exc:
            logger.warning("t0_unavailable", error=str(exc), error_type=type(exc).__name__)
            return None
        return None if t0_ms is None else from_epoch_ms(t0_ms)

    # -------------------------------------------------------------- activity

    @property
    def activity(self) -> ActivityRepository:
        """The activity feed's query layer, built from the running database.

        A fresh repository per call, like :attr:`history` and :attr:`sightings`:
        this is a REST read on the request path, not a live-path lookup, so
        there is nothing to keep warm between calls. Deliberately *not* read
        through ``app.state.activity`` — the running detector holds in-memory
        baselines that a request has no business touching, and the feed is
        answered from the table it wrote.
        """
        database: Database = self._app.state.database
        return ActivityRepository(database)

    async def activity_feed(
        self,
        *,
        limit: int,
        offset: int,
        types: Sequence[str] | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """One page of the activity feed, serialized — ``docs/API.md`` §3.9."""
        events = await self.activity.list_events(
            limit=limit, offset=offset, types=types, from_ms=from_ms, to_ms=to_ms
        )
        return [activity_event_payload(event) for event in events]

    # ------------------------------------------------------- receiver stats

    async def receiver_scorecard(self) -> dict[str, Any]:
        """The SPEC §61 scorecard — ``docs/API.md`` §3.8.

        "Unique aircraft today"/"since T0" are read from :attr:`analytics`
        (roadmap slice 031's rollups) rather than computed here: they are
        exactly :meth:`~flightsite.analytics.queries.AnalyticsQueries.unique_aircraft`
        over the ``today``/``t0`` presets, and reusing that query is what
        keeps this figure and the Analytics page's own "unique aircraft"
        stat tile answering from the same source rather than two independent
        (and potentially disagreeing) counts.
        """
        zone = self._receiver_timezone
        now_ms = utc_now_ms()
        today = local_day(now_ms, zone)
        t0_ms = await self._t0_ms()

        metrics = self.metrics
        service = self.receiver_metrics_service
        analytics = self.analytics

        latest_sample = await metrics.latest_sample()
        today_ranges = await metrics.ranges_for_day(today)
        max_range_today = (
            max((record.max_range_nm for record in today_ranges.values()), default=None)
            if today_ranges
            else None
        )
        lifetime = await metrics.lifetime()
        unique_today = await analytics.unique_aircraft(
            resolve_window(Preset.TODAY, now_ms=now_ms, zone=zone, t0_ms=t0_ms)
        )
        unique_since_t0 = await analytics.unique_aircraft(
            resolve_window(Preset.SINCE_T0, now_ms=now_ms, zone=zone, t0_ms=t0_ms)
        )

        latest_stats = service.latest_stats
        app_start_time: float = self._app.state.start_time
        return receiver_scorecard_payload(
            counts=self.live.counts(),
            latest_sample=latest_sample,
            max_range_today_nm=max_range_today,
            lifetime=lifetime,
            unique_today=unique_today,
            unique_since_t0=unique_since_t0,
            decoder_uptime_s=None if latest_stats is None else latest_stats.uptime_s,
            flightsite_uptime_s=time.monotonic() - app_start_time,
            stats_supported=service.stats_supported,
            demo_mode=self.demo_mode,
        )

    async def receiver_metric_series(
        self,
        *,
        metric: str,
        resolution: str,
        from_ms: int | None,
        to_ms: int | None,
    ) -> dict[str, Any]:
        """The §3.8 time-series payload for one SPEC §62 chart.

        Raises:
            ReceiverMetricQueryError: an unsupported ``metric``/``resolution``
                pairing — see the exception's own docstring. The endpoint
                catches this and answers a 400 in the §2.5 error envelope.
        """
        if metric == "unique_aircraft" and resolution != "daily":
            raise ReceiverMetricQueryError("unique_aircraft is only available at resolution=daily")
        if metric in SUMMARY_ONLY_METRICS and resolution == "high":
            raise ReceiverMetricQueryError(
                f"{metric} has no raw-resolution representation; use resolution=hourly or daily"
            )

        zone = self._receiver_timezone
        now_ms = utc_now_ms()
        end_ms = now_ms if to_ms is None else to_ms
        start_ms = end_ms - DEFAULT_LOOKBACK_MS[resolution] if from_ms is None else from_ms

        metrics = self.metrics
        points: list[tuple[int, float | None]]
        if metric == "unique_aircraft":
            # Roadmap slice 031's daily rollups already answer this exactly —
            # `daily()` returns one row per local day in the window, zero
            # included (the same "the zero is the measurement" rule as every
            # other analytics chart), so there is nothing left for this
            # endpoint to compute from `sightings` itself.
            window = explicit_window(start_ms, end_ms, zone=zone, t0_ms=await self._t0_ms())
            rows = await self.analytics.daily(window)
            points = [
                (local_day_start_ms(row.day, zone), float(row.unique_aircraft)) for row in rows
            ]
        elif resolution == "high":
            samples = await metrics.samples_between(start_ms, end_ms + 1)
            field = RAW_FIELD_FOR_METRIC[metric]
            points = [(sample.ts_ms, getattr(sample, field)) for sample in samples]
        elif resolution == "hourly":
            hourly_summaries = await metrics.hourly_between(start_ms, end_ms + 1)
            field = SUMMARY_FIELD_FOR_METRIC[metric]
            points = [
                (hour_ms, getattr(summary, field)) for hour_ms, summary in hourly_summaries.items()
            ]
        else:  # daily
            start_day = local_day(start_ms, zone)
            end_day = next_local_day(local_day(end_ms, zone))
            daily_summaries = await metrics.daily_between(start_day, end_day)
            field = SUMMARY_FIELD_FOR_METRIC[metric]
            points = [
                (local_day_start_ms(day, zone), getattr(summary, field))
                for day, summary in daily_summaries.items()
            ]

        points.sort(key=lambda point: point[0])
        return receiver_metric_series_payload(metric=metric, resolution=resolution, points=points)

    async def receiver_range_by_bearing(self) -> dict[str, Any]:
        """``GET /api/v1/receiver/range-by-bearing`` — SPEC §62's polar plot."""
        zone = self._receiver_timezone
        today = local_day(utc_now_ms(), zone)
        metrics = self.metrics
        today_ranges = await metrics.ranges_for_day(today)
        ever = ever_ranges(await metrics.ranges_all())
        return receiver_range_by_bearing_payload(today=today_ranges, ever=ever)

    async def receiver_signal_distribution(
        self, *, from_ms: int | None, to_ms: int | None, bucket_width_db: float
    ) -> dict[str, Any]:
        """``GET /api/v1/receiver/signal-distribution`` — SPEC §62, from per-sighting RSSI."""
        values = await self.receiver_stats.signal_values(from_ms=from_ms, to_ms=to_ms)
        histogram = signal_histogram(values, bucket_width_db=bucket_width_db)
        return receiver_signal_distribution_payload(histogram, from_ms=from_ms, to_ms=to_ms)

    async def receiver_lifetime(self) -> dict[str, Any]:
        """``GET /api/v1/receiver/lifetime`` — SPEC §63, since T0 where possible."""
        metrics = self.metrics
        stats = self.receiver_stats
        lifetime = await metrics.lifetime()
        t0 = await self._t0()
        t0_ms = None if t0 is None else to_epoch_ms(t0)
        unique_aircraft = await self.analytics.unique_aircraft(
            resolve_window(
                Preset.SINCE_T0, now_ms=utc_now_ms(), zone=self._receiver_timezone, t0_ms=t0_ms
            )
        )
        total_sightings = await stats.total_sightings()
        most_frequent = await stats.most_frequent_aircraft()
        common_type = await stats.common_type()
        common_model = await stats.common_model()
        common_operator = await stats.common_operator()
        return receiver_lifetime_stats_payload(
            t0=t0,
            lifetime=lifetime,
            unique_aircraft=unique_aircraft,
            total_sightings=total_sightings,
            most_frequent=most_frequent,
            common_type=common_type,
            common_model=common_model,
            common_operator=common_operator,
        )


__all__ = ["LiveApiContext"]
