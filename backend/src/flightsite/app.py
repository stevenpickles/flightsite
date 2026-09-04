"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI

from flightsite import __version__
from flightsite.activity import (
    ActivityListener,
    ActivityService,
    AlertMatchFact,
    HealthProbe,
    StoredActivityEvent,
)
from flightsite.airports import (
    AIRPORTS_SOURCE,
    AirportContextService,
    AirportImportSink,
    AirportRepository,
    OurAirportsProvider,
)
from flightsite.alerts import AlertListener, AlertService
from flightsite.analytics import AnalyticsService
from flightsite.api.context import LiveApiContext
from flightsite.api.ingestion import decoder_endpoint, start_decoder_ingestion
from flightsite.api.internal import router as internal_router
from flightsite.api.serializers import activity_event_payload
from flightsite.api.v1 import router as v1_router
from flightsite.api.ws import LiveBroadcaster
from flightsite.config import ConfigStore, Settings
from flightsite.db import Database, database_path, initialize_database
from flightsite.db.startup import DATABASE_SUBSYSTEM
from flightsite.demo import DEFAULT_CENTER, DemoAdapter, demo_enabled
from flightsite.diagnostics.errors import error_ring, secrets_from_settings
from flightsite.enrichment import EnrichmentService, RouteCacheRepository
from flightsite.enrichment.service import build_provider
from flightsite.ingest import IngestionService, Position
from flightsite.ingest.health import AdapterHealth
from flightsite.live import LiveStore
from flightsite.logging import DEFAULT_LOG_DIR, configure_logging, install_error_capture
from flightsite.maintenance import MaintenanceService, RouteCachePruner
from flightsite.metadata import ImportListener, ImportRun, MetadataService
from flightsite.metadata.registry import SourceRegistry
from flightsite.metadata.sources import FaaRegistryProvider, MictronicsProvider, OpenSkyProvider
from flightsite.readiness import ReadinessRegistry
from flightsite.receiver_metrics import ReceiverMetricsService, StatsJsonPoller
from flightsite.reset import apply_pending_reset
from flightsite.sightings import PersistenceWorker
from flightsite.watchlists import WatchlistService

logger = structlog.get_logger(__name__)


def _build_live_store(settings: Settings) -> LiveStore:
    """Construct the live registry from the configured timings and location.

    The receiver location is optional: until the setup wizard (slice 018)
    collects one, the store simply computes no distance or bearing. Everything
    else — the live set, lifecycle, tracks, events — works exactly the same.
    """
    location = settings.location
    receiver = (
        Position(latitude=location.latitude, longitude=location.longitude)
        if location.latitude is not None and location.longitude is not None
        else None
    )
    return LiveStore(
        stale_s=settings.sighting.stale_s,
        remove_s=settings.sighting.remove_s,
        receiver_location=receiver,
    )


def _build_metadata_registry(airports: AirportRepository, settings: Settings) -> SourceRegistry:
    """The datasets this build ships.

    Slice 022 registers ``mictronics`` (the offline primary source); slice 023
    adds ``faa``; slice 027 adds ``airports``, which is not aircraft metadata
    at all — it supplies its own :class:`~flightsite.metadata.sink.ImportSink`
    and shares everything else, so slice 025's update action imports it and
    reports its status independently (SPEC §27).

    Slice 059 adds ``opensky``, the one source that is **not** unconditional:
    it is registered only when ``metadata.opensky_enabled`` is set. The gate
    lives here, at construction, rather than inside the provider or the
    importer, and that is what makes "off" mean *absent* — an unregistered
    source cannot be imported, cannot be named in a per-source status, and
    cannot make a request. A stock install therefore never contacts OpenSky at
    all, which is the point: ADR-0013 keeps that contact a deliberate act by
    the operator, because the dataset's licensing is ambiguous. This mirrors
    how :func:`flightsite.enrichment.service.build_provider` gates its own
    optional provider — but no longer what happens when the setting changes:
    that one is re-read and applied on every configuration save (issue #161),
    while this registry is built here and nowhere else, so toggling OpenSky
    still takes effect on the next restart.

    Constructing a provider here opens nothing — it downloads only when an
    import actually runs (:mod:`flightsite.metadata.importer`).
    """
    registry = SourceRegistry()
    registry.register("mictronics", MictronicsProvider())
    registry.register("faa", FaaRegistryProvider())
    if settings.metadata.opensky_enabled:
        registry.register("opensky", OpenSkyProvider())
    registry.register(AIRPORTS_SOURCE, OurAirportsProvider(), sink=AirportImportSink(airports))
    return registry


