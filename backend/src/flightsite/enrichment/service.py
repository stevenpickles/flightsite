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

Each eligible observation walks six gates, cheapest first, and the first one
that answers ends the walk:

1. **Configuration.** Nothing to consult — no provider *and* no directory — and
   the service does not start at all. A build with **no key** does start, and
   answers from the cache and the directory; it simply holds no object that
   knows how to make a request, which is what "zero external calls without a
   key" has always meant and still does.
2. **Eligibility** (:mod:`flightsite.enrichment.policy`). Only callsigns in the
   ICAO airline-flight form are ever looked up.
3. **Answers already held**, in memory: the last few thousand callsigns this
   process has resolved, each with the expiry its cache row carries. This gate
   is what keeps a 1 Hz observation stream from costing a database read per
   poll for an aircraft whose route is already known — or already known not to
   exist.
4. **The cache table** (:mod:`flightsite.enrichment.cache`), which survives a
   restart and is shared across every aircraft flying the same number.
5. **The offline route directory** (:mod:`flightsite.enrichment.directory`) —
   619,770 callsigns of Virtual Radar Server standing data, one indexed
   primary-key read, and free. SPEC §28's 2026-09-05 amendment makes this the
   *primary* source; ADR-0016 has the reasoning. A hit is written into the
   cache tagged ``vrs`` and applied to the sighting, and the provider is never
   asked.
6. **The daily budget**, if the owner set one. A day's lookups are counted from
   ``route_cache`` rather than from a process counter, so a restart does not
   hand the install a fresh allowance.

Only what survives all six reaches the circuit breaker, the rate limiter and
the provider — which is now the *fallback*, spending credits only on the
callsigns the directory has never heard of. The budget, the priority order and
the breaker govern **provider requests only**: a directory hit is free, is
counted separately as ``cache.directory_hits``, and is unaffected by a spent
budget or an open circuit.

Without a key
-------------

A key-less install runs everything above except the last step. It answers from
the cache and the directory, writes ``route_source: vrs`` onto sightings, and
never constructs a request — because :func:`build_provider` returned ``None``
and there is no object in the process that could. That is the same structural
guarantee slice 026 shipped, restated: *no provider, no external call* is
unchanged; *no provider, no work* is what stopped being true, and had to,
because SPEC §28's amendment makes the offline directory the primary source and
an install that had imported 619,770 routes was showing Unknown for all of
them.

A callsign the directory does not know, on an install with no provider, has
nobody left to ask. It is left alone for :data:`UNANSWERABLE_BACKOFF_S` rather
than re-walked on every observation — in memory only, because "this install
cannot find a route" is not the same claim as "there is no route" and must
never reach the cache table where the two would be indistinguishable.

When nobody can answer
----------------------

A cached route that has expired, a directory that does not know the callsign,
and a provider that cannot be asked — a spent budget, an open circuit, a 429, a
timeout — used to mean the sighting lost its route until the outage ended.
Slice 071 serves the expired row instead: it is what was true last week, and a
week-old origin and destination are worth more than an ``Unknown`` bought by
strictness. The row's expiry is pushed a day out so one outage costs one stale
serve rather than one per observation, ``route_cache_stale_served`` is logged
once per callsign per UTC day, and diagnostics counts it in
``enrichment.cache.stale_served``. Nothing is fabricated: the route served is
one a source reported, with the provenance that source earned.

Which lookup goes first
-----------------------

The pending queue drains in priority order rather than FIFO, because a bounded
queue that is also budget-bounded has to answer *which* callsigns the day's
credits buy:

0. an aircraft **currently matching an alert rule** — the sky FlightSite was
   asked to care about;
1. an aircraft inside ``display_radius_nm`` — what the map is showing now;
2. everything else;
3. **refreshes** of routes this process already answered once and whose answer
   has expired. The sighting reads correctly from the row that is about to be
   replaced, so a refresh losing a race to a first answer costs nothing.

The two probes are closures over ``app.state`` in the style of
:func:`flightsite.app._alert_radius`, not services this module depends on: the
question "is this aircraft alerting?" is asked of whatever the app holds *now*,
and a service constructed without them simply treats everything as tier 2.

Catching a schedule change early
--------------------------------

A cached route is a claim, and the aircraft flying it can disprove that claim
faster than any TTL. When the airport-context service latches a *departure*
from a field the cached route does not call the origin — or an *arrival* at one
it does not call the destination — the row is invalidated and the next
observation buys a fresh answer
(:func:`flightsite.enrichment.policy.contradicts_route`). Once per callsign per
process: a route that disagrees twice is a disagreement about idents, not a
schedule change, and re-buying it on every observation would be the retry storm
this slice exists to stop.

A directory row is a claim of exactly the same kind, and is disproved the same
way — but the remedy differs in one respect, because the directory cannot be
*refreshed*. Community standing data goes stale between imports, so a
contradicted directory row is not merely invalidated: the callsign is put on a
skip list for the cache TTL and the re-ask goes to the **provider**, which is
the only source that can have a newer answer. Without that, a wrong directory
row would be re-read, re-cached, re-contradicted and re-read again — a loop
paced by the sky and answered every time by the same stale file.

Configured while it runs
------------------------

