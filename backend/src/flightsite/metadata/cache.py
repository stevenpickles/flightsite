"""The metadata & rarity cache (``docs/ARCHITECTURE.md`` §3.3).

The live path is memory-only. ``docs/ARCHITECTURE.md`` §3.1 states it as *"no
live request or decoder poll ever waits on SQLite"*, and §3.1 names this cache
as what preserves that invariant once live payloads carry metadata: *"metadata
joins and rarity checks hit a cache, not the database."*

How the invariant is kept — structurally, not by discipline
-----------------------------------------------------------

:meth:`LiveStore.apply <flightsite.live.store.LiveStore.apply>` never calls
into this module. The cache is a *consumer* of the live event stream, exactly
like the persistence worker: it holds a bounded subscription and does its work
on its own task. So the coupling runs one way only — the live store publishes
and moves on; the cache reads the database on its own time. There is no code
path from a decoder batch to a session, which is why the instrumentation test
can assert zero read sessions across a full batch application rather than
merely observing that none happened to open.

What it holds, and why that is bounded
--------------------------------------

* **Resolved metadata per live aircraft**, loaded when the aircraft appears and
  dropped when it leaves the live set. Bounded by the live set (§3.3: ≤ ~1,000
  aircraft), not by the size of the metadata database.
* **Its classification** (SPEC §39), computed by
  :func:`flightsite.classification.engine.classify` as the entry is built and
  recomputed in memory when the aircraft's callsign changes — the one
  classification input that moves during a flight. So the API serializer reads
  a classification rather than deriving one, and the hot path stays a dict
  lookup. The equivalent rows are also written to ``aircraft_classification``
  at import time for the SQL the Aircraft page will need; the engine is the
  same function, so the two cannot disagree.
* **A rarity counter per live aircraft** — ``aircraft.sighting_count``, the
  lifetime figure of ``docs/DATA_MODEL.md`` §2.2 — loaded in the same batch.
* **The full type-count map**, a few thousand entries, refreshed with the rest
  on import completion. Small enough to hold whole, and holding it whole is
  what makes "how rare is this type?" a dict lookup.

Population is *batched*, and the batching is free. ``LiveStore.apply`` runs a
whole decoder poll synchronously without awaiting, so by the time this task is
scheduled the poll's appear events are already sitting in its queue together;
draining them resolves the lot with one pair of queries instead of one pair
each. No artificial delay is introduced to achieve that — a linger would trade
the very latency the acceptance criterion measures for batching the topology
already provides.

The remaining cost is a sub-poll-interval delay before a newly appeared
aircraft has metadata, which is correct: metadata is enrichment, and a live
aircraft is fully usable without it (``docs/API.md`` §2.7 — the field is
``null`` until it is not).

Observing resolved views
-------------------------

An optional ``on_resolved`` callback (:data:`OnResolvedFn`) fires whenever one
cached entry's resolved view changes: installed with a fresh resolution,
reclassified after a callsign change, or evicted (``view`` is ``None``) when
its aircraft leaves the live set. It is the seam roadmap slice 037's watchlist
matcher hooks into to keep an in-memory match index current — matching by
registration, type or operator needs the *resolved* metadata this cache
computes, which arrives asynchronously after an aircraft's appear event, so a
consumer that only watched the live event stream would have no signal for
"metadata just resolved". Piggy-backing on this cache's own population
pipeline, which already visits every live aircraft exactly when its resolved
view is known, answers that with no second subscription and no extra
database read: the callback receives the same :class:`AircraftMetadataView`
this module just built, entirely in memory.

The callback is deliberately generic (an ``icao24``/view pair, nothing
watchlist-specific) so this module stays ignorant of what a watchlist even
is — the dependency runs one way, the same shape as
:mod:`flightsite.metadata.service`'s post-import ``ImportListener``\\ s. A
callback that raises is caught and logged: an observer's bookkeeping breaking
must not turn a successful metadata resolution into a cache failure.

Invalidation
------------

A completed metadata import can change any resolved row, so the cache drops
everything and repopulates from the current live set
(:meth:`MetadataCache.invalidate`). Repopulating the *live set* rather than
lazily per aircraft matters: the live set is what the WebSocket is about to
send, and a lazy refill would show every live aircraft as unknown for one poll.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

import structlog

from flightsite.classification.engine import classify
from flightsite.classification.model import Classification, Evidence
from flightsite.db import Database
from flightsite.live.events import (
    AircraftAppeared,
    AircraftRemoved,
    AircraftUpdated,
    EventSubscription,
    LiveEvent,
)
from flightsite.live.store import LiveStore
from flightsite.metadata.precedence import ResolvedMetadata
from flightsite.metadata.repository import AircraftLookup, MetadataRepository

logger = structlog.get_logger(__name__)

#: Events buffered for the cache before the live store sheds the oldest. The
#: cache's recovery from a shed event is trivially cheap — it resyncs against
#: the live snapshot, which is the set it wants to hold anyway — so it needs
#: nothing like the persistence worker's headroom.
DEFAULT_QUEUE_SIZE: Final = 2048

#: Most addresses resolved in one round of queries. Comfortably above the
#: ~1,000-aircraft live set in two rounds, and below SQLite's bound-parameter
#: limit once the repository chunks its ``IN`` clauses.
MAX_BATCH: Final = 512

#: A cache observer: called with an aircraft's address and its freshly
#: resolved view, or ``None`` when the aircraft left the live set. See the
#: module docstring's "Observing resolved views" section.
OnResolvedFn = Callable[[str, "AircraftMetadataView | None"], None]


@dataclass(frozen=True, slots=True)
class AircraftMetadataView:
    """What the cache knows about one live aircraft.

    Present in the cache means *resolved*, not *known*: an aircraft no metadata
    source has heard of gets a view with every field ``None`` and an empty
    provenance map. That distinction is deliberate — "we looked and nobody
    knows" and "we have not looked yet" are different answers, and only the
    second one is worth retrying.
    """

    icao24: str
    metadata: ResolvedMetadata | None = None
    #: Persisted lifetime sighting count (``aircraft.sighting_count``), or
    #: ``None`` for an airframe with no persisted row yet. It is the count as
    #: of population: the write-behind worker persists the current sighting
    #: within a cycle or so of the appear event that populated this entry, so
    #: the figure can trail the current sighting by one.
    sighting_count: int | None = None
    #: Unique airframes ever recorded of this aircraft's resolved type.
    type_count: int | None = None
    #: Display name of the curated operator group (SPEC §38), or ``None`` when
    #: the exact operator matched no group. The exact operator is on
    #: :attr:`metadata` either way — grouping is additive, never a replacement.
    operator_group: str | None = None
    #: The classification engine's inputs for this airframe, retained so a
    #: later callsign can be folded in without another database read.
    evidence: Evidence = field(default_factory=lambda: Evidence(icao24=""))
    #: SPEC §39's answer for this airframe. Never ``None``: an airframe nobody
    #: knows anything about has a complete classification whose every claim is
    #: absent (:attr:`Classification.is_unknown`), which is a different and more
    #: useful statement than a missing object.
    classification: Classification = field(default_factory=Classification)

    @property
    def type_code(self) -> str | None:
        """The resolved ICAO type designator, if any source supplied one."""
        return None if self.metadata is None else self.metadata.type_code

    @property
    def known(self) -> bool:
        """True when at least one metadata field resolved for this airframe."""
        return self.metadata is not None

    def provenance(self) -> dict[str, str]:
        """Per-field provenance in the ``docs/API.md`` §2.6 shape.

        Includes ``classification`` and ``operator_group`` where they have a
        value: both are FlightSite's own statements rather than an upstream
        database's, and §2.6 exists so a reader can tell which is which.
        """
        found = {} if self.metadata is None else self.metadata.provenance()
        source = self.classification.source
        if source is not None:
            found["classification"] = source.value
        if self.operator_group is not None:
            found["operator_group"] = "derived"
        return found


class MetadataCache:
    """In-memory metadata and rarity lookups for the live aircraft set.

    Args:
        database: the application database, read off the hot path.
        live: the live store whose event stream drives population.
        queue_size: bounded subscription capacity.
        on_resolved: optional observer notified whenever a cached entry is
            installed, reclassified or evicted — see the module docstring's
            "Observing resolved views" section.
    """

    __slots__ = (
        "_entries",
        "_idle",
        "_live",
        "_lock",
        "_on_resolved",
        "_populations",
        "_queue_size",
        "_repository",
        "_subscription",
        "_task",
        "_type_counts",
    )

    def __init__(
        self,
        *,
        database: Database,
        live: LiveStore,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        on_resolved: OnResolvedFn | None = None,
    ) -> None:
        self._repository = MetadataRepository(database)
        self._live = live
        self._queue_size = queue_size
        self._on_resolved = on_resolved

        self._entries: dict[str, AircraftMetadataView] = {}
        self._type_counts: dict[str, int] = {}
        self._subscription: EventSubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._populations = 0
        # Serializes the population task against an import's invalidation.
        # Both mutate the entry map across an await and they run on
        # different tasks: without this, a population that had already read
        # the pre-import rows could install them after invalidation cleared
        # the map, leaving one aircraft describing the previous dataset
        # until it next appeared. Uncontended in the normal case.
        self._lock = asyncio.Lock()
        # Set while the population task has nothing left to do. Tests await it
        # instead of sleeping, and it is what makes the latency measurement a
        # measurement of the cache rather than of a poll loop.
        self._idle = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------- inspection

    @property
    def running(self) -> bool:
        """True while the population task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def size(self) -> int:
        """Cached aircraft. Bounded by the live set."""
        return len(self._entries)

    @property
    def type_count_size(self) -> int:
        """Entries in the resident type-count map."""
        return len(self._type_counts)

    @property
    def populations(self) -> int:
        """Batched population rounds run since start. Instrumentation."""
        return self._populations

    # ---------------------------------------------------------------- lookups

    def get(self, icao: str) -> AircraftMetadataView | None:
        """Resolved metadata and rarity for ``icao``, or ``None``.

        Pure memory: no ``await``, no session, no I/O. ``None`` means *not
        resolved yet* — the aircraft is not live, or its appear event is still
        in flight — and a caller renders that the same way it renders unknown
        (``docs/API.md`` §2.7), it just may become known a moment later.

        This is the lookup slice 024's classification and the aircraft APIs
        read; it is deliberately the only public read path, so nothing can
        accidentally reach the database for a live-path answer.
        """
        return self._entries.get(icao)

    def sighting_count(self, icao: str) -> int | None:
        """Lifetime sighting count for a live aircraft (SPEC §44 rarity)."""
        entry = self._entries.get(icao)
        return None if entry is None else entry.sighting_count

    def type_count(self, type_code: str) -> int:
        """Unique airframes ever recorded of ``type_code``.

        Zero for an unseen type, which is the truthful answer: the map holds
        every type the receiver has ever recorded, so absence is a count of
        none rather than a missing entry.
        """
        return self._type_counts.get(type_code, 0)

    def type_counts(self) -> Mapping[str, int]:
        """A snapshot of the resident type-count map."""
        return dict(self._type_counts)

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Subscribe, warm the cache from the current live set, and run.

        Warming at start rather than waiting for events matters after a
        restart: the live set is repopulated by ingestion within a poll or two,
        but any aircraft already present when the cache starts would otherwise
        never get an appear event of its own.
        """
        if self.running:
            return
        # Subscribe before the first read so appears during warm-up queue up
        # rather than being missed.
        self._subscription = self._live.subscribe("metadata-cache", maxsize=self._queue_size)
        async with self._lock:
            await self._reload_type_counts()
            await self._populate([aircraft.icao for aircraft in self._live.snapshot()])
        self._task = asyncio.create_task(self._loop(), name="flightsite-metadata-cache")
        logger.info(
            "metadata_cache_started",
            aircraft=len(self._entries),
            types=len(self._type_counts),
        )

    async def stop(self) -> None:
        """Stop the population task and release the subscription. Idempotent."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()
        self._idle.set()
        logger.info("metadata_cache_stopped", aircraft=len(self._entries))

    async def wait_idle(self) -> None:
        """Wait until the population task finishes the cycle it is in.

        "Idle" means *not currently resolving*, which is not the same as
        "everything published has been seen": a caller that has just published
        an appear must let the task be scheduled before this answers about it
        (:func:`tests.metadata.conftest.settle` is what does that). Tests wait
        on this rather than sleeping, which is what makes the latency
        measurement measure the cache rather than a polling interval
        (``docs/TEST_STRATEGY.md`` §3).
        """
        await self._idle.wait()

    # ------------------------------------------------------------ invalidation

    async def invalidate(self) -> None:
        """Drop everything and repopulate for the current live set.

        Called when a metadata import completes: any resolved row may have
        changed, and the cache has no way to tell which, so re-resolving the
        live set is both the correct and the cheapest answer — the live set is
        the only part of the metadata database this cache ever held.

        Runs on the importing caller's task rather than the population one,
        so it takes the same lock: a population already in flight has read
        the *old* resolved rows, and letting it install them after this
        clear would leave one aircraft describing the previous dataset.
        """
        async with self._lock:
            self._entries.clear()
            await self._reload_type_counts()
            await self._populate([aircraft.icao for aircraft in self._live.snapshot()])
        logger.info(
            "metadata_cache_invalidated",
            aircraft=len(self._entries),
            types=len(self._type_counts),
        )

    # ------------------------------------------------------------- population

    async def _loop(self) -> None:
        subscription = self._subscription
        if subscription is None:  # pragma: no cover - start() always sets one
            return
        while True:
            event = await subscription.get()
            self._idle.clear()
            try:
                # Held across collect and populate together: see the lock's
                # construction for what an interleaved invalidation costs.
                async with self._lock:
                    await self._populate(self._collect(event, subscription))
            except Exception as exc:  # pragma: no cover - defensive
                # A failed population is a cache miss, not an outage: the live
                # picture is unaffected and the next import or appear retries.
                logger.warning(
                    "metadata_cache_population_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            finally:
                if subscription.pending == 0:
                    self._idle.set()

    def _collect(self, first: LiveEvent, subscription: EventSubscription) -> list[str]:
        """Apply queued lifecycle events; return addresses needing resolution.

        Removals are applied here rather than deferred: eviction is what bounds
        the cache to the live set, and an aircraft that left before its appear
        was resolved must not be resolved at all.

        A callsign change on an aircraft the cache already holds needs no
        database read — the evidence for its classification is retained on the
        entry — so it is reclassified in place here rather than joining the
        resolution list.
        """
        events = (first, *subscription.drain())
        if subscription.overflowed:
            # Shed events may have hidden a removal, so the live snapshot — not
            # the event history — decides what the cache should hold. Shed
            # events may equally have hidden a callsign, so everything the cache
            # kept is reclassified against the snapshot.
            subscription.acknowledge_overflow()
            live = {aircraft.icao for aircraft in self._live.snapshot()}
            for icao in [icao for icao in self._entries if icao not in live]:
                del self._entries[icao]
                self._notify(icao, None)
            for icao in list(self._entries):
                self._reclassify(icao)
            return [icao for icao in live if icao not in self._entries]

        wanted: list[str] = []
        for event in events:
            if isinstance(event, AircraftRemoved):
                # Evict-and-repopulate is left as it is (issue #138). Since
                # slice 062 made removals fire on schedule, a marginal-coverage
                # aircraft that flaps costs an eviction and a re-resolution per
                # cycle instead of per five minutes — but the eviction is two
                # dictionary operations, and the re-resolution is one extra
                # `icao24` in the batched pair of queries this drain was
                # already going to issue. Both are therefore bounded by the
                # live set once per drain, not by the flap rate, and the
                # alternative — a grace window like the airport service's —
                # would trade that for a second lifetime rule over an entry
                # whose only cost is the row it re-reads.
                removed = self._entries.pop(event.icao, None)
                if removed is not None:
                    self._notify(event.icao, None)
                if event.icao in wanted:
                    wanted.remove(event.icao)
            elif isinstance(event, AircraftAppeared) and event.icao not in self._entries:
                wanted.append(event.icao)
            elif isinstance(event, AircraftUpdated) and "callsign" in event.changed:
                self._reclassify(event.icao)
        return wanted

    async def _populate(self, icaos: Sequence[str]) -> None:
        """Resolve ``icaos`` in batched reads and install the results."""
        pending = [icao for icao in dict.fromkeys(icaos) if icao not in self._entries]
        if not pending:
            return
        for start in range(0, len(pending), MAX_BATCH):
            chunk = pending[start : start + MAX_BATCH]
            view = await self._repository.load_live_view(chunk)
            self._populations += 1
            for icao in chunk:
                self._install(icao, view.get(icao, AircraftLookup()))

    def _install(self, icao: str, lookup: AircraftLookup) -> None:
        """Build and store one entry, classifying it as it is built.

        Classification happens here — once per aircraft, on the population task,
        never on a request — because it is the same shape of work as the
        metadata join it accompanies and belongs on the same side of the line
        ``docs/ARCHITECTURE.md`` §3.1 draws. The serializer then reads a value
        rather than computing one.
        """
        record = self._live.get(icao)
        evidence = lookup.evidence(icao, callsign=None if record is None else record.callsign)
        type_code = None if lookup.metadata is None else lookup.metadata.type_code
        view = AircraftMetadataView(
            icao24=icao,
            metadata=lookup.metadata,
            sighting_count=lookup.sighting_count,
            type_count=None if type_code is None else self.type_count(type_code),
            operator_group=lookup.operator_group,
            evidence=evidence,
            classification=classify(evidence),
        )
        self._entries[icao] = view
        self._notify(icao, view)

    def _reclassify(self, icao: str) -> None:
        """Recompute one held entry's classification for its current callsign.

        Pure memory: the entry already carries the metadata evidence, and only
        the callsign has moved. An entry the cache does not hold is ignored —
        its appear event will classify it with the callsign it has by then.
        """
        entry = self._entries.get(icao)
        record = self._live.get(icao)
        if entry is None or record is None or entry.evidence.callsign == record.callsign:
            return
        evidence = replace(entry.evidence, callsign=record.callsign)
        view = replace(entry, evidence=evidence, classification=classify(evidence))
        self._entries[icao] = view
        self._notify(icao, view)

    def _notify(self, icao: str, view: AircraftMetadataView | None) -> None:
        """Tell the observer, if any, that ``icao``'s resolved view changed.

        Never lets an observer's own bug look like a cache failure — see the
        module docstring's "Observing resolved views" section.
        """
        if self._on_resolved is None:
            return
        try:
            self._on_resolved(icao, view)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "metadata_cache_observer_error",
                icao=icao,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _reload_type_counts(self) -> None:
        self._type_counts = await self._repository.load_type_counts()


__all__ = [
    "DEFAULT_QUEUE_SIZE",
    "MAX_BATCH",
    "AircraftMetadataView",
    "MetadataCache",
    "OnResolvedFn",
]
