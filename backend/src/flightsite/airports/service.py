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

The latch also survives a **removal**, for :data:`PHASE_GRACE_S` (issue #138).
Low and slow over a field is exactly where a receiver's coverage is worst, so
the aircraft whose phase is most interesting is the one most likely to drop out
for a minute on final — and until slice 062 the removal event fired minutes
late, which was accidentally protecting the latch from precisely that. Dropping
the latch on removal means an aircraft that reappears at 300 ft on the
threshold is re-inferred from an empty trail and reads as nothing at all, when
what actually happened is one dropout inside one approach. So a removed
aircraft's answer and trail are set aside rather than discarded, and a
reappearance inside the window picks them back up; past it they are gone. The
sighting's persisted inference was never at risk either way — it is on the
row — but the live answer is what the map draws.
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

#: How long a removed aircraft's answer and trail are kept, in seconds, so a
#: reappearance resumes the approach it was already in rather than starting
#: over (issue #138 — see the module docstring).
#:
#: Measured on the **observation** clock, from the last moment the aircraft was
#: actually heard, and compared against the timestamp of the observation that
#: brings it back — not from the removal event, and never from the wall clock.
#: The whole of the rest of this module reasons in decoder timestamps, and what
#: is being asked here is "are the observations behind this phase still recent
#: enough to mean anything?", which is a question about the observations.
#:
#: Two minutes, chosen against the two things either side of it. Below: the
#: live store removes an aircraft 60 s after it was last heard, so anything
#: much shorter would expire at, or before, the moment a dropout could even be
#: observed. Above: the trend gate's own look-back is two minutes, so a trail
#: older than that contributes nothing to an inference anyway, and a phase held
#: longer would outlive every input that produced it. A gap longer than this is
#: a new arrival to reason about, not the same approach continuing.
PHASE_GRACE_S: Final = 120.0


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
        "_grace_ms",
        "_index",
        "_lapsed",
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
        phase_grace_s: float = PHASE_GRACE_S,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least one")
        if phase_grace_s < 0.0:
            raise ValueError("phase_grace_s must not be negative")
        self._live = live
        self._persistence = persistence
        self._repository = repository
        self._queue_size = queue_size
        self._search_nm = search_nm
        self._grace_ms = int(phase_grace_s * 1_000)
        self._index = AirportIndex()
        self._subscription: EventSubscription | None = None
        self._reader: asyncio.Task[None] | None = None
        #: Current answer per ICAO, most recently touched last.
        self._answers: OrderedDict[str, AirportContext] = OrderedDict()
        #: Recent ranges per ICAO, oldest first.
        self._trails: dict[str, deque[TrendSample]] = {}
        #: Removed aircraft still inside their grace window: the answer and
        #: trail set aside, with the instant they stop being worth keeping.
        #: Insertion order is expiry order, because every entry is stamped from
        #: the observation clock and the events arrive in that order.
        self._lapsed: OrderedDict[str, tuple[AirportContext, deque[TrendSample], int]] = (
            OrderedDict()
        )

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

    def name_for(self, ident: str) -> str | None:
        """The local name of the airport with this ident, or ``None``.

        The lookup behind ``route.origin_name``/``route.destination_name``
        (``docs/API.md`` §2.6). Unrelated to the nearest-airport inference this
        service otherwise makes: it answers a question about an ident somebody
        *else* supplied — the route enrichment provider — from the same
        in-memory dataset, and it makes no claim of its own.

        A dictionary access on
        :meth:`~flightsite.airports.index.AirportIndex.name_for`, with no
        ``await`` and no session, because the live aircraft serializer calls it
        twice per aircraft per frame. ``None`` on an install that has never
        imported the airport dataset, and for any ident the dataset does not
        carry.
        """
        return self._index.name_for(ident)

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

        Removal sets the aircraft's answer and trail aside for
        :data:`PHASE_GRACE_S` rather than dropping them (issue #138): a dropout
        on final is a gap in coverage, not the end of an approach, and the
        latch is what stops the gap from erasing it. Past the window they go.
        The persisted inference stays on the sighting row throughout, which is
        the point of persisting it.
        """
        if isinstance(event, AircraftRemoved):
            self._lapse(event.aircraft)
            return
        if isinstance(event, AircraftAppeared | AircraftUpdated):
            self._observe(event.aircraft)

    def _forget(self, icao: str) -> None:
        """Drop everything held for an aircraft, with no grace.

        Used where the answer is *wrong* rather than merely absent — the
        aircraft has flown out of range of every field — which is the one case
        a grace window must not cover.
        """
        self._answers.pop(icao, None)
        self._trails.pop(icao, None)
        self._lapsed.pop(icao, None)

    def _lapse(self, record: LiveAircraft) -> None:
        """Set a removed aircraft's answer aside for the grace window."""
        answer = self._answers.pop(record.icao, None)
        trail = self._trails.pop(record.icao, None)
        if answer is None or self._grace_ms == 0:
            self._lapsed.pop(record.icao, None)
            return
        expiry_ms = to_epoch_ms(record.last_seen) + self._grace_ms
        self._lapsed[record.icao] = (answer, trail if trail is not None else deque(), expiry_ms)
        self._lapsed.move_to_end(record.icao)
        while len(self._lapsed) > MAX_TRACKED_AIRCRAFT:
            self._lapsed.popitem(last=False)

    def _resume(self, icao: str, now_ms: int) -> None:
        """Take back a lapsed answer if it is still inside its window.

        Expired entries at the front are dropped on the way past, which is what
        keeps this store bounded by *recent* removals rather than by every
        removal the process has ever seen. Insertion order is expiry order, so
        the sweep stops at the first entry that is still live.
        """
        while self._lapsed:
            oldest, (_, _, expiry_ms) = next(iter(self._lapsed.items()))
            if expiry_ms > now_ms:
                break
            del self._lapsed[oldest]
        held = self._lapsed.pop(icao, None)
        if held is None:
            return
        answer, trail, expiry_ms = held
        if expiry_ms <= now_ms:
            return
        self._answers[icao] = answer
        self._answers.move_to_end(icao)
        self._trails[icao] = trail

    def _observe(self, record: LiveAircraft) -> None:
        """Walk the gates for one observation and record whatever they allow."""
        position = record.position
        if position is None or not self._index.size:
            return

        self._resume(record.icao, to_epoch_ms(record.last_seen))
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