The first gate is decided by an object rather than by a branch, and that stayed
true when enrichment became a setting a user could change without a restart
(issue #161). :meth:`EnrichmentService.apply_provider` takes whatever
:func:`build_provider` made of the configuration that was just saved — a
provider, or ``None`` — and reconciles the running service with it: switching
on starts the tasks, switching off stops them and closes the client, and a new
key swaps the provider and starts again. What it does *not* do is keep an
enabled flag of its own to consult. "No provider, no external call" is still a
fact about the object graph, at every instant, which is why turning enrichment
off leaves nothing behind that could make a request.

Bounded, and honest about it
----------------------------

The pending-lookup queue is bounded (:data:`DEFAULT_PENDING_LIMIT`) and sheds
the **oldest** key on overflow, the same policy and for the same reason as the
live event stream: the newest sky is the one worth enriching, and a queue that
grew without bound would trade a missing route for memory. Shedding increments
:attr:`EnrichmentService.dropped` and logs once per episode, never once per key.
A spent budget changes nothing about that bound: the queue keeps filling and
shedding exactly as it does under a slow provider, and midnight finds it
holding the newest sky rather than a day-old backlog.

Failures are values, never exceptions that escape a task. A provider that
cannot answer increments ``enrichment_failures`` and feeds the circuit breaker;
the sighting keeps its ``Unknown`` route, which is what SPEC §28 asks for and
what ``docs/API.md`` §2.7 makes the display of. A *restricted* flight is not
one of those: HTTP 451 is the provider answering, so it is cached, counted in
neither the failures nor the breaker, and left Unknown (issue #165). Nothing in
this module can write a route the provider did not report.
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

from flightsite.airports.model import AirportContext
from flightsite.config import Settings
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import utc_now_ms
from flightsite.enrichment.aerodatabox import AeroDataBoxProvider
from flightsite.enrichment.cache import (
    DEFAULT_ROUTE_TTL_DAYS,
    LEARNED_TTL_S,
    MS_PER_SECOND,
    NEGATIVE_TTL_S,
    SECONDS_PER_DAY,
    STALE_EXTENSION_S,
    RouteCacheRepository,
    RouteWrite,
    utc_day_start_ms,
)
from flightsite.enrichment.directory import RouteDirectoryRepository
from flightsite.enrichment.limits import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RATE_PER_MINUTE,
    CircuitBreaker,
    MonotonicClock,
    TokenBucket,
)
from flightsite.enrichment.model import (
    ROUTE_SOURCE_VRS,
    RouteInfo,
    RouteRestricted,
    RouteUnavailable,
)
from flightsite.enrichment.policy import cache_key, contradicts_route, eligible_callsign
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

#: Logged once per UTC day, the first time the budget refuses a lookup. Once,
#: because the refusal repeats for every eligible callsign until midnight and a
#: line per refusal would be a log flood describing one decision.
BUDGET_EXHAUSTED_EVENT: Final = "enrichment_budget_exhausted"

#: Logged when an expired route is served because nothing could refresh it.
#: Once per callsign per UTC day, for the reason above: an outage lasting an
#: afternoon touches every callsign in the sky, and one line per serve would
#: describe the outage several thousand times.
STALE_SERVED_EVENT: Final = "route_cache_stale_served"

#: Logged when the airport context disproves a directory row. Distinct from
#: ``enrichment_route_invalidated`` because the remedy is different: this one
#: also skips the directory for that callsign, so the re-ask reaches a source
#: that can have a newer answer.
DIRECTORY_CONTRADICTED_EVENT: Final = "route_directory_contradicted"

#: A source of UTC epoch milliseconds, injected for tests.
EpochClock = Callable[[], int]

#: "Is this aircraft matching an alert rule right now?" — a closure over
#: ``app.state`` (:func:`flightsite.app._alert_radius`'s pattern), so the answer
#: follows a rule list the user edits without this service holding the engine.
AlertProbe = Callable[[str], bool]

#: "What field is this aircraft at, and what is it doing there?" — the airport
#: context service's own in-memory answer, read through a closure for the same
#: reason.
ContextProbe = Callable[[str], AirportContext | None]

#: "How far out is the map showing?" — ``display_radius_nm``, read per drain so
#: a saved change applies without a restart.
RadiusProbe = Callable[[], float | None]

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

#: How long a callsign nothing could answer is left alone (slice 071).
#:
#: A key-less install whose directory does not know a callsign has no answer to
#: remember and nothing to cache — an unanswerable callsign is not a *route*
#: fact, and writing a negative cache row would claim for a day that no route
#: exists when the truth is only that this install cannot find one. Without
#: some bound, though, every such callsign would cost two table reads on every
#: drain: a sky of two hundred airline callsigns at one decoder poll a second
#: is several hundred reads a second, forever, on the install least able to
#: afford them.
#:
#: A minute is the compromise. It costs a few reads a second at worst, and it
#: is short enough that importing the routes dataset shows results almost at
#: once rather than after a restart. Saving an API key does not wait for it at
#: all: :meth:`EnrichmentService._reset_provider_state` clears the backoff,
#: because the callsigns in it are exactly the ones a new key can now answer.
UNANSWERABLE_BACKOFF_S: Final = 60


def build_provider(settings: Settings) -> RouteEnrichmentProvider | None:
    """The configured route provider, or ``None`` if there is not one.

    ``None`` is the whole of "enrichment is off": the flag unset, or no key.
    Deciding it here rather than inside the service is what makes the
    zero-external-calls guarantee structural — with no provider there is no
    object in the process that knows how to make the request.

    Called twice: once by :func:`flightsite.app.create_app` at boot, and once
    per configuration save by
    :func:`flightsite.api.internal._apply_enrichment`, which hands the result
    to :meth:`EnrichmentService.apply_provider` (issue #161). One function
    deciding both is the point — the running install and the next boot must not
    read the same configuration two different ways.

    Constructing a provider opens nothing: the HTTP client is built on the
    first request, so a provider that is built and then declined has cost a
    dataclass-sized allocation and no socket.
    """
    enrichment = settings.enrichment
    if not enrichment.aerodatabox_enabled or enrichment.aerodatabox_api_key is None:
        return None
    return AeroDataBoxProvider(api_key=enrichment.aerodatabox_api_key)


@dataclass(frozen=True, slots=True)
class EnrichmentEconomy:
    """How much the owner is willing to spend, and how long an answer lasts.

    The two numbers of ``enrichment.*`` that are not about *whether* to enrich
    but about *how much*. Kept as one value object so a save carries them
    together and :func:`_same_configuration` can compare a whole configuration
    rather than a provider and two loose integers.
    """

    #: Days a found route stays cached (``enrichment.route_ttl_days``).
    route_ttl_days: int = DEFAULT_ROUTE_TTL_DAYS
    #: Provider lookups allowed per UTC day; ``0`` is uncapped.
    daily_lookup_budget: int = 0

    @property
    def route_ttl_s(self) -> int:
        """The positive TTL in seconds, as the cache repository takes it."""
        return self.route_ttl_days * SECONDS_PER_DAY


def build_economy(settings: Settings) -> EnrichmentEconomy:
    """The spending plan the configuration describes.

    The sibling of :func:`build_provider`, and called in the same two places
    for the same reason: the running install and its next boot must not read
    one configuration two different ways.
    """
    enrichment = settings.enrichment
    return EnrichmentEconomy(
        route_ttl_days=enrichment.route_ttl_days,
        daily_lookup_budget=enrichment.daily_lookup_budget,
    )


def _same_provider(
    current: RouteEnrichmentProvider | None, candidate: RouteEnrichmentProvider | None
) -> bool:
    """True when ``candidate`` would make exactly the requests ``current`` does.

    Configuration, not identity. Every save calls :func:`build_provider`, which
    returns a fresh object, so identity would report a change on every save of
    every setting and restart the worker each time.

    Only :class:`~flightsite.enrichment.AeroDataBoxProvider` can answer the
    question in terms of configuration, and it is the only provider ADR-0006
    ships; anything else — a test double, a provider added later without a
    comparison — falls back to identity, which is the safe answer, because a
    provider wrongly judged *different* costs a restart while one wrongly
    judged *identical* would keep a superseded provider running.
    """
    if current is None or candidate is None:
        return current is None and candidate is None
    if isinstance(current, AeroDataBoxProvider) and isinstance(candidate, AeroDataBoxProvider):
        return current.configured_like(candidate)
    return current is candidate


def _same_configuration(
    current: RouteEnrichmentProvider | None,
    candidate: RouteEnrichmentProvider | None,
    current_economy: EnrichmentEconomy,
    candidate_economy: EnrichmentEconomy,
) -> bool:
    """True when applying this save would change nothing at all.

    The whole configuration, not just the provider: since slice 070 a save can
    change the TTL or the daily budget while leaving the key alone, and a
    comparison that ignored those would quietly discard the change the owner
    just made. What it must *not* do is conflate the two halves — a new budget
    is a number the running worker adopts in place, while a new key is a
    provider swap — so :meth:`EnrichmentService.apply_provider` asks
    :func:`_same_provider` separately before it decides to restart anything.
    """
    return _same_provider(current, candidate) and current_economy == candidate_economy


@dataclass(slots=True)
class _PendingLookup:
    """One queued callsign and the aircraft waiting on its answer.

    Several aircraft can share one key — a flight number flown by a substituted
    airframe, or the same flight seen twice either side of a closure gap — and
    every sighting that was waiting deserves the answer the single request
    bought.

    ``refresh`` marks a lookup whose answer this process already had and has
    since expired. It is the lowest priority precisely because it is the least
    urgent kind of miss: something correct is already on file, and the aircraft
    waiting on it is reading that.
    """

    callsign: str
    icaos: set[str] = field(default_factory=set)
    refresh: bool = False


@dataclass(frozen=True, slots=True)
class _Answer:
    """A route this process holds, and when it stops being worth holding.

    The in-memory gate needed no expiry while the cache key carried a UTC date:
    the key itself rotated at midnight and yesterday's answers were simply
    never asked for again. With a callsign-only key it does — without one, a
    long-running process would serve its first answer for a callsign forever
    and the TTL would apply to the table but not to the memory in front of it.
    """

    route: RouteInfo | None
    expires_ms: int


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """What the daily lookup budget has left. Read by diagnostics."""

    #: Lookups allowed today, or ``None`` when uncapped.
    limit: int | None
    #: Rows fetched so far in the current UTC day.
    used_today: int
    #: What is left, or ``None`` when uncapped. Never negative.
    remaining: int | None
    #: The next UTC midnight, when ``used_today`` returns to zero.
    resets_at_ms: int


@dataclass(frozen=True, slots=True)
class CacheStats:
    """How the cache is doing, as diagnostics reports it."""

    #: Lookups answered from the table or from memory since start.
    hits: int
    #: Lookups that had to reach the provider since start.
    misses: int
    #: Rows currently frozen as learned schedules.
    learned: int
    #: Expired rows served because nothing could refresh them (slice 071).
    #: An additive key on the ``enrichment.cache`` diagnostics block; a run of
    #: these is the signal that the provider has been unreachable, the budget
    #: is spent, or the breaker has been open for a while.
    stale_served: int = 0
    #: Lookups answered by the offline route directory (slice 071). Additive,
    #: and deliberately not folded into :attr:`hits`: both cost nothing, but
    #: this is the one that says the imported routes dataset is earning its
    #: place — and on a key-less install it is the only column that counts a
    #: *new* answer, :attr:`misses` never moving and :attr:`hits` recording
    #: only the repeat sightings of what the directory already supplied.
    directory_hits: int = 0


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
        directory: the offline route directory, consulted after the cache and
            before the provider (slice 071). ``None`` — the default, and what
            every test that predates the directory constructs — means the
            worker behaves exactly as it did before it existed.
        rate_per_minute: sustained provider request rate.
        failure_threshold: consecutive failures that open the circuit.
        cooldown_s: how long the circuit stays open.
        queue_size: bounded live-event subscription capacity.
        pending_limit: bounded pending-lookup queue capacity.
        economy: the TTL and the daily budget this install is configured with.
        alerting: "is this aircraft matching an alert rule right now?" — a
            closure over app state, injected rather than depended on, so the
            service needs no alert engine to run and tests need no alerts.
        airport_context: the airport-context service's latched answer for an
            aircraft, read the same way and used for the consistency check.
        display_radius_nm: the configured map radius, read per drain.
        clock: UTC epoch milliseconds, injected for tests.
        monotonic: monotonic seconds for the limiter and breaker, injected so
            their rules are proved in microseconds rather than minutes.
        counters: registry receiving ``enrichment_failures``.
    """

    __slots__ = (
        "_airport_context",
        "_alerting",
        "_answer_limit",
        "_answers",
        "_breaker",
        "_budget_announced",
        "_budget_day_ms",
        "_budget_used",
        "_cache",
        "_clock",
        "_counters",
        "_directory",
        "_directory_hits",
        "_directory_skip",
        "_dropped",
        "_economy",
        "_hits",
        "_idle",
        "_inflight",
        "_invalidated",
        "_invalidating",
        "_learned",
        "_limiter",
        "_live",
        "_lookups",
        "_misses",
        "_overflowed",
        "_pending",
        "_pending_limit",
        "_persistence",
        "_provider",
        "_queue_size",
        "_radius_nm",
        "_reader",
        "_stale_logged",
        "_stale_served",
        "_started",
        "_subscription",
        "_unanswered",
        "_worker",
    )

    def __init__(
        self,
        *,
        live: LiveStore,
        persistence: PersistenceWorker,
        cache: RouteCacheRepository,
        provider: RouteEnrichmentProvider | None,
        directory: RouteDirectoryRepository | None = None,
        economy: EnrichmentEconomy | None = None,
        alerting: AlertProbe | None = None,
        airport_context: ContextProbe | None = None,
        display_radius_nm: RadiusProbe | None = None,
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
        self._directory = directory
        self._provider = provider
        self._economy = economy if economy is not None else EnrichmentEconomy()
        self._alerting = alerting
        self._airport_context = airport_context
        self._radius_nm = display_radius_nm
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
        #: True between :meth:`start` and :meth:`stop` — the app's lifespan
        #: window, recorded even on a disabled install so that
        #: :meth:`apply_provider` can tell "enrichment is off in a running app"
        #: (start what is applied now) from "the app has not started yet"
        #: (install it and let the lifespan's own ``start`` pick it up).
        self._started = False
        self._reader: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        #: Queued keys, oldest first. An ordered mapping rather than a queue so
        #: two observations of one flight coalesce into a single lookup.
        self._pending: OrderedDict[str, _PendingLookup] = OrderedDict()
        #: Answers this process already holds, keyed as the cache is. A
        #: :class:`_Answer` whose ``route`` is ``None`` means "asked, and there
        #: is no route" — remembered as firmly as a route, because it is the
        #: answer that saves the most requests.
        self._answers: OrderedDict[str, _Answer] = OrderedDict()
        #: Keys whose cache row is to be deleted before the next request,
        #: because the aircraft contradicted it.
        self._invalidating: set[str] = set()
        #: Keys already invalidated once this process. Bounded like the answers
        #: and for the same reason; membership is what makes the consistency
        #: check fire once rather than on every observation.
        self._invalidated: OrderedDict[str, None] = OrderedDict()
        #: Callsigns whose directory row an aircraft has disproved, mapped to
        #: the instant the skip lapses. Bounded like the answers, for the same
        #: reason; an entry is what routes the re-ask to the provider rather
        #: than back to the file that was wrong.
        self._directory_skip: OrderedDict[str, int] = OrderedDict()
        self._inflight: str | None = None
        self._dropped = 0
        self._overflowed = False
        self._lookups = 0
        self._hits = 0
        self._misses = 0
        self._learned = 0
        self._stale_served = 0
        self._directory_hits = 0
        #: Callsigns whose stale serve has already been logged, mapped to the
        #: UTC day it was logged for. Bounded like the answers.
        self._stale_logged: OrderedDict[str, int] = OrderedDict()
        #: Callsigns nothing could answer, mapped to when the worker will try
        #: again. Not an answer and never cached — see :meth:`_unanswerable`.
        self._unanswered: OrderedDict[str, int] = OrderedDict()
        #: Start of the UTC day the budget count belongs to, or ``None`` before
        #: the first read of the table. Not "today": the day the *count* was
        #: taken for, which is what makes a midnight rollover detectable.
        self._budget_day_ms: int | None = None
        self._budget_used = 0
        self._budget_announced = False
        self._idle = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------ inspection

    @property
    def enabled(self) -> bool:
        """True when there is **any** source this worker could consult.

        Until slice 071 this meant "a provider is configured", because a
        provider was the only thing that could answer. The offline route
        directory is a second source and needs no key, so a stock install with
        the routes dataset imported enriches perfectly well without one — which
        is the whole point of SPEC §28's amendment making the directory the
        *primary* source.

        What did **not** change is the guarantee underneath: with no provider
        no request is ever made, because there is no object in the process that
        knows how to make one (:func:`build_provider` returned ``None``). "No
        provider, no external call" is still structural. What it stopped
        meaning is "no provider, no *work*" — the worker still runs, and still
        answers from the cache and the directory.

        :attr:`provider_name` is what tells a reader which of the two an
        install has; diagnostics publishes both.
        """
        return self._provider is not None or self._directory is not None

    @property
    def provider_name(self) -> str | None:
        """The online provider's name, or ``None`` on a key-less install.

        Published by diagnostics beside :attr:`enabled`, because those are now
        two different questions: whether route lookup is operating at all, and
        whether it can reach past the local directory.
        """
        return None if self._provider is None else self._provider.name

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

    @property
    def economy(self) -> EnrichmentEconomy:
        """The TTL and daily budget currently in force."""
        return self._economy

    @property
    def budget(self) -> BudgetStatus:
        """What the day's lookup budget has spent and has left.

        Read from memory: the count is taken from ``route_cache`` at start and
        at each midnight rollover and incremented as rows are written, so this
        is a property read rather than a query on the diagnostics path.
        """
        limit = self._economy.daily_lookup_budget
        used = self._budget_used
        return BudgetStatus(
            limit=limit or None,
            used_today=used,
            remaining=max(0, limit - used) if limit else None,
            resets_at_ms=self._next_midnight_ms(),
        )

    @property
    def cache_stats(self) -> CacheStats:
        """How each lookup was answered, for diagnostics.

        Three mutually exclusive outcomes, so the numbers say where the day's
        answers actually came from: ``hits`` is the route cache (in memory or
        in the table), ``directory_hits`` is the offline directory, and
        ``misses`` is what had to reach the provider. A directory hit is
        deliberately **not** folded into ``hits`` — both are free, but only one
        of them is evidence that importing the routes dataset is doing its job.
        """
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            learned=self._learned,
            stale_served=self._stale_served,
            directory_hits=self._directory_hits,
        )

    async def wait_idle(self) -> None:
        """Wait until the worker task finishes the lookup it is in.

        Tests wait on this rather than sleeping, which is what keeps the suite
        deterministic without a polling interval (``docs/TEST_STRATEGY.md`` §3).
        """
        await self._idle.wait()

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Subscribe and start consuming. Idempotent.

        Runs whenever there is *something* to consult — a provider, the offline
        directory, or both (:attr:`enabled`). Before slice 071 a key-less
        install started nothing at all, which was the right shape while a
        provider was the only source of routes and the wrong one the moment the
        directory became the primary source: it left an install that had
        imported 619,770 routes showing Unknown for every one of them.

        The acceptance criterion it used to encode — *"without key or offline:
        zero external calls, clean Unknowns"* — still holds, and still
        structurally: no provider means no object in this process knows how to
        make a request, and :meth:`_advance` never reaches one. What a key-less
        install now does is read its own two tables, which is not an external
        call by any reading.

        An install with neither a provider nor a directory subscribes to
        nothing and creates no task, exactly as before. It still records that
        the lifespan is open, so a provider applied later has somewhere to run.
        """
        self._started = True
        if self.running or not self.enabled:
            return
        # Before the first event, so an install restarted at noon knows what it
        # has already spent today rather than being handed a fresh allowance.
        await self._refresh_ledger()
        self._subscription = self._live.subscribe("enrichment", maxsize=self._queue_size)
        self._reader = asyncio.create_task(self._read_loop(), name="flightsite-enrichment-read")
        self._worker = asyncio.create_task(self._lookup_loop(), name="flightsite-enrichment")
        logger.info(
            "enrichment_started",
            provider=self.provider_name,
            directory=self._directory is not None,
        )

    async def stop(self) -> None:
        """Stop consuming, release the subscription and the client. Idempotent.

        Closes the lifespan window as well as the tasks, so a service stopped
        at shutdown stays stopped: a configuration applied after this point
        installs a provider and starts nothing.
        """
        self._started = False
        await self._halt()

    async def apply_provider(
        self,
        provider: RouteEnrichmentProvider | None,
        economy: EnrichmentEconomy | None = None,
    ) -> None:
        """Reconcile the running service with a just-saved configuration (#161).

        ``provider`` is whatever :func:`build_provider` made of the settings the
        save installed, ``economy`` what :func:`build_economy` made of the same
        settings, and this method makes the service match both. Before it
        existed the provider was read exactly once, in ``create_app``, so an
        owner who enabled enrichment and pasted a key into the Settings page
        got a saved file and nothing else until the backend was restarted —
        the same defect as issues #110, #122 and #129, in the fourth subsystem
        that had captured a setting at construction.

        Four cases, and the first is the common one
        -------------------------------------------

        * **Nothing changed.** Compared by configuration rather than by
          identity (:func:`_same_configuration`), because every save — of the
          map style, of a watchlist, of anything — arrives here with a freshly
          built provider object. An equivalent one returns immediately, so the
          worker keeps its tasks, its subscription, its remembered answers and
          its place in the queue. ``None`` matching ``None`` is the same
          no-op, and the one a disabled install takes on every save.
        * **Switched on.** The provider is installed in place. Since slice 071
          the worker is already running for the offline directory, so there is
          nothing to start: the next drain that gets past the directory finds
          a provider where the one before it found none.
        * **Switched off.** The provider is dropped and its client closed.
          What is left is a service holding ``None``, which is exactly what a
          stock install holds — the guarantee that no object in the process
          can make the request is restored, not merely asserted. The worker
          keeps running, because the directory is the primary source and
          removing an API key is not a request to stop enriching.
        * **Re-keyed.** Both of the above, in order: the new provider is
          installed and then the old one's client is closed, so a replaced
          provider never leaves a connection pool behind.

        A fifth case was added with the budget and the TTL (slice 070), and it
        is deliberately none of the above: **re-budgeted**. A save that changes
        only ``route_ttl_days`` or ``daily_lookup_budget`` adopts the new
        numbers in place — no teardown, no lost queue, no resubscription — and
        re-reads the day's ledger, so raising a spent budget resumes lookups on
        the save rather than at midnight. That is why the equality check that
        decides "nothing changed" is over the whole configuration while the one
        that decides "restart" is over the provider alone.

        Starting is conditional on the lifespan being open, not on the service
        having been running: a service with nothing at all to consult has no
        tasks to speak of, and a provider applied later is what first gives it
        a reason to run. A service that has not been started yet — an app still
        being built — takes the provider and waits, because its :meth:`start`
        is still to come and would otherwise start it twice.
        """
        current = self._provider
        candidate_economy = economy if economy is not None else self._economy
        if _same_configuration(current, provider, self._economy, candidate_economy):
            # Constructing a provider opens nothing, so the candidate this call
            # declines has nothing to leak; closing it anyway keeps that true
            # of a provider that one day acquires something in its constructor.
            if provider is not None and provider is not current:
                await provider.aclose()
            return

        if not _same_provider(current, provider):
            await self._swap_provider(provider, candidate_economy)
            return

        # Only the numbers changed. The worker keeps its tasks, its
        # subscription, its remembered answers and its place in the queue.
        await self._adopt_economy(candidate_economy)
        if provider is not None and provider is not current:
            await provider.aclose()

    async def _adopt_economy(self, economy: EnrichmentEconomy) -> None:
        """Take a new TTL and budget without disturbing anything running."""
        self._economy = economy
        # A budget that was spent may not be any more, and one that was
        # uncapped may now be spent already: re-read rather than reason about
        # which, so the next drain sees the truth either way.
        self._budget_day_ms = None
        if self._started:
            await self._refresh_ledger()
        logger.info(
            "enrichment_economy_applied",
            route_ttl_days=economy.route_ttl_days,
            daily_lookup_budget=economy.daily_lookup_budget,
            used_today=self._budget_used,
        )

    async def _swap_provider(
        self, provider: RouteEnrichmentProvider | None, economy: EnrichmentEconomy
    ) -> None:
        """Install a different provider **in place**, without a teardown.

        Until slice 071 this stopped the tasks, released the subscription and
        started again, because the provider *was* the service: with none there
        was nothing left to run. That is no longer true, and it made two of the
        cases wrong rather than merely wasteful.

        * Turning the provider **off** used to stop directory lookups too. It
          must not: the directory is the primary source, and removing an API
          key is not a request to stop enriching.
        * Turning it **on** used to cost a restart — a lost subscription, a
          lost queue, and a resubscribe — for a change no running task holds a
          reference to.

        Nothing in the loops captures the provider: :meth:`_request` reads
        ``self._provider`` at the moment it asks. So the swap is an assignment
        plus the two things that *are* the old provider's: its HTTP client,
        which is closed, and the provider-scoped state
        (:meth:`_reset_provider_state`). The tasks keep running throughout, and
        a service that was not running starts if it now has something to do.
        """
        current = self._provider
        # Installed *before* the old client is closed, and that order is
        # load-bearing now that the worker keeps running through the swap.
        # :meth:`_request` reads ``self._provider`` at the moment it asks, and
        # ``AeroDataBoxProvider`` builds its client lazily — so a drain that
        # started during the ``aclose`` below, while the attribute still named
        # the old provider, would have built that provider a *fresh* client and
        # sent the key the owner had just removed. Assigning first means such a
        # drain sees the new provider, or sees ``None`` and asks nobody.
        self._provider = provider
        self._economy = economy
        self._reset_provider_state()
        if current is not None:
            # The client belongs to the provider being replaced, whether or not
            # the tasks ever ran, and nothing references it any more: a
            # replaced provider never leaves a connection pool behind. A
            # request already in flight on it fails as a transport error, which
            # is the one thing a swap without a teardown cannot avoid and the
            # one the provider already models.
            await current.aclose()

        if not self.enabled:
            # Nothing left to consult at all — no provider *and* no directory,
            # which is the shape a test double takes and the shape an install
            # would take if the directory were ever unwired. Then the tasks do
            # have to stop, because there is genuinely no work.
            if self.running:
                await self._halt()
        elif self._started and not self.running:
            await self.start()
        logger.info(
            "enrichment_reconfigured",
            provider=self.provider_name,
            enabled=self.enabled,
            running=self.running,
        )

    def _reset_provider_state(self) -> None:
        """Forget what belonged to the provider that has just been replaced.

        The circuit breaker above all: a run of failures earned by a rejected
        key is not evidence about the key that replaced it, and an install that
        re-keyed *because* the old key was refused would otherwise spend its
        first cooldown refusing every lookup.

        The queued lookups go with it, and their counters. Dropping them is the
        policy an open circuit already applies — the next observation of the
        flight queues it again, which is a retry paced by the sky rather than
        by a loop. Since slice 071 this runs while the worker's tasks keep
        going, so the clear happens between drains rather than instead of them;
        that is safe because :meth:`drain_once` reads the queue and selects
        from it without an ``await`` in between.

        The **unanswerable** backoff goes too, and that one is load-bearing: it
        records callsigns nothing could answer, which is exactly the set a
        newly saved key *can* now answer. Keeping it would make an install that
        pasted a key wait out the backoff before its first lookup.

        Five things deliberately survive. Remembered answers are facts about
        flights, not about the provider that reported them — ``route_cache``
        keeps them across a restart already, and re-asking would spend quota to
        learn what FlightSite knows; the cache counters describe those same
        facts. The day's budget ledger is a count of rows in a table, which a
        new key does not refund. And the rate limiter describes the plan rather
        than the object: refilling its bucket here would make saving the
        Settings page a way to buy requests per minute. The fifth is the
        directory skip list, which describes a *file* an aircraft disproved and
        which a new API key does not make right.
        """
        self._breaker.reset()
        self._pending.clear()
        self._invalidating.clear()
        self._unanswered.clear()
        self._overflowed = False
        self._dropped = 0
        self._lookups = 0

    async def _halt(self) -> None:
        """Cancel the tasks, release the subscription, close the provider.

        The teardown :meth:`stop` and :meth:`apply_provider` share. It is
        idempotent, and it says nothing about whether the service may run
        again — that is :attr:`_started`, which only :meth:`stop` clears.
        """
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

        An install with nothing to consult — no provider *and* no directory —
        considers nothing at all. :meth:`start` already subscribes to no events
        in that case, so this guard is belt as well as braces; what it is no
        longer allowed to key on is the provider alone, because a key-less
        install with an imported directory has plenty to do.

        Public because it is the whole of the read side's decision, and tests
        drive it directly rather than through a task.
        """
        if not self.enabled:
            return
        if isinstance(event, AircraftAppeared | AircraftUpdated):
            self._enqueue(event.aircraft)

    def _enqueue(self, record: LiveAircraft) -> None:
        callsign = eligible_callsign(record.callsign)
        if callsign is None:
            return
        key = cache_key(callsign)
        if self._backing_off(key):
            # Nothing could answer this callsign a moment ago and nothing has
            # changed since. Queueing it again would buy the same two table
            # reads per observation, forever.
            return

        held = self._answers.get(key)
        if held is not None and held.expires_ms <= self._clock():
            # The memory gate has the same expiry the row it came from has.
            # What follows is a refresh, and it is the lowest priority there is.
            del self._answers[key]
            held = None
            refresh = True
        else:
            refresh = False

        if held is not None:
            if self._contradicted(key, (record.icao,), held.route):
                self._invalidate_later(key, callsign, record.icao, held.route)
                return
            # Already answered this process. Applying is idempotent, so this
            # also covers the second aircraft to fly the number and the
            # sighting that reopened after a gap.
            self._answers.move_to_end(key)
            self._hits += 1
            self._apply(key, held.route, (record.icao,))
            return
        if key == self._inflight:
            # A lookup for this key is in the provider right now; ride it.
            self._pending.setdefault(key, _PendingLookup(callsign)).icaos.add(record.icao)
            return

        existing = self._pending.get(key)
        if existing is not None:
            existing.icaos.add(record.icao)
            return
        self._pending[key] = _PendingLookup(callsign, {record.icao}, refresh=refresh)
        self._shed_if_full()

    def _invalidate_later(
        self, key: str, callsign: str, icao: str, route: RouteInfo | None
    ) -> None:
        """Queue a re-fetch of a route the aircraft has just disproved.

        The row is deleted on the worker's task rather than here, for the
        reason the whole read side exists: this runs on the reader, which must
        never await a database write while live events queue behind it. The
        directory skip *is* set here, because it is an in-memory dictionary
        write and setting it late would let the drain that follows read the
        same disproved row straight back out of the directory.
        """
        self._invalidating.add(key)
        self._remember_invalidation(key)
        self._skip_directory(key, self._clock(), source=None if route is None else route.source)
        self._answers.pop(key, None)
        pending = self._pending.setdefault(key, _PendingLookup(callsign, refresh=True))
        pending.icaos.add(icao)
        self._shed_if_full()
        logger.info("enrichment_route_invalidated", callsign=callsign, icao=icao)

    def _contradicted(self, key: str, icaos: tuple[str, ...], route: RouteInfo | None) -> bool:
        """True when an aircraft's latched airport phase disproves ``route``.

        Once per callsign per process: a key already invalidated is never
        invalidated again, so a route the provider keeps reporting the same way
        cannot become a request per observation. ``None`` — the provider has no
        route — can be contradicted by nothing, because it claims nothing.
        """
        probe = self._airport_context
        if route is None or probe is None or key in self._invalidated:
            return False
        return any(
            contradicts_route(
                probe(icao),
                origin_ident=route.origin_ident,
                destination_ident=route.destination_ident,
            )
            for icao in icaos
        )

    def _backing_off(self, key: str) -> bool:
        """Whether ``key`` is inside its unanswerable backoff window."""
        until = self._unanswered.get(key)
        if until is None:
            return False
        if until <= self._clock():
            del self._unanswered[key]
            return False
        return True

    def _unanswerable(self, key: str, now_ms: int) -> None:
        """Record that nothing could answer ``key``, and leave it alone a while.

        Deliberately in memory and nowhere else. This is not a fact about the
        flight — a route may well exist and simply be unknown to this install —
        so it must not reach ``route_cache``, where a reader could not tell it
        from "the provider answered and has none". See
        :data:`UNANSWERABLE_BACKOFF_S` for what the window buys.
        """
        self._unanswered[key] = now_ms + UNANSWERABLE_BACKOFF_S * MS_PER_SECOND
        self._unanswered.move_to_end(key)
        while len(self._unanswered) > self._answer_limit:
            self._unanswered.popitem(last=False)

    def _remember_invalidation(self, key: str) -> None:
        self._invalidated[key] = None
        self._invalidated.move_to_end(key)
        while len(self._invalidated) > self._answer_limit:
            self._invalidated.popitem(last=False)

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
        """Advance the most deserving queued lookup one step.

        ``True`` if it did anything. The whole of the lookup side's decision,
        in the order the gates are cheapest: an answer already held, then the
        cache table, then the budget, then the circuit, then the limiter, then
        a request. Public so tests step it one call at a time instead of racing
        a background task.
        """
        if not self._pending:
            return False
        key, lookup = self._select()

        self._idle.clear()
        self._inflight = key
        try:
            return await self._advance(key, lookup)
        finally:
            self._inflight = None
            self._idle.set()

    def _select(self) -> tuple[str, _PendingLookup]:
        """The queued lookup the day's next request should buy.

        ``min`` returns the *first* minimal element, and ``_pending`` is
        insertion-ordered, so within one priority the queue is still FIFO —
        priority reorders tiers, it does not shuffle a tier. The scan is over a
        queue bounded at a few hundred entries and runs once per drain, which
        is cheaper than maintaining four queues that all have to be kept
        consistent with one another.
        """
        return min(self._pending.items(), key=lambda item: self._priority(item[1]))

    def _priority(self, lookup: _PendingLookup) -> int:
        """Which tier a pending lookup belongs to; lower goes first.

        See the module docstring for the tiers. Computed at selection time
        rather than stored at enqueue time because every input to it changes
        while the entry waits: an aircraft starts matching a rule, flies inside
        the display radius, or leaves.
        """
        alerting = self._alerting
        if alerting is not None and any(alerting(icao) for icao in lookup.icaos):
            return 0
        if self._within_display_radius(lookup.icaos):
            return 1
        return 3 if lookup.refresh else 2

    def _within_display_radius(self, icaos: set[str]) -> bool:
        """True when any waiting aircraft is inside the configured radius.

        An aircraft with no computed distance — no position yet, or no receiver
        location configured — is not *outside* the radius, it is unmeasured,
        and unmeasured is not a reason to promote it above the sky the map is
        actually showing.
        """
        probe = self._radius_nm
        radius_nm = probe() if probe is not None else None
        if radius_nm is None:
            return False
        for icao in icaos:
            record = self._live.get(icao)
            if (
                record is not None
                and record.distance_nm is not None
                and (record.distance_nm <= radius_nm)
            ):
                return True
        return False

    async def _advance(self, key: str, lookup: _PendingLookup) -> bool:
        # A queued key is never one this process has already answered:
        # `_enqueue` applies a remembered answer instead of queueing, and
        # `_finish` — the only writer of `_answers` — takes the key off the
        # queue in the same call. So the memory gate is upstream of here and
        # this method starts at the cache.
        now_ms = self._clock()
        if key in self._invalidating:
            # An aircraft disproved this row on the reader's task; deleting it
            # is this task's work, and it happens before the read below so the
            # request that follows cannot be answered by what was disproved.
            self._invalidating.discard(key)
            await self._cache.invalidate(key)

        # The cache before the limits: a hit spends no request, and a route
        # already on disk is worth applying even while the circuit is open —
        # ``docs/ARCHITECTURE.md`` §"Degradation" keeps cached enrichment
        # working through an outage.
        cached = await self._cache.get(key, now_ms=now_ms)
        if cached is not None:
            answer = cached.as_lookup()
            route = answer if isinstance(answer, RouteInfo) else None
            if self._contradicted(key, tuple(lookup.icaos), route):
                # The restart case: the row outlived the process that fetched
                # it, so the contradiction is met here rather than at the
                # memory gate. Same remedy, one step later — plus the skip, in
                # case the row that was disproved is one the directory wrote.
                self._remember_invalidation(key)
                await self._cache.invalidate(key)
                self._skip_directory(key, now_ms, source=cached.source)
                logger.info("enrichment_route_invalidated", callsign=lookup.callsign)
            else:
                self._hits += 1
                self._finish(key, route, expires_ms=cached.expires_ms)
                return True

        # The directory before the budget, because it costs no credit: SPEC
        # §28 as amended makes it the primary source, and a callsign it knows
        # never reaches the provider at all.
        if await self._answer_from_directory(key, lookup, now_ms):
            return True

        if self._provider is None:
            # A key-less install, and the directory does not know this flight.
            # Nothing in this process can ask anybody — which is the guarantee,
            # not a failure. The last known route is still worth serving; past
            # that the key is dropped and left alone for a while, because
            # re-walking two tables for it on every observation would cost the
            # smallest install the most.
            if not await self._serve_stale(key, lookup, now_ms, reason="no_provider"):
                self._pending.pop(key, None)
                self._unanswerable(key, now_ms)
            return True

        if not await self._may_spend(now_ms):
            # The budget is spent. The key keeps its place, as it does under
            # the rate limiter: what stops is asking, not queueing — unless
            # there is a last known route to fall back on, in which case the
            # sighting gets it and the key is done for the day.
            return await self._serve_stale(key, lookup, now_ms, reason="budget_spent")

        if not self._breaker.allow():
            # Silently absent while the circuit is open, and dropped rather
            # than requeued: the next observation of this flight queues it
            # again, which is a retry paced by the sky instead of by a loop.
            await self._serve_stale(key, lookup, now_ms, reason="circuit_open")
            self._pending.pop(key, None)
            return True
        if not self._limiter.take():
            # The key keeps its place. A limiter is a delay, not a refusal —
            # and deliberately not a reason to serve a stale route: the answer
            # is seconds away, not unavailable.
            return False

        await self._request(key, lookup)
        return True

    async def _answer_from_directory(self, key: str, lookup: _PendingLookup, now_ms: int) -> bool:
        """Answer from the offline directory if it knows this callsign.

        ``True`` when it did. One indexed primary-key read on this task, never
        on the reader's and never on the live path; a hit is written into
        ``route_cache`` tagged ``vrs`` so the *next* observation of the flight
        is answered by the gate above without touching this table at all.

        The contradiction check runs here for the same reason it runs against a
        cached row — the aircraft can disprove a claim faster than any import
        can correct it — but the remedy is different, and it is the whole
        reason this branch exists: the directory is a file, so re-reading it
        would return the same wrong answer forever. So the callsign is skipped
        for the cache TTL and the walk falls through to the provider, which is
        the only source that can know better.
        """
        directory = self._directory
        if directory is None or self._directory_skipped(key, now_ms):
            return False
        found = await directory.lookup(key)
        if found is None:
            return False

        route = found.route_info()
        if self._contradicted(key, tuple(lookup.icaos), route):
            self._remember_invalidation(key)
            self._skip_directory(key, now_ms, source=ROUTE_SOURCE_VRS)
            logger.info(
                DIRECTORY_CONTRADICTED_EVENT,
                callsign=lookup.callsign,
                origin=route.origin_ident,
                destination=route.destination_ident,
            )
            return False

        self._directory_hits += 1
        write = await self._cache.store_route(
            key, route, now_ms=now_ms, ttl_s=self._economy.route_ttl_s
        )
        self._finish(key, route, expires_ms=now_ms + self._stored_ttl_s(write) * MS_PER_SECOND)
        return True

    def _skip_directory(self, key: str, now_ms: int, *, source: str | None) -> None:
        """Stop consulting the directory about ``key`` for the cache TTL.

        A no-op unless the answer being invalidated actually came from the
        directory: a contradicted *provider* route says nothing about what the
        directory holds, and skipping it would send the next lookup to the paid
        source for no reason.
        """
        if source != ROUTE_SOURCE_VRS:
            return
        self._directory_skip[key] = now_ms + self._economy.route_ttl_s * MS_PER_SECOND
        self._directory_skip.move_to_end(key)
        while len(self._directory_skip) > self._answer_limit:
            self._directory_skip.popitem(last=False)

    def _directory_skipped(self, key: str, now_ms: int) -> bool:
        """Whether the directory is currently being skipped for ``key``."""
        until = self._directory_skip.get(key)
        if until is None:
            return False
        if until <= now_ms:
            del self._directory_skip[key]
            return False
        return True

    async def _serve_stale(
        self, key: str, lookup: _PendingLookup, now_ms: int, *, reason: str
    ) -> bool:
        """Serve the last known route when nothing can refresh it.

        ``True`` when there was one. The expired row's expiry is pushed a day
        out inside the read's own transaction, so an outage costs one serve per
        callsign per day rather than one per observation, and the answer is
        applied to every waiting sighting with the provenance of whichever
        source originally reported it — never re-attributed, never invented.

        ``False`` means there is nothing to fall back on: the callsign has
        never been answered, or the expired row says "nobody knows", which is
        not a route to keep.
        """
        stale = await self._cache.serve_stale(key, now_ms=now_ms)
        if stale is None:
            return False
        answer = stale.as_lookup()
        if not isinstance(answer, RouteInfo):  # pragma: no cover - has_route decides this
            return False

        self._stale_served += 1
        self._log_stale(key, lookup.callsign, reason=reason, now_ms=now_ms)
        self._finish(key, answer, expires_ms=now_ms + STALE_EXTENSION_S * MS_PER_SECOND)
        return True

    def _log_stale(self, key: str, callsign: str, *, reason: str, now_ms: int) -> None:
        """Announce a stale serve once per callsign per UTC day."""
        day_ms = utc_day_start_ms(now_ms)
        if self._stale_logged.get(key) == day_ms:
            return
        self._stale_logged[key] = day_ms
        self._stale_logged.move_to_end(key)
        while len(self._stale_logged) > self._answer_limit:
            self._stale_logged.popitem(last=False)
        logger.warning(
            STALE_SERVED_EVENT,
            callsign=callsign,
            reason=reason,
            extended_s=STALE_EXTENSION_S,
        )

    async def _request(self, key: str, lookup: _PendingLookup) -> None:
        """Ask the provider, then record and apply whatever it said."""
        provider = self._provider
        if provider is None:  # pragma: no cover - the loop only runs when enabled
            return
        self._lookups += 1
        self._misses += 1
        result = await provider.lookup(lookup.callsign)
        now_ms = self._clock()

        if isinstance(result, RouteUnavailable):
            self._breaker.record_failure()
            self._counters.increment(ENRICHMENT_FAILURES_COUNTER)
            # Deliberately neither cached nor remembered: an unavailability is
            # a fact about the network, not about the flight. What *is* on file
            # about the flight — an expired answer from an earlier day — is
            # served instead of thrown away, and `_serve_stale` takes the key
            # off the queue when it finds one. Failing that the key is dropped,
            # so the sky rather than a retry loop decides when to ask again.
            if not await self._serve_stale(key, lookup, now_ms, reason=result.reason):
                self._pending.pop(key, None)
            return

        # Everything below is the provider *answering*, so the breaker closes
        # on all three — including 451. Issue #165 is what happens when a
        # definitive answer about one flight is read as a failing provider.
        self._breaker.record_success()
        await self._spend(now_ms)
        ttl_s = self._economy.route_ttl_s
        # A provider does not name itself in its own reply, so the row is
        # stamped here — the one place that knows which provider was asked.
        # Without it a cached provider answer would come back un-attributed
        # after a restart, and the directory-skip rule could not tell a
        # contradicted `vrs` row from a contradicted `aerodatabox` one.
        source = provider.name
        if isinstance(result, RouteInfo):
            write = await self._cache.store_route(
                key, result, now_ms=now_ms, ttl_s=ttl_s, source=source
            )
            if write.newly_learned:
                self._learned += 1
                logger.info(
                    "enrichment_route_learned",
                    callsign=lookup.callsign,
                    confirmations=write.confirmations,
                )
            self._finish(
                key,
                result,
                expires_ms=now_ms + self._stored_ttl_s(write) * MS_PER_SECOND,
            )
        elif isinstance(result, RouteRestricted):
            # Cached like an answer, because it is one, and for the positive
            # TTL: a flight withheld by law is withheld on the next sighting.
            await self._cache.store_restricted(key, now_ms=now_ms, ttl_s=ttl_s, source=source)
            self._finish(key, None, expires_ms=now_ms + ttl_s * MS_PER_SECOND)
        else:
            await self._cache.store_not_found(key, now_ms=now_ms, source=source)
            self._finish(key, None, expires_ms=now_ms + NEGATIVE_TTL_S * MS_PER_SECOND)

    def _stored_ttl_s(self, write: RouteWrite) -> int:
        """How long the row just written will live."""
        return LEARNED_TTL_S if write.learned else self._economy.route_ttl_s

    def _finish(self, key: str, answer: RouteInfo | None, *, expires_ms: int) -> None:
        """Remember an answer, apply it, and take the key off the queue."""
        self._remember(key, answer, expires_ms=expires_ms)
        lookup = self._pending.pop(key, None)
        if lookup is not None:
            self._apply(key, answer, tuple(sorted(lookup.icaos)))

    def _apply(self, key: str, answer: RouteInfo | None, icaos: tuple[str, ...]) -> None:
        """Attach a found route to every sighting that was waiting for it.

        ``answer is None`` — nobody has a route — writes nothing: the sighting
        keeps its ``NULL`` route columns, which is the honest record and what
        the API renders as Unknown. There is no branch here in which a route
        FlightSite was not told about could be written.

        The provenance is the answer's own ``source`` where it has one — the
        directory names itself, and so does a row read back out of the cache —
        falling back to the provider that was asked, which is the only thing
        that knows its own name. It reaches ``sightings.route_source`` and from
        there the API's ``provenance.route`` (``docs/API.md`` §2.6), so the two
        sources are told apart everywhere a route is shown.
        """
        provider = self._provider
        if answer is None:
            return
        source = answer.source or (provider.name if provider is not None else None)
        if source is None:  # pragma: no cover - the loop only runs when enabled
            return
        route = SightingRoute(
            origin_ident=answer.origin_ident,
            destination_ident=answer.destination_ident,
            source=source,
        )
        at_ms = self._clock()
        for icao in icaos:
            self._persistence.apply_route(icao, route, at_ms=at_ms)
        logger.debug("enrichment_applied", cache_key=key, aircraft=len(icaos))

    def _remember(self, key: str, answer: RouteInfo | None, *, expires_ms: int) -> None:
        self._answers[key] = _Answer(route=answer, expires_ms=expires_ms)
        self._answers.move_to_end(key)
        while len(self._answers) > self._answer_limit:
            self._answers.popitem(last=False)

    # ----------------------------------------------------------- the budget

    async def _may_spend(self, now_ms: int) -> bool:
        """Whether a lookup may be bought right now (issue #167).

        Uncapped installs — the default, and every install before this setting
        existed — take the first branch and never touch the table.
        """
        limit = self._economy.daily_lookup_budget
        if limit <= 0:
            return True
        if self._budget_day_ms != utc_day_start_ms(now_ms):
            # Either the first drain of this process or the first after
            # midnight. Both want the same thing: what the table says.
            await self._refresh_ledger(now_ms)
        if self._budget_used < limit:
            return True
        if not self._budget_announced:
            self._budget_announced = True
            logger.warning(
                BUDGET_EXHAUSTED_EVENT,
                limit=limit,
                used_today=self._budget_used,
                pending=len(self._pending),
                resets_at_ms=self._next_midnight_ms(now_ms),
            )
        return False

    async def _spend(self, now_ms: int) -> None:
        """Count a lookup that is about to write a row.

        Only answers are counted, because the ledger this mirrors is
        ``COUNT(*)`` over rows fetched today — and an unavailable provider
        writes no row. That is the honest join between the in-memory count and
        the one a restart re-reads, and it errs the right way: a failed request
        that bought nothing does not consume the day's allowance.

        The re-read is the midnight rollover an uncapped install would
        otherwise never take: a capped one has already refreshed in
        :meth:`_may_spend`, so this costs a query once a day at most.
        """
        if self._budget_day_ms != utc_day_start_ms(now_ms):
            await self._refresh_ledger(now_ms)
        self._budget_used += 1

    async def _refresh_ledger(self, now_ms: int | None = None) -> None:
        """Re-read the day's spend and the learned-row count from the table."""
        moment = now_ms if now_ms is not None else self._clock()
        day_ms = utc_day_start_ms(moment)
        self._budget_used = await self._cache.count_fetched_since(day_ms)
        self._learned = await self._cache.count_learned()
        self._budget_day_ms = day_ms
        self._budget_announced = False

    def _next_midnight_ms(self, now_ms: int | None = None) -> int:
        """The next 00:00 UTC, when the day's allowance returns."""
        moment = now_ms if now_ms is not None else self._clock()
        return utc_day_start_ms(moment) + SECONDS_PER_DAY * MS_PER_SECOND


__all__ = [
    "BUDGET_EXHAUSTED_EVENT",
    "DEFAULT_ANSWER_LIMIT",
    "DEFAULT_PENDING_LIMIT",
    "DEFAULT_QUEUE_SIZE",
    "DIRECTORY_CONTRADICTED_EVENT",
    "ENRICHMENT_FAILURES_COUNTER",
    "IDLE_POLL_S",
    "STALE_SERVED_EVENT",
    "UNANSWERABLE_BACKOFF_S",
    "AlertProbe",
    "BudgetStatus",
    "CacheStats",
    "ContextProbe",
    "EnrichmentEconomy",
    "EnrichmentService",
    "EpochClock",
    "RadiusProbe",
    "build_economy",
    "build_provider",
]