def _rebuild_airport_index(app: FastAPI) -> ImportListener:
    """A post-import listener that rebuilds the airport index when it changed.

    The airport equivalent of the metadata cache's invalidation, and wired the
    same way and on the same edge — but as a listener rather than a hard-coded
    step, so :mod:`flightsite.metadata` never has to know that
    :mod:`flightsite.airports` exists. The dependency runs one way: airports
    consumes the import pipeline.

    Guarded on the source actually having succeeded. A run in which only
    ``faa`` imported changed no airport, and rebuilding a 70k-row index for
    that would be work for nothing.
    """

    async def rebuild(run: ImportRun) -> None:
        if AIRPORTS_SOURCE not in run.succeeded:
            return
        service: AirportContextService = app.state.airports
        await service.reload()

    return rebuild


def _record_activity(app: FastAPI) -> ImportListener:
    """A post-import listener that turns a run's results into feed events.

    Registered beside the airport index rebuild and on the same edge, but with
    the opposite guard: SPEC §55 wants *"metadata update results"* in the feed
    and SPEC §27 wants the user to see which sources failed, so this one cares
    about every completed run rather than only the ones that changed data.
    """

    async def record(run: ImportRun) -> None:
        activity: ActivityService = app.state.activity
        await activity.record_import(run)

    return record


def _decoder_health(app: FastAPI) -> HealthProbe:
    """Read the decoder's current connection health, if there is a decoder.

    A callable rather than a service reference because ``app.state.ingestion``
    is assigned *during* the lifespan hook, after the activity service has been
    constructed and started; and on a first-run install it is ``None`` until a
    configuration is saved — which is exactly the case the feed must stay
    silent about rather than report as an outage.

    Reading late is also what makes the hot start of issue #122 invisible
    here: when a config save assigns ``app.state.ingestion`` mid-life, the
    very next probe reports the new service's health with no re-registration.
    """

    def probe() -> AdapterHealth | None:
        service: IngestionService | None = getattr(app.state, "ingestion", None)
        return None if service is None else service.health()

    return probe


def _broadcast_activity(app: FastAPI) -> ActivityListener:
    """Push newly recorded activity events onto the WebSocket (§4.4).

    Serialization happens here, in the API layer, rather than inside the
    activity service: the frame body is the §3.9 payload, and
    :func:`~flightsite.api.serializers.activity_event_payload` is the one
    function that builds it — which is what makes the REST feed and the live
    frame the same object rather than two that agree by inspection.
    """

    def broadcast(events: Sequence[StoredActivityEvent]) -> None:
        broadcaster: LiveBroadcaster = app.state.broadcaster
        broadcaster.publish_activity([activity_event_payload(event) for event in events])

    return broadcast


def _record_alert_matches(app: FastAPI) -> AlertListener:
    """Push the alert engine's created matches into the activity feed (SPEC §55).

    The alert engine writes ``alert_matches`` on its own transaction and then
    hands what it *created* to this listener; the activity service records the
    ``alert_triggered`` / ``emergency_squawk`` events on its own pass, its own
    transaction and its own dedupe key. Two subsystems, two commits, one
    direction of dependency — and a feed failure can never turn a recorded
    alert into an unrecorded one.
    """

    def record(matches: Sequence[AlertMatchFact]) -> None:
        activity: ActivityService = app.state.activity
        activity.record_alert_matches(matches)

    return record


def _alert_radius(app: FastAPI) -> Callable[[], float | None]:
    """Read the configured alert radius at the moment a cycle needs it (SPEC §66).

    A callable rather than a captured value for the reason
    :class:`~flightsite.api.context.LiveApiContext` reads ``app.state`` lazily:
    ``PUT /api/internal/config`` replaces ``app.state.settings`` on a running
    app, and a captured radius would keep bounding alerts by a setting the user
    has since changed.
    """

    def probe() -> float | None:
        settings: Settings = app.state.settings
        return settings.alert_radius_nm

    return probe


def _build_persistence_worker(app: FastAPI, settings: Settings) -> PersistenceWorker:
    """Construct the write-behind persistence worker (ADR-0008).

    Constructing it subscribes to nothing and opens no connection; ``start()``
    in the lifespan hook attaches it to the live event stream. It is the only
    writer of ``aircraft`` and ``sightings``, and it reaches them through
    :meth:`~flightsite.db.engine.Database.writer_session` — the process's one
    serialized writer, which the metadata import, the airport dataset and the
    receiver metrics share.
    """
    return PersistenceWorker(
        database=app.state.database,
        live=app.state.live,
        close_s=settings.sighting.close_s,
    )


