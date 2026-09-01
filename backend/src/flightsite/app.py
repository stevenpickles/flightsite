"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI

from flightsite import __version__
from flightsite.airports import (
    AIRPORTS_SOURCE,
    AirportContextService,
    AirportImportSink,
    AirportRepository,
    OurAirportsProvider,
)
from flightsite.api.context import LiveApiContext
from flightsite.api.internal import router as internal_router
from flightsite.api.v1 import router as v1_router
from flightsite.api.ws import LiveBroadcaster
from flightsite.config import ConfigStore, Settings
from flightsite.db import Database, database_path, initialize_database
from flightsite.db.startup import DATABASE_SUBSYSTEM
from flightsite.demo import DEFAULT_CENTER, DemoAdapter, demo_enabled
from flightsite.enrichment import EnrichmentService, RouteCacheRepository
from flightsite.enrichment.service import build_provider
from flightsite.ingest import DecoderEndpoint, IngestionService, Position, build_ingestion_service
from flightsite.live import LiveStore
from flightsite.logging import configure_logging
from flightsite.metadata import ImportListener, ImportRun, MetadataService
from flightsite.metadata.registry import SourceRegistry
from flightsite.metadata.sources import FaaRegistryProvider, MictronicsProvider
from flightsite.readiness import ReadinessRegistry
from flightsite.receiver_metrics import ReceiverMetricsService, StatsJsonPoller
from flightsite.sightings import PersistenceWorker

logger = structlog.get_logger(__name__)


def _decoder_endpoint(settings: Settings) -> DecoderEndpoint:
    """Translate the receiver section of settings into an ingestion endpoint."""
    receiver = settings.receiver
    return DecoderEndpoint(
        host=receiver.host,
        port=receiver.port,
        path=receiver.path,
        poll_interval_s=receiver.poll_interval_s,
    )


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


def _build_metadata_registry(airports: AirportRepository) -> SourceRegistry:
    """The datasets this build ships.

    Slice 022 registers ``mictronics`` (the offline primary source); slice 023
    adds ``faa``; slice 027 adds ``airports``, which is not aircraft metadata
    at all — it supplies its own :class:`~flightsite.metadata.sink.ImportSink`
    and shares everything else, so slice 025's update action imports it and
    reports its status independently (SPEC §27).

    Constructing a provider here opens nothing — it downloads only when an
    import actually runs (:mod:`flightsite.metadata.importer`).
    """
    registry = SourceRegistry()
    registry.register("mictronics", MictronicsProvider())
    registry.register("faa", FaaRegistryProvider())
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

    Constructing it opens nothing: no HTTP client, no session, no task.
    """
    store: ConfigStore = app.state.config_store
    poller = (
        None if store.first_run or demo_enabled() else StatsJsonPoller(_decoder_endpoint(settings))
    )
    return ReceiverMetricsService(
        database=app.state.database,
        live=app.state.live,
        poller=poller,
        timezone=settings.timezone,
        high_res_days=settings.retention.high_res_metric_days,
    )


async def _start_ingestion(app: FastAPI) -> IngestionService | None:
    """Start decoder ingestion, unless this install has never been configured.

    On a first run there is no ``config.yaml``, so there is no receiver the
    user has actually chosen — only model defaults. Polling those would
    produce a stream of connection failures and a ``down`` decoder before the
    setup wizard has even been opened, so ingestion is skipped and starts on
    the next boot after a configuration is saved.

    Demo mode (``FLIGHTSITE_DEMO=1``, slice 011) is the one exception: it
    starts :class:`~flightsite.demo.DemoAdapter` regardless of first-run
    state, because demo mode's whole purpose is a full stack with zero
    configuration (SPEC §76). A receiver location is injected into the live
    store when none is configured, so distance and bearing still compute.

    The live store is the sole consumer: every normalized batch goes straight
    into the in-memory registry, and nothing on this path touches the database
    (``docs/ARCHITECTURE.md`` §3.1).

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
        return service

    store: ConfigStore = app.state.config_store
    if store.first_run:
        logger.info("ingestion_skipped", reason="first_run")
        return None

    service = build_ingestion_service(
        _decoder_endpoint(app.state.settings),
        readiness=app.state.readiness,
        consumers=(live.apply,),
    )
    await service.start()
    return service


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

    # The lifecycle sweep runs whether or not a decoder is configured: an
    # empty live set costs nothing to sweep, and starting it unconditionally
    # means the store behaves identically the moment ingestion does start.
    await live.start()
    # Started before ingestion, so the broadcaster's subscription is attached
    # before the first decoder batch is applied: a client connecting during
    # startup then gets a snapshot and a continuous delta stream, never a
    # snapshot followed by a gap.
    await broadcaster.start()
    app.state.ingestion = await _start_ingestion(app)
    readiness.mark_startup_complete()
    logger.info("app_startup_complete")
    try:
        yield
    finally:
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
        await metadata.stop()
        # Stopped before the engines close because its final flush is a real
        # write: an interval of samples, and the lifetime increments they
        # carry, are in memory at this point. It takes the same writer lock
        # the persistence worker does, so the two simply serialize.
        await receiver_metrics.stop()
        await persistence.stop()
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

    The ``database`` subsystem is registered here, not in the lifespan hook,
    so it reads as not-ready from the very first request; the lifespan hook
    migrates the database and marks it ready. Constructing
    :class:`~flightsite.db.Database` opens nothing and creates no directory —
    building an app is still side-effect free.

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
    every route stays ``null``. When it is on, routes reach the database through
    the persistence worker's accumulator rather than a writer session of its
    own, which is why it is stopped before that worker on shutdown.

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
    configure_logging(level=settings.log_level)

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
    app.state.metadata = MetadataService(
        database=app.state.database,
        live=app.state.live,
        data_dir=store.data_dir,
        registry=_build_metadata_registry(airport_repository),
        listeners=(_rebuild_airport_index(app),),
    )
    # Optional route enrichment (SPEC §28). `build_provider` returns None
    # unless the flag is set *and* a key is present, and a service with no
    # provider starts nothing and subscribes to nothing — so a stock install
    # cannot make an external call, whatever else happens at runtime.
    app.state.enrichment = EnrichmentService(
        live=app.state.live,
        persistence=app.state.persistence,
        cache=RouteCacheRepository(app.state.database),
        provider=build_provider(settings),
    )
    # Receiver metrics (SPEC §60/§64, ADR-0009): the decoder's own statistics
    # plus FlightSite's, on a rolling high-resolution window with permanent
    # hourly/daily summaries and lifetime records. Its own two low-frequency
    # tasks (``docs/ARCHITECTURE.md`` §3.3's "stats poller / maintenance
    # scheduler"), writing through the same single writer as everything else.
    app.state.receiver_metrics = _build_receiver_metrics(app, settings)
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
