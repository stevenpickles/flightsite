"""The airport context worker: live aircraft in, nearest-airport context out.

The seam, and why it is this one
--------------------------------

The same seam :mod:`flightsite.enrichment.service` chose, for the same reason
``docs/ARCHITECTURE.md`` §3.1 gives: *"A slow consumer can lag or drop to a
resync; it cannot stall the adapter loop."* This is an independent consumer of
the live event stream with its own bounded subscription and its own task. The
live store publishes with ``put_nowait`` and returns; nothing on the ingestion
path or the API path can reach this module at all.

It differs from enrichment in one way that matters: there is no network and no
provider, so there is no lookup queue and no second task. Every answer is
computed from an in-memory index in microseconds, which means the reader loop
can compute in place and the whole service is one task.

What it borrows is the *write* discipline. When an inference firms up it calls
:meth:`~flightsite.sightings.worker.PersistenceWorker.apply_inferred_airport`,
which sets the accumulator's running values so they land in the worker's next
cycle. This service opens no writer session of its own, and it makes no
database read at all after startup.

Zero database on the hot path
-----------------------------

:class:`~flightsite.airports.index.AirportIndex` is built once at
:meth:`AirportContextService.start` and rebuilt only when an import replaces the
dataset. ``docs/ARCHITECTURE.md`` §3.1 forbids SQLite on the live path, and a
nearest-airport question arrives once per low aircraft per decoder poll — so the
whole ~70k-row dataset lives in memory, exactly as the metadata cache keeps
resolved metadata there for the same reason.

Rebuilding mirrors :meth:`~flightsite.metadata.cache.MetadataCache.invalidate`:
:meth:`reload` builds a *new* index and swaps the reference in one assignment.
A query in flight during a rebuild therefore reads the whole old index rather
than a half-replaced one, and no lock is needed on the read side.

What it remembers, and what it forgets
--------------------------------------

Two things per aircraft, both bounded by the live set and both dropped when the
aircraft leaves it:

* **The answer** — an :class:`~flightsite.airports.model.AirportContext`, which
  is what the API reads.
* **A trail** of recent ranges to the nearest field, which is what the trend
  gate in :mod:`flightsite.airports.inference` reads. Pruned to the gate's own
  window, so it is a handful of samples per low aircraft and nothing at all for
  the cruising majority.

A phase, once inferred, is **latched for as long as the aircraft stays with the
same field**. An aircraft on short final levels briefly in the flare, and a
departure's climb pauses at a level-off; without a latch the API would flicker
between "likely arriving" and nothing on a one-second cadence. The latch is
dropped the moment a different field becomes nearest, because then the phase
would be a statement about somewhere the aircraft no longer is.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict, deque
from typing import Final

import structlog

from flightsite.airports.index import AirportIndex
from flightsite.airports.inference import (
    NEAREST_SEARCH_NM,
    Kinematics,
    TrendSample,
    in_context,
    infer_phase,
    trail_window_start,
)
from flightsite.airports.model import AirportContext, InferredPhase
from flightsite.airports.repository import AirportRepository
from flightsite.db.clock import to_epoch_ms
from flightsite.live.aircraft import LiveAircraft
from flightsite.live.events import (
    AircraftAppeared,
    AircraftRemoved,
    AircraftUpdated,
    EventSubscription,
    LiveEvent,
)
from flightsite.live.store import LiveStore
from flightsite.sightings.state import InferredAirport
from flightsite.sightings.worker import PersistenceWorker

logger = structlog.get_logger(__name__)

#: Live events buffered for this service before the store sheds the oldest.
#: The same size as enrichment's and for the same reason: recovery from a shed
#: event costs one delayed inference, not a corrupted history, and the aircraft
#: is observed again on the next decoder poll.
DEFAULT_QUEUE_SIZE: Final = 1024

#: Trail samples kept per aircraft. The trend gate looks back two minutes; at a
#: 1 Hz decoder cadence that is 120 samples, and this bounds the pathological
#: case of a decoder polling far faster. Oldest-first eviction, so the bound
#: costs reach rather than currency.
MAX_TRAIL_SAMPLES: Final = 256

#: Aircraft whose context is remembered at once. Comfortably above any
#: realistic live set, so in practice the bound never binds — it exists so a
#: leak in the removal path costs memory that stops growing instead of memory
#: that does not.
MAX_TRACKED_AIRCRAFT: Final = 4096


class AirportContextService:
    """Consumes the live stream and maintains nearest-airport context.

    Args:
        live: the live store to subscribe to.
        persistence: the worker owning the open sightings; inferences are
            applied through it so they ride its transaction discipline.
        repository: the ``airports`` repository the index is built from.
        queue_size: bounded live-event subscription capacity.
        search_nm: how far to look for a nearest airport. Injected so a test
            can shrink the world; production uses the inference module's own
            :data:`~flightsite.airports.inference.NEAREST_SEARCH_NM`.
    """

    __slots__ = (
        "_answers",
        "_index",
        "_live",
        "_persistence",
        "_queue_size",
        "_reader",
        "_repository",
        "_search_nm",
        "_subscription",
        "_trails",
    )

    def __init__(
        self,
        *,
        live: LiveStore,
        persistence: PersistenceWorker,
        repository: AirportRepository,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        search_nm: float = NEAREST_SEARCH_NM,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least one")
        self._live = live
        self._persistence = persistence
        self._repository = repository
        self._queue_size = queue_size
        self._search_nm = search_nm
        self._index = AirportIndex()
        self._subscription: EventSubscription | None = None
        self._reader: asyncio.Task[None] | None = None
        #: Current answer per ICAO, most recently touched last.
        self._answers: OrderedDict[str, AirportContext] = OrderedDict()
        #: Recent ranges per ICAO, oldest first.
        self._trails: dict[str, deque[TrendSample]] = {}

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the consumer task is alive."""
        return self._reader is not None and not self._reader.done()

    @property
    def index(self) -> AirportIndex:
        """The index queries currently answer from."""
        return self._index

    @property
    def known_airports(self) -> int:
        """How many airports the current index holds. Zero before an import."""
        return self._index.size

    @property
    def tracked(self) -> int:
        """Aircraft currently holding an answer."""
        return len(self._answers)

    def context_for(self, icao: str) -> AirportContext | None:
        """The nearest-airport context for ``icao``, or ``None``.

        A plain dictionary lookup with no ``await`` and no session: the live API
        calls this once per aircraft per frame, so anything else would put
        SQLite on the live path (``docs/ARCHITECTURE.md`` §3.1).

        ``None`` covers every honest reason there is nothing to say — no
        airport dataset imported, the aircraft is at cruise, it is nowhere near
        a field, it has no position — and the API renders all of them the same
        way (``docs/API.md`` §2.7).
        """
        return self._answers.get(icao)

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Load the index, subscribe and start consuming. Idempotent.

        The index is loaded *before* the subscription, so the first event this
        service handles is answered from a full index rather than an empty one.
        A load that finds no rows — the normal state until a user runs an
        update — leaves an empty index and every answer ``None``, which costs
        one dictionary miss per observation and nothing else.
        """
        if self.running:
            return
        await self.reload()
        self._subscription = self._live.subscribe("airports", maxsize=self._queue_size)
        self._reader = asyncio.create_task(self._read_loop(), name="flightsite-airports")
        logger.info("airport_context_started", airports=self._index.size)

    async def stop(self) -> None:
        """Stop consuming and release the subscription. Idempotent."""
        task, self._reader = self._reader, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()
        logger.info("airport_context_stopped", tracked=len(self._answers))

    async def reload(self) -> int:
        """Rebuild the index from the ``airports`` table. Returns its size.

        Called at startup and after an import that replaced the dataset — the
        airport equivalent of
        :meth:`~flightsite.metadata.cache.MetadataCache.invalidate`, and wired
        up the same way, as a listener the metadata service runs once a run has
        actually changed data.

        The new index is built completely before the reference is swapped, so
        the swap is one atomic assignment and a concurrent query reads either
        the whole old index or the whole new one.
        """
        records = await self._repository.load_all()
        self._index = AirportIndex(records)
        logger.info("airport_index_rebuilt", airports=self._index.size)
        return self._index.size

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
                # No resync is owed. This consumer holds no history a gap could
                # corrupt: a shed event costs one missing trail sample, and the
                # trend gate simply waits for the next observation.
                subscription.acknowledge_overflow()

    def consider(self, event: LiveEvent) -> None:
        """Update this aircraft's context from one live event.

        Public because it is the whole of the read side's decision, and tests
        drive it directly rather than through a task.

        Removal drops everything held for the aircraft. The persisted
        inference stays on the sighting row, which is the point of persisting
        it; what goes is the live answer and the trail, neither of which means
        anything for an aircraft that is no longer in the sky.
        """
        if isinstance(event, AircraftRemoved):
            self._forget(event.icao)
            return
        if isinstance(event, AircraftAppeared | AircraftUpdated):
            self._observe(event.aircraft)

    def _forget(self, icao: str) -> None:
        self._answers.pop(icao, None)
        self._trails.pop(icao, None)

    def _observe(self, record: LiveAircraft) -> None:
        """Walk the gates for one observation and record whatever they allow."""
        position = record.position
        if position is None or not self._index.size:
            return

        nearest = self._index.nearest(position, within_nm=self._search_nm)
        if nearest is None:
            # Out of range of every field. The previous answer is dropped
            # rather than kept: it described somewhere the aircraft has flown
            # away from, and a stale nearest airport is worse than none.
            self._forget(record.icao)
            return

        ts_ms = to_epoch_ms(record.last_seen)
        kinematics = Kinematics(
            altitude_ft=record.altitude_ft,
            vertical_rate_fpm=record.vertical_rate_fpm,
            on_ground=record.on_ground,
            ts_ms=ts_ms,
        )
        # The trail is read *before* this observation joins it: the inference
        # treats the current range as the end of the trend, not as a member of
        # it, so appending first would compare the observation to itself.
        trail = self._trail(record.icao)
        self._remember_sample(record.icao, nearest.airport.ident, nearest.distance_nm, ts_ms)

        if not in_context(nearest, kinematics):
            self._answers.pop(record.icao, None)
            return

        phase = infer_phase(nearest, kinematics, trail)
        phase = self._latched(record.icao, nearest.airport.ident, phase)
        context = AirportContext(
            ident=nearest.airport.ident,
            name=nearest.airport.name,
            distance_nm=nearest.distance_nm,
            phase=phase,
        )
        self._answers[record.icao] = context
        self._answers.move_to_end(record.icao)
        self._evict()
        self._persist(record.icao, context, on_ground=bool(record.on_ground), at_ms=ts_ms)

    def _latched(self, icao: str, ident: str, phase: InferredPhase | None) -> InferredPhase | None:
        """A freshly inferred phase, or the one already held for this field.

        See the module docstring's "What it remembers": a phase is latched
        against the field it was inferred for, so a momentary level-off does not
        blank it, and a new field clears it.
        """
        if phase is not None:
            return phase
        held = self._answers.get(icao)
        if held is not None and held.ident == ident:
            return held.phase
        return None

    def _persist(self, icao: str, context: AirportContext, *, on_ground: bool, at_ms: int) -> None:
        """Hand a context to the persistence worker's accumulator.

        Only what the sighting row should keep is handed over. A context with
        no phase is persisted **only when the decoder says the aircraft is on
        the ground** — and gate 5 has already required it to be within
        :data:`~flightsite.airports.inference.ON_GROUND_MAX_DISTANCE_NM` of the
        field — because that is a near-certainty rather than an inference. An
        aircraft that merely flew low past a field therefore leaves no claim
        behind it in history. Everything else that reaches here carries a
        phase, which is by construction something the gates were confident
        about.

        ``on_ground`` is the decoder's own statement, carried down from the
        observation rather than re-read, and never the live layer's airborne
        inference (:data:`~flightsite.live.aircraft.AIRBORNE_INFERENCE_ALTITUDE_FT`).
        """
        if context.phase is None and not on_ground:
            return
        self._persistence.apply_inferred_airport(
            icao,
            InferredAirport(
                ident=context.ident,
                phase=None if context.phase is None else context.phase.value,
            ),
            at_ms=at_ms,
        )

    # ------------------------------------------------------------ the trail

    def _trail(self, icao: str) -> tuple[TrendSample, ...]:
        """This aircraft's remembered range samples, oldest first."""
        return tuple(self._trails.get(icao, ()))

    def _remember_sample(self, icao: str, ident: str, distance_nm: float, ts_ms: int) -> None:
        """Append one range sample and drop what the trend gate cannot use."""
        trail = self._trails.setdefault(icao, deque(maxlen=MAX_TRAIL_SAMPLES))
        cutoff = trail_window_start(ts_ms)
        while trail and trail[0].ts_ms < cutoff:
            trail.popleft()
        trail.append(TrendSample(ident=ident, distance_nm=distance_nm, ts_ms=ts_ms))

    def _evict(self) -> None:
        """Drop the least recently updated aircraft once the bound is exceeded."""
        while len(self._answers) > MAX_TRACKED_AIRCRAFT:
            icao, _ = self._answers.popitem(last=False)
            self._trails.pop(icao, None)


__all__ = [
    "DEFAULT_QUEUE_SIZE",
    "MAX_TRACKED_AIRCRAFT",
    "MAX_TRAIL_SAMPLES",
    "AirportContextService",
]