def _build_receiver_metrics(app: FastAPI, settings: Settings) -> ReceiverMetricsService:
    """Construct the receiver-metric service (SPEC §60/§64, ADR-0009).

    The ``stats.json`` poller is built only when there is a decoder to poll:
    a first-run install has no configured receiver, and demo mode has no
    decoder at all. In both cases the service still runs and still records
    every FlightSite-computed metric — simultaneous aircraft, message and
    position rates from the live set, and range by bearing — with the
    decoder-supplied columns left ``NULL``. That is the same graceful absence
    SPEC §60 asks for when a decoder serves no statistics document.

    Absent, not absent-until-reboot: the save that ends the first-run state
    attaches a poller to this service, through
    :func:`~flightsite.api.ingestion.attach_stats_poller` (issue #129), just as
    it starts ingestion. Before that, a fresh install's decoder metric columns
    stayed ``NULL`` for the life of the process.

    Constructing it opens nothing: no HTTP client, no session, no task.
    """
    store: ConfigStore = app.state.config_store
    poller = (
        None if store.first_run or demo_enabled() else StatsJsonPoller(decoder_endpoint(settings))
    )
    return ReceiverMetricsService(
        database=app.state.database,
        live=app.state.live,
        poller=poller,
        timezone=settings.timezone,
        high_res_days=settings.retention.high_res_metric_days,
    )


