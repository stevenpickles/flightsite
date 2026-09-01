"""The enrichment worker: eligible callsigns in, routes onto sightings out.

The seam, and why it is this one
--------------------------------

Two places could have driven enrichment: a hook inside
:class:`~flightsite.sightings.worker.PersistenceWorker`'s cycle, or an
independent consumer of the live event stream. This is the second, for the
reason ``docs/ARCHITECTURE.md`` §3.1 gives for putting bounded queues between
the live store and everything downstream: *"A slow consumer can lag or drop to
a resync; it cannot stall the adapter loop."*

A hook inside the persistence cycle would have put a network call — with a
timeout measured in seconds — inside the transaction discipline of the
process's **only** SQLite writer. A slow AeroDataBox would then have been a
slow database, which would have been shed live events. So this service holds
its own bounded subscription, exactly as
:class:`~flightsite.metadata.cache.MetadataCache` does, and runs on its own
tasks. The live store publishes with ``put_nowait`` and returns; nothing on the
ingestion path or the API path can reach this module at all.

What it does borrow is the *write* discipline. When a route arrives it calls
:meth:`~flightsite.sightings.worker.PersistenceWorker.apply_route`, which sets
the accumulator's running values and queues the ``route_enriched`` event — so
the route and its event land in the worker's next cycle, in one transaction,
retried together if that cycle fails. Enrichment never opens a writer session
for a sighting; the only writes it makes of its own are to ``route_cache``.

Two tasks, and why
------------------

A **reader** drains live events and queues eligible callsigns; a **worker**
drains that queue through the limiter to the provider. They are separate
because the reader must never await a network call: if it did, a ten-second
timeout would be ten seconds of live events piling into the subscription, and
the queue bound would start shedding for a reason that has nothing to do with
the queue being too small.

The gates
---------

Each eligible observation walks four gates, cheapest first, and the first one
that answers ends the walk:

1. **Configuration.** Disabled, or no key, and the service does not start at
   all — a build with enrichment switched off makes zero external calls, which
   is an acceptance criterion and a test.
2. **Eligibility** (:mod:`flightsite.enrichment.policy`). Only callsigns in the
   ICAO airline-flight form are ever looked up.
3. **Answers already held**, in memory: the last few thousand keys this process
   has resolved. This gate is what keeps a 1 Hz observation stream from costing
   a database read per poll for an aircraft whose route is already known — or
   already known not to exist.
4. **The cache table** (:mod:`flightsite.enrichment.cache`), which survives a
   restart and is shared across every aircraft flying the same number.

Only what survives all four reaches the circuit breaker, the rate limiter and
the provider.

Bounded, and honest about it
----------------------------

The pending-lookup queue is bounded (:data:`DEFAULT_PENDING_LIMIT`) and sheds
the **oldest** key on overflow, the same policy and for the same reason as the
live event stream: the newest sky is the one worth enriching, and a queue that
grew without bound would trade a missing route for memory. Shedding increments
:attr:`EnrichmentService.dropped` and logs once per episode, never once per key.

Failures are values, never exceptions that escape a task. A provider that
cannot answer increments ``enrichment_failures`` and feeds the circuit breaker;
the sighting keeps its ``Unknown`` route, which is what SPEC §28 asks for and
what ``docs/API.md`` §2.7 makes the display of. Nothing in this module can
write a route the provider did not report.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

import structlog

from flightsite.config import Settings
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import utc_now_ms
from flightsite.enrichment.aerodatabox import AeroDataBoxProvider
from flightsite.enrichment.cache import RouteCacheRepository
from flightsite.enrichment.limits import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RATE_PER_MINUTE,
    CircuitBreaker,
    MonotonicClock,
    TokenBucket,
)
from flightsite.enrichment.model import RouteInfo, RouteUnavailable
from flightsite.enrichment.policy import cache_key, eligible_callsign
from flightsite.enrichment.provider import RouteEnrichmentProvider
from flightsite.live.aircraft import LiveAircraft
from flightsite.live.events import (
    AircraftAppeared,
    AircraftUpdated,
    EventSubscription,
    LiveEvent,
)
from flightsite.live.store import LiveStore
from flightsite.sightings.state import SightingRoute
from flightsite.sightings.worker import PersistenceWorker

logger = structlog.get_logger(__name__)

#: Counter incremented when a provider could not answer. Predeclared in
#: :data:`flightsite.counters.KNOWN_COUNTERS` and surfaced by
#: ``/api/v1/health``.
ENRICHMENT_FAILURES_COUNTER: Final = "enrichment_failures"

#: A source of UTC epoch milliseconds, injected for tests.
EpochClock = Callable[[], int]

#: Live events buffered for this service before the store sheds the oldest.
#: Smaller than the persistence worker's: recovery from a shed event costs one
#: delayed lookup, not a corrupted history, and the aircraft is observed again
#: on the next decoder poll.
DEFAULT_QUEUE_SIZE: Final = 1024

#: Callsign lookups that may be queued at once. A sky of a thousand aircraft
#: holds a few hundred distinct airline callsigns, so this is a buffer rather
#: than a bottleneck, and a stalled provider costs kilobytes.
DEFAULT_PENDING_LIMIT: Final = 256

#: Answers remembered in memory. Bounded and evicted oldest-first; losing an
#: entry costs one indexed read of ``route_cache``, never a provider request,
#: because the table gate still stands behind it.
DEFAULT_ANSWER_LIMIT: Final = 4096

#: How long the worker task waits when there is nothing it may do yet. A poll
#: rather than a computed sleep because the limiter is deliberately
#: non-blocking (:mod:`flightsite.enrichment.limits`); at one wake a second the
#: cost is nothing and the loop stays readable.
IDLE_POLL_S: Final = 1.0


def build_provider(settings: Settings) -> RouteEnrichmentProvider | None:
    """The configured route provider, or ``None`` if there is not one.

    ``None`` is the whole of "enrichment is off": the flag unset, or no key.
    Deciding it here rather than inside the service is what makes the
    zero-external-calls guarantee structural — with no provider there is no
    object in the process that knows how to make the request.
    """
    enrichment = settings.enrichment
    if not enrichment.aerodatabox_enabled or enrichment.aerodatabox_api_key is None:
        return None
    return AeroDataBoxProvider(api_key=enrichment.aerodatabox_api_key)


@dataclass(slots=True)
class _PendingLookup:
    """One queued callsign and the aircraft waiting on its answer.

    Several aircraft can share one key across a day — a flight number flown by
    a substituted airframe, or the same flight seen twice either side of a
    closure gap — and every sighting that was waiting deserves the answer the
    single request bought.
    """

    callsign: str
    icaos: set[str] = field(default_factory=set)


class EnrichmentService:
    """Consumes the live stream and enriches eligible sightings with routes.

    Args:
        live: the live store to subscribe to.
        persistence: the worker owning the open sightings; routes are applied
            through it so they ride its transaction discipline.
        cache: the ``route_cache`` repository.
        provider: the route provider, or ``None`` for a disabled install — in
            which case :meth:`start` subscribes to nothing, creates no task,
            and no request is ever made.
        rate_per_minute: sustained provider request rate.
        failure_threshold: consecutive failures that open the circuit.
        cooldown_s: how long the circuit stays open.
        queue_size: bounded live-event subscription capacity.
        pending_limit: bounded pending-lookup queue capacity.
        clock: UTC epoch milliseconds, injected for tests.
        monotonic: monotonic seconds for the limiter and breaker, injected so
            their rules are proved in microseconds rather than minutes.
        counters: registry receiving ``enrichment_failures``.
    """

    __slots__ = (
        "_answer_limit",
        "_answers",
        "_breaker",
        "_cache",
        "_clock",
        "_counters",
        "_dropped",
        "_idle",
        "_inflight",
        "_limiter",
        "_live",
        "_lookups",
        "_overflowed",
        "_pending",
        "_pending_limit",
        "_persistence",
        "_provider",
        "_queue_size",
        "_reader",
        "_subscription",
        "_worker",
    )

    def __init__(
        self,
        *,
        live: LiveStore,
        persistence: PersistenceWorker,
        cache: RouteCacheRepository,
        provider: RouteEnrichmentProvider | None,
        rate_per_minute: float = DEFAULT_RATE_PER_MINUTE,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        pending_limit: int = DEFAULT_PENDING_LIMIT,
        answer_limit: int = DEFAULT_ANSWER_LIMIT,
        clock: EpochClock = utc_now_ms,
        monotonic: MonotonicClock = time.monotonic,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if pending_limit < 1:
            raise ValueError("pending_limit must be at least one")
        if answer_limit < 1:
            raise ValueError("answer_limit must be at least one")
        self._live = live
        self._persistence = persistence
        self._cache = cache
        self._provider = provider
        self._queue_size = queue_size
        self._pending_limit = pending_limit
        self._answer_limit = answer_limit
        self._clock = clock
        self._counters = counters
        self._limiter = TokenBucket(rate_per_minute=rate_per_minute, clock=monotonic)
        self._breaker = CircuitBreaker(
            failure_threshold=failure_threshold, cooldown_s=cooldown_s, clock=monotonic
        )

        self._subscription: EventSubscription | None = None
        self._reader: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        #: Queued keys, oldest first. An ordered mapping rather than a queue so
        #: two observations of one flight coalesce into a single lookup.
        self._pending: OrderedDict[str, _PendingLookup] = OrderedDict()
        #: Answers this process already holds, keyed as the cache is.
        #: ``None`` means "asked, and there is no route" — remembered as firmly
        #: as a route, because it is the answer that saves the most requests.
        self._answers: OrderedDict[str, RouteInfo | None] = OrderedDict()
        self._inflight: str | None = None
        self._dropped = 0
        self._overflowed = False
        self._lookups = 0
        self._idle = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------ inspection

    @property
    def enabled(self) -> bool:
        """True when a provider is configured. ``False`` disables everything."""
        return self._provider is not None

    @property
    def running(self) -> bool:
        """True while the consumer tasks are alive."""
        return self._reader is not None and not self._reader.done()

    @property
    def dropped(self) -> int:
        """Pending lookups shed because the queue was full."""
        return self._dropped

    @property
    def lookups(self) -> int:
        """Provider requests made since start. Zero on a disabled install."""
        return self._lookups

    @property
    def pending(self) -> int:
        """Callsigns queued for a lookup right now."""
        return len(self._pending)

    @property
    def circuit_open(self) -> bool:
        """True while the breaker is refusing requests."""
        return self._breaker.is_open

    async def wait_idle(self) -> None:
        """Wait until the worker task finishes the lookup it is in.

        Tests wait on this rather than sleeping, which is what keeps the suite
        deterministic without a polling interval (``docs/TEST_STRATEGY.md`` §3).
        """
        await self._idle.wait()

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Subscribe and start consuming. Idempotent; a no-op when disabled.

        A disabled install returns having subscribed to nothing and created no
        task, which is the structural form of the acceptance criterion
        *"without key or offline: zero external calls, clean Unknowns"*.
        """
        provider = self._provider
        if provider is None or self.running:
            return
        self._subscription = self._live.subscribe("enrichment", maxsize=self._queue_size)
        self._reader = asyncio.create_task(self._read_loop(), name="flightsite-enrichment-read")
        self._worker = asyncio.create_task(self._lookup_loop(), name="flightsite-enrichment")
        logger.info("enrichment_started", provider=provider.name)

    async def stop(self) -> None:
        """Stop consuming, release the subscription and the client. Idempotent."""
        await self._cancel("_reader")
        await self._cancel("_worker")

        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()
        if self._provider is not None:
            await self._provider.aclose()
        self._idle.set()
        logger.info("enrichment_stopped", lookups=self._lookups, dropped=self._dropped)

    async def _cancel(self, attribute: str) -> None:
        task: asyncio.Task[None] | None = getattr(self, attribute)
        setattr(self, attribute, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # --------------------------------------------------------- the read side

    async def _read_loop(self) -> None:
        subscription = self._subscription
        if subscription is None:  # pragma: no cover - start() always sets one
            return
        while True:
            self.consider(await subscription.get())
            for queued in subscription.drain():
                self.consider(queued)
            if subscription.overflowed:
                # No resync is owed. Unlike the persistence worker this
                # consumer holds no history a gap could corrupt: a shed event
                # costs one delayed lookup, and the aircraft is observed again
                # on the next decoder poll.
                subscription.acknowledge_overflow()

    def consider(self, event: LiveEvent) -> None:
        """Queue a lookup for an observation that deserves one.

        Appear and update only. ``AircraftStale`` announces silence and carries
        nothing new; ``AircraftRemoved`` names an aircraft whose closure gap has
        already started, and spending a request on one that has gone is exactly
        the waste the eligibility policy exists to avoid.

        A disabled install considers nothing at all. :meth:`start` already
        subscribes to no events, so this guard is belt as well as braces — but
        it makes "no provider, no work" true of the object rather than only of
        its wiring.

        Public because it is the whole of the read side's decision, and tests
        drive it directly rather than through a task.
        """
        if self._provider is None:
            return
        if isinstance(event, AircraftAppeared | AircraftUpdated):
            self._enqueue(event.aircraft)

    def _enqueue(self, record: LiveAircraft) -> None:
        callsign = eligible_callsign(record.callsign)
        if callsign is None:
            return
        key = cache_key(callsign, record.last_seen)

        if key in self._answers:
            # Already answered this process. Applying is idempotent, so this
            # also covers the second aircraft to fly the number today and the
            # sighting that reopened after a gap.
            self._answers.move_to_end(key)
            self._apply(key, self._answers[key], (record.icao,))
            return
        if key == self._inflight:
            # A lookup for this key is in the provider right now; ride it.
            self._pending.setdefault(key, _PendingLookup(callsign)).icaos.add(record.icao)
            return

        existing = self._pending.get(key)
        if existing is not None:
            existing.icaos.add(record.icao)
            return
        self._pending[key] = _PendingLookup(callsign, {record.icao})
        self._shed_if_full()

    def _shed_if_full(self) -> None:
        """Drop the oldest queued lookup once the bound is exceeded.

        Oldest-first for the reason the live event stream sheds that way: what
        is newest is what is still overhead. Logged once per episode, so an
        overloaded queue produces a warning rather than a flood.
        """
        while len(self._pending) > self._pending_limit:
            self._pending.popitem(last=False)
            self._dropped += 1
            if not self._overflowed:
                self._overflowed = True
                logger.warning(
                    "enrichment_queue_overflow",
                    capacity=self._pending_limit,
                    dropped=self._dropped,
                )

    # ------------------------------------------------------- the lookup side

    async def _lookup_loop(self) -> None:
        while True:
            if not await self.drain_once():
                await asyncio.sleep(IDLE_POLL_S)

    async def drain_once(self) -> bool:
        """Advance the head of the queue one step; ``True`` if it did anything.

        The whole of the lookup side's decision, in the order the gates are
        cheapest: an answer already held, then the cache table, then the
        circuit, then the limiter, then a request. Public so tests step it one
        call at a time instead of racing a background task.
        """
        if not self._pending:
            return False
        key = next(iter(self._pending))
        lookup = self._pending[key]

        self._idle.clear()
        self._inflight = key
        try:
            return await self._advance(key, lookup)
        finally:
            self._inflight = None
            self._idle.set()

    async def _advance(self, key: str, lookup: _PendingLookup) -> bool:
        # A queued key is never one this process has already answered:
        # `_enqueue` applies a remembered answer instead of queueing, and
        # `_finish` — the only writer of `_answers` — takes the key off the
        # queue in the same call. So the memory gate is upstream of here and
        # this method starts at the cache.
        #
        # The cache before the limits: a hit spends no request, and a route
        # already on disk is worth applying even while the circuit is open —
        # ``docs/ARCHITECTURE.md`` §"Degradation" keeps cached enrichment
        # working through an outage.
        cached = await self._cache.get(key, now_ms=self._clock())
        if cached is not None:
            answer = cached.as_lookup()
            self._finish(key, answer if isinstance(answer, RouteInfo) else None)
            return True

        if not self._breaker.allow():
            # Silently absent while the circuit is open, and dropped rather
            # than requeued: the next observation of this flight queues it
            # again, which is a retry paced by the sky instead of by a loop.
            self._pending.pop(key, None)
            return True
        if not self._limiter.take():
            # The key keeps its place. A limiter is a delay, not a refusal.
            return False

        await self._request(key, lookup)
        return True

    async def _request(self, key: str, lookup: _PendingLookup) -> None:
        """Ask the provider, then record and apply whatever it said."""
        provider = self._provider
        if provider is None:  # pragma: no cover - the loop only runs when enabled
            return
        self._lookups += 1
        result = await provider.lookup(lookup.callsign)
        now_ms = self._clock()

        if isinstance(result, RouteUnavailable):
            self._breaker.record_failure()
            self._counters.increment(ENRICHMENT_FAILURES_COUNTER)
            # Deliberately neither cached nor remembered: an unavailability is
            # a fact about the network, not about the flight. The key is
            # dropped so the sky, not a retry loop, decides when to ask again.
            self._pending.pop(key, None)
            return

        self._breaker.record_success()
        if isinstance(result, RouteInfo):
            await self._cache.store_route(key, result, now_ms=now_ms)
            self._finish(key, result)
        else:
            await self._cache.store_not_found(key, now_ms=now_ms)
            self._finish(key, None)

    def _finish(self, key: str, answer: RouteInfo | None) -> None:
        """Remember an answer, apply it, and take the key off the queue."""
        self._remember(key, answer)
        lookup = self._pending.pop(key, None)
        if lookup is not None:
            self._apply(key, answer, tuple(sorted(lookup.icaos)))

    def _apply(self, key: str, answer: RouteInfo | None, icaos: tuple[str, ...]) -> None:
        """Attach a found route to every sighting that was waiting for it.

        ``answer is None`` — the provider has no route — writes nothing: the
        sighting keeps its ``NULL`` route columns, which is the honest record
        and what the API renders as Unknown. There is no branch here in which a
        route FlightSite was not told about could be written.
        """
        provider = self._provider
        if answer is None or provider is None:
            return
        route = SightingRoute(
            origin_ident=answer.origin_ident,
            destination_ident=answer.destination_ident,
            source=provider.name,
        )
        at_ms = self._clock()
        for icao in icaos:
            self._persistence.apply_route(icao, route, at_ms=at_ms)
        logger.debug("enrichment_applied", cache_key=key, aircraft=len(icaos))

    def _remember(self, key: str, answer: RouteInfo | None) -> None:
        self._answers[key] = answer
        self._answers.move_to_end(key)
        while len(self._answers) > self._answer_limit:
            self._answers.popitem(last=False)


__all__ = [
    "DEFAULT_ANSWER_LIMIT",
    "DEFAULT_PENDING_LIMIT",
    "DEFAULT_QUEUE_SIZE",
    "ENRICHMENT_FAILURES_COUNTER",
    "IDLE_POLL_S",
    "EnrichmentService",
    "EpochClock",
    "build_provider",
]
