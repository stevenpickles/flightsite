"""The ingestion loop: runs an adapter and fans batches out to consumers.

One asyncio task drains a :class:`~flightsite.ingest.protocol.DecoderAdapter`
and hands each batch to every subscriber. In production the subscriber is the
live aircraft state store (:class:`flightsite.live.LiveStore`), which the app
passes in as the sole consumer. :func:`null_sink` remains the default for a
service constructed without one, so "nothing consumes this service" stays an
explicit, testable fact rather than an empty list that might mean anything.

Readiness
---------

**A decoder outage must never fail ``/ready``.** FlightSite is genuinely
usable without a decoder: history, analytics, settings and the setup wizard
all work, and a first-run install has no decoder configured at all. Wiring
decoder health into readiness would make an orchestrator restart the backend
because something *outside* it went offline — the opposite of helpful — and it
would put the app into a crash loop during exactly the outage a user needs the
UI to explain.

So the service registers ``ingestion`` with the readiness registry and marks
it ready as soon as the loop task is running, which is the condition
``docs/API.md`` §3.1 states (*"ingestion loop started"*), and never marks it
not-ready afterwards. Decoder connectivity is reported through
:class:`~flightsite.ingest.health.AdapterHealth` — diagnostics and the UI
(slices 042/046) — not through readiness. When no receiver is configured the
service is not started at all and nothing is registered, so a first-run
install is ready immediately.

Consumer isolation
------------------

A subscriber that raises is logged and skipped; it cannot stop the loop or
starve the other subscribers. This is the same rule ``docs/ARCHITECTURE.md``
§3.1 states for the pipeline at large: a slow or broken consumer may lag, but
it must never stall the adapter.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Final

import structlog

from flightsite.ingest.health import AdapterHealth
from flightsite.ingest.protocol import DecoderAdapter
from flightsite.ingest.readsb import ReadsbJsonAdapter
from flightsite.ingest.types import AircraftStateBatch, DecoderEndpoint
from flightsite.readiness import ReadinessRegistry

logger = structlog.get_logger(__name__)

#: Readiness subsystem name. Registered only when ingestion actually starts.
READINESS_SUBSYSTEM: Final = "ingestion"

#: A consumer of normalized batches. Synchronous by design: applying a batch
#: to the in-memory live store is CPU work, and making it awaitable would
#: invite a consumer to do I/O on the ingestion path.
BatchConsumer = Callable[[AircraftStateBatch], None]


def null_sink(batch: AircraftStateBatch) -> None:
    """Discard a batch.

    The default consumer for a service built without one — a connection
    smoke test, a fixture, an adapter exercised on its own.
    """


class IngestionService:
    """Owns the adapter, its task, and the set of batch consumers."""

    def __init__(
        self,
        adapter: DecoderAdapter,
        *,
        readiness: ReadinessRegistry | None = None,
        consumers: tuple[BatchConsumer, ...] = (null_sink,),
    ) -> None:
        self._adapter = adapter
        self._readiness = readiness
        self._consumers: list[BatchConsumer] = list(consumers)
        self._task: asyncio.Task[None] | None = None
        self._batches = 0
        self._updates = 0

    @property
    def running(self) -> bool:
        """True while the ingestion task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def batches_ingested(self) -> int:
        """Number of batches handed to consumers since start."""
        return self._batches

    @property
    def updates_ingested(self) -> int:
        """Number of aircraft updates handed to consumers since start."""
        return self._updates

    def health(self) -> AdapterHealth:
        """Current decoder connection health."""
        return self._adapter.health()

    def subscribe(self, consumer: BatchConsumer) -> Callable[[], None]:
        """Register ``consumer`` for every future batch.

        Returns a callable that unsubscribes it, so a caller never has to hold
        onto the service to detach cleanly.
        """
        self._consumers.append(consumer)

        def unsubscribe() -> None:
            if consumer in self._consumers:
                self._consumers.remove(consumer)

        return unsubscribe

    async def start(self) -> None:
        """Start the adapter and the poll loop. Idempotent."""
        if self.running:
            return
        await self._adapter.start()
        self._task = asyncio.create_task(self._run(), name="flightsite-ingestion")
        if self._readiness is not None:
            self._readiness.register(READINESS_SUBSYSTEM)
            # Ready means "the loop is running", not "the decoder answered" —
            # see this module's docstring.
            self._readiness.mark_ready(READINESS_SUBSYSTEM)
        logger.info("ingestion_started")

    async def stop(self) -> None:
        """Stop the loop and the adapter. Idempotent, and safe before start."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._adapter.stop()
        logger.info("ingestion_stopped", batches=self._batches, updates=self._updates)

    async def _run(self) -> None:
        async for batch in self._adapter.updates():
            self._batches += 1
            self._updates += len(batch)
            self._dispatch(batch)

    def _dispatch(self, batch: AircraftStateBatch) -> None:
        for consumer in list(self._consumers):
            try:
                consumer(batch)
            except Exception as exc:
                logger.warning(
                    "ingestion_consumer_error",
                    consumer=getattr(consumer, "__name__", type(consumer).__name__),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )


def build_ingestion_service(
    endpoint: DecoderEndpoint,
    *,
    readiness: ReadinessRegistry | None = None,
    consumers: tuple[BatchConsumer, ...] = (null_sink,),
) -> IngestionService:
    """Build the v1 ingestion service: a polling readsb/dump1090-fa adapter.

    ``consumers`` replaces the default sink outright rather than adding to it,
    so the app hands in the live store and no batch is handed to a discard
    function on the hot path.
    """
    return IngestionService(ReadsbJsonAdapter(endpoint), readiness=readiness, consumers=consumers)


__all__ = [
    "READINESS_SUBSYSTEM",
    "BatchConsumer",
    "IngestionService",
    "build_ingestion_service",
    "null_sink",
]