async def _start_ingestion(app: FastAPI) -> None:
    """Start decoder ingestion, unless this install has never been configured.

    On a first run there is no ``config.yaml``, so there is no receiver the
    user has actually chosen — only model defaults. Polling those would
    produce a stream of connection failures and a ``down`` decoder before the
    setup wizard has even been opened, so ingestion is skipped here.

    Skipped, not skipped-until-reboot: the save that ends the first-run state
    starts ingestion itself, through the same
    :func:`~flightsite.api.ingestion.start_decoder_ingestion` this function
    calls (issue #122). Before that, ``app.state.ingestion`` stayed ``None``
    for the life of the process and a user who had just completed the setup
    wizard saw an empty map until the backend was restarted.

    Demo mode (``FLIGHTSITE_DEMO=1``, slice 011) is the one exception to the
    first-run skip: it starts :class:`~flightsite.demo.DemoAdapter` regardless
    of first-run state, because demo mode's whole purpose is a full stack with
    zero configuration (SPEC §76). A receiver location is injected into the
    live store when none is configured, so distance and bearing still compute.

    ``app.state.ingestion`` is assigned on every path, including the skip, so
    the shutdown half of the lifespan hook can read it unconditionally.

    Decoder health deliberately never affects ``/ready``; the reasoning is in
    :mod:`flightsite.ingest.service`.
    """
    live: LiveStore = app.state.live

    if demo_enabled():
        if live.receiver_location is None:
            live.set_receiver_location(DEFAULT_CENTER)
        service = IngestionService(
            DemoAdapter(center=live.receiver_location),
            readiness=app.state.readiness,
            consumers=(live.apply,),
        )
        await service.start()
        app.state.ingestion = service
        return

    store: ConfigStore = app.state.config_store
    if store.first_run:
        logger.info("ingestion_skipped", reason="first_run")
        app.state.ingestion = None
        return

    await start_decoder_ingestion(app)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    readiness: ReadinessRegistry = app.state.readiness
    database: Database = app.state.database
    live: LiveStore = app.state.live
    persistence: PersistenceWorker = app.state.persistence
    broadcaster: LiveBroadcaster = app.state.broadcaster
    metadata: MetadataService = app.state.metadata
    enrichment: EnrichmentService = app.state.enrichment
    airports: AirportContextService = app.state.airports
    receiver_metrics: ReceiverMetricsService = app.state.receiver_metrics
    analytics: AnalyticsService = app.state.analytics
    watchlists: WatchlistService = app.state.watchlists
    activity: ActivityService = app.state.activity
    alerts: AlertService = app.state.alerts
    maintenance: MaintenanceService = app.state.maintenance

    # Migrations and the integrity check run before startup is declared
    # complete. They never abort startup: a failure leaves the `database`
    # subsystem not-ready (so /api/v1/ready answers 503) while the process
    # stays reachable for diagnosis — see flightsite.db.startup.
    database_ready = await initialize_database(database, readiness)

    # The persistence worker starts only on a healthy schema: against a
    # database that failed to migrate every cycle would fail identically, and
    # a warning per second would bury the one error that explains it. The live
    # picture, ingestion and the API stay fully available — persistence is the
    # only thing degraded, which is exactly what the readiness flag says.
    if database_ready:
        await persistence.start()
        # Same condition, same reason: the watchlist match index is loaded
        # from tables the failed migration may not have created. It starts
        # before the metadata cache, deliberately: the cache's own start()
        # synchronously visits the current live set and notifies the matcher
        # for each one, so the matcher needs real entries loaded before that
        # happens — otherwise the first population round would compute every
        # aircraft's matches against an empty index. Skipping this leaves
        # `watchlists: []` on every aircraft, which is the same honest empty
        # answer an install with no watchlists configured shows.
        await watchlists.start()
        # Same condition, same reason: the metadata cache reads the schema the
        # migration just failed to create. Skipping it leaves every live
        # aircraft's metadata `null` — the documented unknown state — while
        # the live picture stays completely unaffected.
        await metadata.start()
        # Same condition again: enrichment reads and writes `route_cache`, and
        # its whole output is optional information. A build with no API key
        # returns from this immediately having started nothing.
        await enrichment.start()
        # And again: the airport context service reads `airports` once, to
        # build its in-memory index. On an install that has never imported the
        # dataset that read finds nothing, the index stays empty, and every
        # `nearest_airport` is null — the documented unknown state.
        await airports.start()
        # Same condition once more: receiver metrics write five tables the
        # failed migration may not have created, and every one of their reads
        # is of a table they wrote themselves. Skipping them leaves the
        # receiver page without history; nothing else notices, because nothing
        # else reads those tables.
        await receiver_metrics.start()
        # And once more, for the same reason and with one addition: the
        # analytics rollups are derived from `sightings`, so this start
        # runs the backfill that repairs whatever the last process left
        # stale before anything can read a rollup row. It is started
        # after the persistence worker so the lifecycle seam it
        # subscribes to is already live.
        await analytics.start()
        # And once more, for the same reason and after the same worker: the
        # activity detector subscribes to that same lifecycle seam, and its
        # start seeds the record baselines every announcement is measured
        # against. It goes after analytics because a busiest-day record is a
        # `lifetime_stats` value slice 033 writes from rollups slice 031
        # maintains, and seeding from a repaired database is seeding from the
        # truth. A failed migration leaves the feed empty and nothing else
        # degraded — the same shape as every subsystem above it.
        await activity.start()
        # Same condition again: the alert engine reads `alert_rules` and writes
        # `alert_matches`, both created by the migration that may have failed,
        # and it instantiates the shipped templates on its first ever start.
        # Skipping it leaves every aircraft's `interesting` block null — the
        # documented "no active alert match" state — with the live picture, the
        # sightings and the feed all completely unaffected.
        #
        # After the activity service, deliberately: the engine publishes its
        # created matches into that service's pending queue, so the consumer of
        # this producer is already running before it can produce anything. And
        # after the metadata cache and the watchlist service, because those two
        # supply the resolved views and the match index every evaluation reads
        # — starting the engine first would mean its first cycles evaluated
        # every aircraft against empty inputs.
        await alerts.start()
        # Same condition once more, and last of the database-dependent
        # subsystems: maintenance verifies, prunes and optimizes the very
        # schema the migration may have failed to create, so there is nothing
        # for it to do until that succeeds. Started after every other
        # subsystem so its first cycle — an hour away — cannot overlap the
        # backfills and recoveries startup is still running.
        await maintenance.start()

    # The lifecycle sweep runs whether or not a decoder is configured: an
    # empty live set costs nothing to sweep, and starting it unconditionally
    # means the store behaves identically the moment ingestion does start.
    await live.start()
    # Started before ingestion, so the broadcaster's subscription is attached
    # before the first decoder batch is applied: a client connecting during
    # startup then gets a snapshot and a continuous delta stream, never a
    # snapshot followed by a gap.
    await broadcaster.start()
    # Assigns app.state.ingestion itself, on every path — including the
    # first-run skip, which assigns None. A save that later ends the first-run
    # state assigns it through the same helper (issue #122).
    await _start_ingestion(app)
    readiness.mark_startup_complete()
    logger.info("app_startup_complete")
    try:
        yield
    finally:
        # Maintenance stops first, ahead of the data-flow order below, because
        # it is the one subsystem whose in-flight work is entirely
        # discardable: no job holds buffered state, and a cancelled cycle
        # simply leaves its remaining jobs for the next process. Stopping it
        # here means no housekeeping statement is holding the writer lock when
        # the persistence worker takes its final transactions.
        await maintenance.stop()
        # Shut down along the direction of data flow, so each stage has
        # already stopped producing before its consumer stops: ingestion, then
        # the live store's sweep, then its two consumers — the WebSocket
        # broadcaster (which closes every client cleanly) and the persistence
        # worker, which drains what the first two last emitted and flushes
        # every open sighting before the engines close.
        service: IngestionService | None = app.state.ingestion
        if service is not None:
            await service.stop()
        await live.stop()
        await broadcaster.stop()
        # A slice-025 update run outlives the request that triggered it
        # (that is the whole point of running it in the background), so one
        # can still be in flight at shutdown. Cancelling it here rather than
        # abandoning it means the writer session it holds rolls back
        # cleanly (``Database.writer_session`` catches ``BaseException``)
        # instead of racing the engines disposing under it.
        update_task: asyncio.Task[ImportRun] | None = app.state.metadata_update_task
        if update_task is not None and not update_task.done():
            update_task.cancel()
            with suppress(asyncio.CancelledError):
                await update_task
        # Before the persistence worker, so no consumer of the live stream is
        # still resolving against the database while the worker takes its final
        # writer transactions. Enrichment goes first of the two: it applies
        # routes *through* the worker, so it must have stopped before the
        # worker's final flush, or a route could land on an accumulator nobody
        # will write again. Airport context stops for exactly the same reason:
        # it applies inferences through the worker too.
        await enrichment.stop()
        await airports.stop()
        # Beside those two and for the same reason: the alert engine applies
        # `max_alert_severity` *through* the persistence worker, so it must
        # have stopped before that worker's final flush, or a severity could
        # land on an accumulator nobody will write again.
        await alerts.stop()
        await metadata.stop()
        # Stopped before the engines close because its final flush is a real
        # write: an interval of samples, and the lifetime increments they
        # carry, are in memory at this point. It takes the same writer lock
        # the persistence worker does, so the two simply serialize.
        await receiver_metrics.stop()
        await persistence.stop()
        # After the persistence worker, deliberately: that worker's own
        # stop force-flushes every dirty accumulator and closes nothing
        # else, so stopping analytics afterwards means its final rebuild
        # sees the last sightings this process wrote. It is the one
        # subsystem that reads what the worker's shutdown produced.
        await analytics.stop()
        # Last of the background subsystems, for the same reason and one more:
        # its final pass sees the sightings the worker's shutdown closed, and
        # it runs after analytics so a busiest-day record it might announce is
        # measured against rollups that are already final.
        await activity.stop()
        await database.dispose()
        logger.info("app_shutdown")


def create_app(data_dir: str | os.PathLike[str] | None = None) -> FastAPI:
    """Build and configure the FlightSite FastAPI application.

    Loads configuration once (``config.yaml`` / ``secrets.yaml`` /
    ``FLIGHTSITE_*``) and stores the resulting :class:`~flightsite.config.Settings`
    plus its :class:`~flightsite.config.ConfigStore` on ``app.state``;
    ``PUT /api/internal/config`` replaces ``app.state.settings`` in place, so
    request handlers must read it from state rather than caching it at import
    time. Then configures structured logging, initializes the readiness
    registry and uptime clock, constructs the database, and mounts the
    routers.

    Before any of that, a pending ``Reset FlightSite Data`` marker (SPEC §73,
    slice 045) is applied: :func:`~flightsite.reset.apply_pending_reset`
    deletes ``flightsite.sqlite3`` and its WAL sidecars if
    ``POST /api/internal/reset/data`` left one behind on a previous run, and
    is a no-op otherwise. See :mod:`flightsite.reset.marker` for why this is a
    mark-and-restart action rather than a live tear-down.

    The ``database`` subsystem is registered here, not in the lifespan hook,
    so it reads as not-ready from the very first request; the lifespan hook
    migrates the database and marks it ready. Constructing
    :class:`~flightsite.db.Database` opens nothing and creates no directory —
    building an app is still side-effect free, and by this point any pending
    reset has already made sure there is nothing left to migrate but a fresh
    schema.

    The in-memory live aircraft registry is constructed here and exposed as
    ``app.state.live``; startup starts its lifecycle sweep and, when a
    configuration exists, launches decoder ingestion feeding it. Shutdown
    stops both. A decoder that is unreachable does not hold up readiness — the
    app is fully usable without one.

    The write-behind persistence worker is constructed alongside it as
    ``app.state.persistence``. It consumes the live event stream and is the
    process's single SQLite writer (ADR-0008); startup attaches it once the
    schema is known good, and shutdown flushes it before the engines close.

    The metadata subsystem is constructed as ``app.state.metadata``: the source
    registry, the transactional import pipeline, and the metadata & rarity
    cache that keeps SQLite off the live path (``docs/ARCHITECTURE.md`` §3.3).
    Startup attaches the cache to the live event stream on a healthy schema,
    and shutdown detaches it before the writer takes its last transaction.
    ``docs/API.md`` §5's ``/api/internal/metadata/*`` (slice 025) calls
    :meth:`~flightsite.metadata.MetadataService.update` from a background
    task tracked as ``app.state.metadata_update_task``, so a run outlives the
    request that started it; shutdown cancels one still in flight before the
    cache and the writer stop underneath it.

    User-defined watchlists (SPEC §42) are constructed as
    ``app.state.watchlists``. Startup loads its in-memory match index from the
    database before the metadata cache's own startup visits the live set, and
    every CRUD mutation (``docs/API.md`` §5's ``/api/internal/watchlists*``)
    rebuilds that index before answering — so "matching updates without
    restart" is true of the surface, not merely eventually consistent with
    it. It holds no background task of its own and needs no shutdown step.

    Nearest-airport context (SPEC §41) is constructed as ``app.state.airports``
    — a fourth consumer of the live event stream. Startup loads the whole
    ``airports`` table into an in-memory grid index so no live request ever
    queries it; an install that has never imported the dataset gets an empty
    index and a ``null`` ``nearest_airport`` on every aircraft. The dataset is
    registered in the same source registry as the aircraft metadata sources, so
    slice 025's update action imports and reports it independently, and a
    post-import listener rebuilds the index when it lands.

    Optional route enrichment (SPEC §28) is constructed as
    ``app.state.enrichment``. It is a third consumer of the live event stream,
    and it is inert unless ``enrichment.aerodatabox_enabled`` is set *and* a key
    is configured: with no provider it starts no task, opens no socket, and
    every route stays ``null``. Both of those are read again on every
    configuration save and applied in place (issue #161), so switching
    enrichment on, off or onto a new key needs no restart. When it is on,
    routes reach the database through the persistence worker's accumulator
    rather than a writer session of its own, which is why it is stopped before
    that worker on shutdown.

    Analytics rollups (SPEC §58/§59) are constructed as ``app.state.analytics``.
    It is the fifth low-frequency background task: it subscribes to the
    persistence worker's sighting-lifecycle seam, marks the receiver-local days
    a committed cycle touched, and rebuilds those days from ``sightings``
    ground truth on its own writer transaction. Startup first runs its backfill,
    so a day the previous process left stale is repaired before anything can
    read a rollup row; shutdown runs after the persistence worker's final flush,
    which is the one subsystem whose shutdown output another one reads.

    Activity and milestones (SPEC §54/§55) are constructed as
    ``app.state.activity`` — the sixth background task, and the second consumer
    of that same lifecycle seam. It finds what happened by scanning ``sightings``
    above a watermark rather than by trusting a notification, records events and
    milestones whose keys make recording them exactly-once, and publishes what it
    actually wrote onto the WebSocket's ``activity`` frame (``docs/API.md`` §4.4)
    through a listener wired here. It also reads decoder health for the
    offline/restored events and takes metadata import results through the same
    post-import listener list the airport index rebuild uses.

    Interesting-aircraft alerting (SPEC §43 to §48) is constructed as
    ``app.state.alerts`` — the seventh background task and the fifth consumer
    of the live event stream. Its engine evaluates each aircraft's rules on
    that aircraft's own updates, from in-memory inputs only, so a full cycle
    over the whole live set stays inside a fraction of a poll; matches are
    deduplicated once per sighting per rule by two partial unique indexes;
    ``sightings.max_alert_severity`` is applied through the persistence
    worker's accumulator, so it lands in the same transaction as the rest of
    the sighting row; and the activity feed takes the matches that were
    actually created through a listener wired here. Emergency squawks (SPEC
    §47) are evaluated by the engine unconditionally and are not expressible
    as a rule, so no configuration can switch them off. Startup instantiates
    the shipped templates named by ``alerts.enabled_templates`` on an install
    that has never had any; shutdown stops it before the persistence worker,
    because it writes through that worker.

    Database maintenance (SPEC §70) is constructed as ``app.state.maintenance``:
    the seventh low-frequency background task, running an integrity check,
    retention pruning, ``PRAGMA optimize``, WAL checkpoint management and a
    guarded ``VACUUM`` on their own cadences. It adds no configuration key —
    every threshold is a module constant — and its
    :attr:`~flightsite.maintenance.MaintenanceService.report` is what slice
    042's diagnostics surface reads. Startup starts it last, so its first cycle
    cannot overlap the backfills and recoveries; shutdown stops it first,
    because a cancelled cycle loses nothing.

    The live API context and the WebSocket broadcaster are constructed here
    too, as ``app.state.api_context`` and ``app.state.broadcaster``. The
    broadcaster is the second consumer of the live event stream: startup gives
    it its subscription and its ~1 Hz task, and shutdown closes every connected
    client. The context is what makes ``GET /api/v1/aircraft/current`` and the
    WebSocket snapshot one implementation rather than two.

    Args:
        data_dir: overrides data-directory resolution (``FLIGHTSITE_DATA_DIR``,
            then ``/opt/flightsite/data``). Used by tests.
    """
    store = ConfigStore(data_dir)
    settings = store.load()

    # settings.log_level already reflects FLIGHTSITE_LOG_LEVEL when set — the
    # environment outranks config.yaml inside the settings model — so passing
    # it here keeps the env override winning (SPEC §30).
    #
    # Rotating file logs live beside the data they describe (SPEC §68), which
    # keeps them inside the one directory backup and restore already cover.
    configure_logging(
        level=settings.log_level,
        log_dir=store.data_dir / DEFAULT_LOG_DIR,
        file_logging_enabled=settings.log_file_enabled,
    )

    # SPEC §73's "Reset FlightSite Data" is mark-and-restart (slice 045,
    # flightsite.reset.marker): POST /api/internal/reset/data only writes a
    # marker file and asks the operator to restart. A pending marker is
    # applied here — before Database is even constructed below — so the
    # migration that follows always creates a brand new database rather than
    # migrating one this same call is about to delete out from under it.
    reset_applied = apply_pending_reset(store.data_dir)

    # docs/API.md §2.10 places the published schema and its interactive docs
    # under the versioned prefix, not at the server root: the OpenAPI document
    # describes /api/v1 and nothing else, so it belongs beside what it
    # describes. The internal router is excluded from it below.
    app = FastAPI(
        title="FlightSite",
        version=__version__,
        lifespan=_lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.config_store = store
    app.state.settings = settings
    # Tee WARNING-and-above into the diagnostics ring (SPEC §67). The provider
    # reads `app.state.settings` per record rather than closing over the object
    # loaded above, because PUT /api/internal/config replaces it in place — so
    # a key saved through the Settings UI is redacted from captured errors
    # immediately, not at the next restart.
    install_error_capture(
        error_ring,
        lambda: secrets_from_settings(getattr(app.state, "settings", None)),
    )
    # True exactly on the first create_app() call after a reset marker was
    # written; tests and startup logging read it, nothing else depends on it.
    app.state.data_reset_applied = reset_applied
    app.state.readiness = ReadinessRegistry()
    app.state.readiness.register(DATABASE_SUBSYSTEM)
    app.state.database = Database(database_path(store.data_dir))
    # The live registry is always present, even on a first run with no
    # decoder: request handlers can then read `app.state.live` unconditionally
    # instead of guarding every access. Constructing it starts nothing.
    app.state.live = _build_live_store(settings)
    app.state.persistence = _build_persistence_worker(app, settings)
    # The metadata subsystem: a source registry (mictronics as of slice 022;
    # faa joins in 023), the import orchestration behind slice 025's update
    # action, and the in-memory metadata & rarity cache. Constructing it
    # subscribes to nothing and opens no connection; the lifespan hook starts
    # the cache, and a registered provider only touches the network once an
    # import actually runs.
    # Nearest-airport context (SPEC §41). Constructed before the metadata
    # service because that service holds the registry the airport dataset
    # registers with, and the post-import listener that rebuilds this
    # service's index.
    airport_repository = AirportRepository(app.state.database)
    app.state.airports = AirportContextService(
        live=app.state.live,
        persistence=app.state.persistence,
        repository=airport_repository,
    )
    # Watchlists (SPEC §42, roadmap slice 037): CRUD plus the in-memory match
    # index. Constructed before the metadata service because that service's
    # cache takes the index's `on_resolved` observer — see the metadata
    # cache's own docstring ("Observing resolved views") for why matching by
    # registration/type/operator/category piggy-backs on the cache's
    # population pipeline instead of a second live-event subscription.
    app.state.watchlists = WatchlistService(database=app.state.database)
    app.state.metadata = MetadataService(
        database=app.state.database,
        live=app.state.live,
        data_dir=store.data_dir,
        registry=_build_metadata_registry(airport_repository, settings),
        # Both listeners read `app.state` when they run rather than closing
        # over an object, so registering them here — before the services they
        # reach for even exist — is safe and keeps the wiring in one place.
        listeners=(_rebuild_airport_index(app), _record_activity(app)),
        on_resolved=app.state.watchlists.matcher.on_resolved,
    )
    # Optional route enrichment (SPEC §28). `build_provider` returns None
    # unless the flag is set *and* a key is present, and a service with no
    # provider starts nothing and subscribes to nothing — so a stock install
    # cannot make an external call, whatever else happens at runtime. This is
    # the provider the process *boots* with, not the only one it can hold:
    # `PUT /api/internal/config` runs the same function again on every save and
    # applies the result (issue #161), so the same rule decides at boot and at
    # runtime and the guarantee above holds at every instant, not just at this
    # one.
    route_cache = RouteCacheRepository(app.state.database)
    app.state.enrichment = EnrichmentService(
        live=app.state.live,
        persistence=app.state.persistence,
        cache=route_cache,
        provider=build_provider(settings),
    )
    # Database maintenance (SPEC §70, slice 044): a sixth low-frequency task
    # running the integrity check, retention pruning, `PRAGMA optimize`, WAL
    # checkpoint management and a heavily guarded VACUUM on their own cadences.
    # It is handed the one prunable domain that has no owner of its own —
    # `route_cache`, whose expired rows were previously ignored on read but
    # never deleted; the receiver metrics and the track checkpoints prune
    # themselves, and `flightsite.maintenance.retention` documents why. The
    # live store is read only for the VACUUM pressure heuristic. Constructing
    # it opens nothing and starts no task.
    app.state.maintenance = MaintenanceService(
        database=app.state.database,
        retention=(RouteCachePruner(route_cache),),
        live=app.state.live,
    )
    # Receiver metrics (SPEC §60/§64, ADR-0009): the decoder's own statistics
    # plus FlightSite's, on a rolling high-resolution window with permanent
    # hourly/daily summaries and lifetime records. Its own two low-frequency
    # tasks (``docs/ARCHITECTURE.md`` §3.3's "stats poller / maintenance
    # scheduler"), writing through the same single writer as everything else.
    app.state.receiver_metrics = _build_receiver_metrics(app, settings)
    # Analytics rollups (SPEC §58/§59, docs/DATA_MODEL.md §6.5). A fifth
    # low-frequency background task, driven by the persistence worker's
    # sighting-lifecycle seam and writing through the same single writer
    # as everything else. Constructing it subscribes to nothing and opens
    # no connection; `start()` runs the backfill and attaches the seam.
    app.state.analytics = AnalyticsService(
        database=app.state.database,
        persistence=app.state.persistence,
        timezone=settings.timezone,
    )
    # Activity and milestones (SPEC §54/§55, docs/DATA_MODEL.md §5). A sixth
    # low-frequency background task, and the second consumer of the sighting
    # worker's lifecycle seam. It writes through the same single writer as
    # everything else and publishes what it wrote onto the WebSocket's
    # `activity` frame (docs/API.md §4.4). Constructing it subscribes to
    # nothing and opens no connection.
    app.state.activity = ActivityService(
        database=app.state.database,
        persistence=app.state.persistence,
        health=_decoder_health(app),
    )
    app.state.activity.subscribe(_broadcast_activity(app))
    # Interesting-aircraft alerting (SPEC §43 to §48, docs/DATA_MODEL.md §4.2
    # and §4.3). A seventh background task and a fifth consumer of the live
    # event stream: it evaluates each aircraft's rules on its own updates from
    # purely in-memory inputs — the live record, the metadata cache's resolved
    # view and rarity counters, the watchlist match index, and the persistence
    # worker's open accumulator — so nothing on this path can reach SQLite.
    # Matches are written on its own writer transaction; the sighting's
    # `max_alert_severity` rides the persistence worker's, exactly as an
    # enriched route does; and the activity feed takes what was created through
    # the listener wired below. Constructing it subscribes to nothing and opens
    # no connection.
    app.state.alerts = AlertService(
        database=app.state.database,
        live=app.state.live,
        metadata=app.state.metadata.cache,
        watchlists=app.state.watchlists,
        persistence=app.state.persistence,
        template_keys=settings.alerts.enabled_templates,
        alert_radius=_alert_radius(app),
    )
    app.state.alerts.engine.subscribe(_record_alert_matches(app))
    # Slice 025's update-in-progress coordinator: the background task the
    # current "Update Aircraft Metadata" run is executing in, and when it
    # started. ``None`` means no run has ever been triggered on this process.
    # Read and written only from ``POST /api/internal/metadata/update``
    # handlers, which never ``await`` between checking and replacing it, so
    # two overlapping requests on the same event loop cannot both start a run.
    app.state.metadata_update_task = None
    app.state.metadata_update_started_ms = None
    app.state.start_time = time.monotonic()
    # Read once at app-construction time, not per-request: demo mode is a
    # process-level run mode (FLIGHTSITE_DEMO), not something that changes
    # while the app is up.
    app.state.demo_enabled = demo_enabled()
    # One assembler for the live payloads, shared by REST and the WebSocket so
    # the two cannot describe the same instant differently. It reads app.state
    # lazily, so it is safe to build before the lifespan hook has started
    # anything and it follows `PUT /api/internal/config` replacing settings.
    app.state.api_context = LiveApiContext(app)
    app.state.broadcaster = LiveBroadcaster(context=app.state.api_context)

    app.include_router(v1_router, prefix="/api/v1")
    # /api/internal is an unsupported, unversioned surface (ADR-0007) and is
    # kept out of the OpenAPI schema published for /api/v1. One flag here
    # covers every internal endpoint, now and in later slices.
    app.include_router(internal_router, prefix="/api/internal", include_in_schema=False)

    return app
