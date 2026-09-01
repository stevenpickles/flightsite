"""The write-behind persistence worker: sole SQLite writer, sighting lifecycle.

This is the consumer at the far end of the pipeline in ``docs/ARCHITECTURE.md``
§3.1. It subscribes to the live event stream, keeps one accumulator per open
sighting in memory, and drains its bounded queue into batched short
transactions on :meth:`~flightsite.db.engine.Database.writer_session` — the
only writer in the process (ADR-0001, ADR-0008).

Why ingestion cannot be blocked by it
-------------------------------------

Nothing here is reachable from the ingestion path. The live store publishes
with ``put_nowait`` into this worker's bounded queue and returns; if the queue
is full the *oldest* event is shed and the subscription raises its overflow
flag. So a writer stalled on a slow SD card, a ``VACUUM``, or a five-second
``busy_timeout`` costs persistence latency and, at the extreme, shed events —
never a delayed decoder poll. The backpressure test measures exactly that:
``LiveStore.apply`` latency while this worker is artificially stalled.

The overflow flag is not ignored. On seeing it the worker resyncs from
:meth:`~flightsite.live.store.LiveStore.snapshot` — opening sightings for live
aircraft it never saw appear, and starting closure timers for sightings whose
removal event was shed — then acknowledges the episode. Silently treating a gap
as continuity would corrupt history; resyncing costs one pass over the live set.

Sighting lifecycle (SPEC §18)
-----------------------------

* **open** — the first event for an ICAO with no open sighting inserts the
  sighting row and creates or updates its ``aircraft`` row.
* **pending closure** — ``AircraftRemoved`` does *not* close the sighting. It
  arms a deadline of ``last_seen + close_s`` (600 s by default, configurable
  as ``sighting.close_s``) and the sighting stays open in the database. This is
  the mechanism behind "a new sighting begins only after the previous one has
  been closed": the accumulator is still there, keyed by ICAO, so an aircraft
  heard again inside the window is *continued* — same row, same ``started_ms``,
  extremes merged onto the same sighting — rather than opening a second one.
* **close** — once the deadline passes with no further observation, the
  sighting closes with ``closure_reason='gap_timeout'``, ``ended_ms`` set to
  the last moment the aircraft was actually heard, and its extremes merged into
  the airframe's lifetime records.

Closure is measured against the same UTC epoch-millisecond scale the
observations are stamped with, so the rule reads exactly as SPEC §18 states it:
ten minutes after the aircraft was last heard. The live store's own 15 s / 60 s
thresholds are monotonic-clock decisions about the *live set* and stay its
business.

Flush policy
------------

Writing a row per update would be tens of thousands of transactions an hour for
a dozen final values. Instead each accumulator is written:

* when the sighting opens,
* when a flight-context value changes (callsign, squawk, emergency) — the next
  cycle, not the next interval, because those are the facts a user watching a
  live aircraft expects to see recorded,
* every :data:`DEFAULT_FLUSH_INTERVAL_S` while it is dirty,
* when it closes, and
* on shutdown, where every dirty accumulator is force-flushed.

A cycle groups all of that cycle's opens, flushes and closes into one
transaction. Ids are assigned to accumulators only *after* the transaction
commits, so a failed cycle leaves in-memory state that knows it still needs
writing instead of state pointing at rolled-back rows.

Tracks, statistics and events
-----------------------------

Three more things ride that same cycle and that same transaction (ADR-0005,
SPEC §51 and §52):

* **Track checkpoints.** Each accumulator harvests new points from the live
  aircraft's :class:`~flightsite.live.track.CurrentTrack` as it observes it, and
  the cycle appends the thinned tail to ``sighting_track_checkpoints``. What a
  power cut costs an open sighting is therefore one flush interval of path, and
  no more.
* **Reception statistics** are running sums on the accumulator, written into
  the ``sightings`` row by the same flush that writes its extremes.
* **Sighting events** are queued as the transitions happen and written in the
  cycle that follows, after the sighting's own row exists. They are cleared
  only once the transaction commits, so a failed cycle retries them rather than
  losing them, and the accumulator's known-last values keep a resync or a
  restart from emitting a second copy of a change already recorded.

Overflow, and what a gap means for a track
------------------------------------------

When the queue overflows, the shed events' observations are simply absent: the
worker resyncs from the live snapshot, and the *next* harvest takes everything
the live track has accumulated in the meantime, because the harvest is keyed on
the track's own high-water mark rather than on having seen every event. The
recovered track is therefore complete wherever the live track still held the
points and thinned by absence where the aircraft left the live set unheard —
which is the honest record of what happened, and is visible as a gap between
consecutive timestamps rather than as an invented straight line.

Startup
-------

Slice 053 owns checkpoint-based unclean-shutdown recovery. Until it lands this
worker still has to behave sanely when it finds sightings open from a previous
process, and it does so with the machinery it already has: every open sighting
is rehydrated as a *pending closure* whose deadline is the airframe's last
known observation plus ``close_s``. Aircraft still being heard therefore
continue their sighting across a restart, and everything older is closed on the
first cycle with ``gap_timeout``, which is what actually happened — the aircraft
was absent for longer than the gap. Nothing here writes
``closure_reason='shutdown_recovery'``; that value, and repair from track
checkpoints, arrive with slice 053.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Final

import structlog

from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import MS_PER_SECOND, utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.meta import MetaRepository
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.live import (
    DEFAULT_QUEUE_SIZE,
    AircraftAppeared,
    AircraftRemoved,
    AircraftUpdated,
    EventSubscription,
    LiveAircraft,
    LiveEvent,
    LiveStore,
)
from flightsite.sightings.repository import ClosedTrack, SightingIds, SightingRepository
from flightsite.sightings.state import ActiveSighting, open_from
from flightsite.sightings.vocabulary import ClosureReason

logger = structlog.get_logger(__name__)

#: Absence after which a sighting closes (SPEC §18). Mirrors
#: ``sighting.close_s``; the app passes the configured value.
DEFAULT_CLOSE_S: Final = 600.0

#: How often an open sighting's running values are rewritten. Thirty seconds
#: bounds what a power cut costs an active sighting to one interval — the same
#: bound ADR-0005 puts on track checkpoints — while keeping a busy sky at a
#: couple of transactions a second rather than a few hundred.
DEFAULT_FLUSH_INTERVAL_S: Final = 30.0

#: How often the worker wakes to drain events and check closure deadlines.
#: Persistence is write-behind, so a second of latency is free; the cost of a
#: shorter tick is transactions that carry almost nothing.
DEFAULT_TICK_INTERVAL_S: Final = 1.0

#: A source of UTC epoch milliseconds. :func:`~flightsite.db.clock.utc_now_ms`
#: in production, a hand-driven fake in tests, so the 600 s closure rule is
#: verified in microseconds and never with ``asyncio.sleep``.
EpochClock = Callable[[], int]


@dataclass(frozen=True, slots=True)
class CycleResult:
    """What one worker cycle did, for tests, logs and later diagnostics."""

    events: int = 0
    opened: int = 0
    flushed: int = 0
    closed: int = 0
    #: Track points written to ``sighting_track_checkpoints`` this cycle.
    checkpointed: int = 0
    #: ``sighting_events`` rows written this cycle.
    emitted: int = 0
    #: Track points retained across every sighting closed this cycle.
    track_points: int = 0
    resynced: bool = False
    failed: bool = False

    @property
    def wrote(self) -> bool:
        """True if the cycle opened a transaction at all."""
        return bool(self.opened or self.flushed or self.closed or self.emitted)


class PersistenceWorker:
    """Drains live events into the ``aircraft`` and ``sightings`` tables.

    Args:
        database: the application database; this worker is its only writer.
        live: the live store to subscribe to and to resync from.
        close_s: absence after which a sighting closes (``sighting.close_s``).
        flush_interval_s: how often an open sighting's running values are
            rewritten.
        tick_interval_s: period of the background drain/deadline task.
        queue_size: bounded event-queue capacity. Beyond it the live store
            sheds the oldest event and this worker resyncs from the snapshot;
            it never waits, and neither does ingestion.
        clock: UTC epoch-millisecond source, injected for tests.
        counters: registry receiving ``db_errors`` when a cycle fails.
    """

    __slots__ = (
        "_active",
        "_clock",
        "_close_ms",
        "_counters",
        "_database",
        "_flush_interval_ms",
        "_live",
        "_meta",
        "_pending",
        "_queue_size",
        "_repository",
        "_subscription",
        "_t0_established",
        "_task",
        "_tick_interval_s",
    )

    def __init__(
        self,
        *,
        database: Database,
        live: LiveStore,
        close_s: float = DEFAULT_CLOSE_S,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        clock: EpochClock = utc_now_ms,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if close_s <= 0.0:
            raise ValueError("close_s must be greater than zero")
        if flush_interval_s <= 0.0:
            raise ValueError("flush_interval_s must be greater than zero")
        if tick_interval_s <= 0.0:
            raise ValueError("tick_interval_s must be greater than zero")

        self._database = database
        self._live = live
        self._close_ms = int(close_s * MS_PER_SECOND)
        self._flush_interval_ms = int(flush_interval_s * MS_PER_SECOND)
        self._tick_interval_s = tick_interval_s
        self._queue_size = queue_size
        self._clock = clock
        self._counters = counters
        self._repository = SightingRepository(database)
        self._meta = MetaRepository(database)

        self._active: dict[str, ActiveSighting] = {}
        self._pending: dict[str, ActiveSighting] = {}
        self._subscription: EventSubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._t0_established = False

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the background drain task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def active_count(self) -> int:
        """Open sightings whose aircraft is currently live."""
        return len(self._active)

    @property
    def pending_count(self) -> int:
        """Open sightings whose aircraft is absent and whose gap is running."""
        return len(self._pending)

    @property
    def t0_established(self) -> bool:
        """True once T0 is known to be recorded (SPEC §16)."""
        return self._t0_established

    def sighting_for(self, icao: str) -> ActiveSighting | None:
        """The accumulator tracking ``icao``, live or pending, if any."""
        return self._active.get(icao) or self._pending.get(icao)

    def sighting_id_for(self, icao: str) -> int | None:
        """The id of ``icao``'s open sighting row, or ``None`` if there is none.

        ``None`` covers three real states and is the honest answer to all of
        them (``docs/API.md`` §2.7): no sighting is open, one is open but its
        ``INSERT`` has not committed yet (the first second or so of a new
        aircraft), or persistence is degraded and no row exists at all. The
        live API reads this per aircraft when it serializes the live set, so it
        is a plain in-memory lookup — asking the database here would put SQLite
        on the live path, which ``docs/ARCHITECTURE.md`` §3.1 forbids.
        """
        active = self.sighting_for(icao)
        return None if active is None else active.sighting_id

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Subscribe, adopt any open sightings, and start draining. Idempotent."""
        if self.running:
            return

        # Subscribe before reading anything: events published while startup
        # recovery runs then queue up rather than being lost. Re-entry is
        # guarded by `running` above and `stop` detaches, so this is never a
        # second live subscription for the same worker.
        self._subscription = self._live.subscribe("persistence", maxsize=self._queue_size)

        self._t0_established = await self._meta.get_t0() is not None
        await self._adopt_open_sightings()

        self._task = asyncio.create_task(self._loop(), name="flightsite-persistence")
        logger.info(
            "persistence_worker_started",
            close_s=self._close_ms / MS_PER_SECOND,
            flush_interval_s=self._flush_interval_ms / MS_PER_SECOND,
            adopted=len(self._pending),
            t0_established=self._t0_established,
        )

    async def stop(self) -> None:
        """Stop draining and flush every dirty accumulator. Idempotent.

        Sightings are left *open* in the database. A clean stop is not an
        observation gap: if the process comes back inside ``close_s`` the next
        startup adopts them and the aircraft's sighting continues, which is the
        same rule a live aircraft gets while the process is running.
        """
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        result = await self.process_pending(force_flush=True)

        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()
        logger.info(
            "persistence_worker_stopped",
            open_sightings=len(self._active) + len(self._pending),
            flushed=result.flushed,
            closed=result.closed,
        )

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval_s)
            try:
                await self.process_pending()
            except Exception as exc:  # pragma: no cover - defensive
                # Database failures are already handled inside the cycle; this
                # guard only exists so an unforeseen bug cannot silently kill
                # persistence for the rest of the process's life.
                logger.warning(
                    "persistence_cycle_error", error=str(exc), error_type=type(exc).__name__
                )

    # ------------------------------------------------------------- one cycle

    async def process_pending(self, *, force_flush: bool = False) -> CycleResult:
        """Drain queued events and run one write cycle.

        Split out from the loop so tests drive it deterministically: no
        sleeping, no waiting on a background task, one call per simulated
        instant.
        """
        subscription = self._subscription
        if subscription is None:
            return CycleResult()

        events = subscription.drain()
        for event in events:
            self._handle(event)

        resynced = subscription.overflowed
        if resynced:
            self._resync(subscription)

        result = await self._commit(force_flush=force_flush)
        return replace(result, events=len(events), resynced=resynced)

    # --------------------------------------------------------- event handling

    def _handle(self, event: LiveEvent) -> None:
        """Fold one live event into the in-memory sighting state.

        ``AircraftStale`` carries no new observation — it announces silence —
        so it is deliberately not handled: staleness is a live-display concern,
        and the closure gap is measured from ``last_seen`` regardless.
        """
        if isinstance(event, AircraftAppeared | AircraftUpdated):
            self._observe(event.aircraft)
        elif isinstance(event, AircraftRemoved):
            self._arm_closure(event.aircraft)

    def _observe(self, record: LiveAircraft) -> ActiveSighting:
        """Route an observation to its sighting, opening or continuing one.

        The three cases are the whole of SPEC §18's identity rule: an aircraft
        already being sighted continues its sighting; one whose closure gap is
        still running is *resumed* into the same sighting; only an aircraft
        with no open sighting at all starts a new one.
        """
        icao = record.icao
        active = self._active.get(icao)
        if active is not None:
            active.observe(record)
            return active

        resumed = self._pending.pop(icao, None)
        if resumed is not None:
            resumed.close_deadline_ms = None
            resumed.observe(record)
            self._active[icao] = resumed
            logger.debug("sighting_continued", icao=icao, sighting_id=resumed.sighting_id)
            return resumed

        opened = open_from(record)
        self._active[icao] = opened
        return opened

    def _arm_closure(self, record: LiveAircraft) -> None:
        """Start the closure gap for an aircraft that left the live set.

        The sighting stays open in the database. An aircraft heard again before
        the deadline resumes it; nothing else may open a sighting for that ICAO
        in the meantime.

        A removal for an ICAO with no accumulator is not ignored: the event
        carries the full record, so the sighting is opened from it and armed in
        one step. That is the shape an overflow episode leaves behind, and
        dropping it would lose a real observation period.
        """
        active = self._active.pop(record.icao, None) or self._pending.get(record.icao)
        if active is None:
            active = open_from(record)
        else:
            active.observe(record)
        active.close_deadline_ms = active.last_seen_ms + self._close_ms
        # Persist what the sighting knows before the gap starts: if the process
        # dies during those ten minutes, this is the state startup finds.
        active.flush_immediately = True
        self._pending[record.icao] = active

    def _resync(self, subscription: EventSubscription) -> None:
        """Rebuild from the live snapshot after the event queue overflowed.

        Two kinds of damage are possible and both are repaired here: an
        ``AircraftAppeared`` that was shed (an aircraft is live with no
        sighting) and an ``AircraftRemoved`` that was shed (a sighting is
        active for an aircraft that has left the live set, so its closure gap
        never started).
        """
        live_icaos = set()
        for record in self._live.snapshot():
            live_icaos.add(record.icao)
            self._observe(record)

        for icao in [icao for icao in self._active if icao not in live_icaos]:
            active = self._active.pop(icao)
            active.close_deadline_ms = active.last_seen_ms + self._close_ms
            active.flush_immediately = True
            self._pending[icao] = active

        dropped = subscription.acknowledge_overflow()
        logger.warning(
            "persistence_resynced_from_snapshot",
            dropped=dropped,
            live=len(live_icaos),
            active=len(self._active),
            pending=len(self._pending),
        )

    # ---------------------------------------------------------- the write leg

    def _accumulators(self) -> Iterator[ActiveSighting]:
        yield from self._active.values()
        yield from self._pending.values()

    async def _commit(self, *, force_flush: bool) -> CycleResult:
        """Write this cycle's opens, flushes, checkpoints, events and closes.

        One transaction for all of it. The in-memory bookkeeping that says
        "this reached the disk" — ids, flush marks, checkpoint high-water
        marks, event queues — is applied only after the commit returns, so a
        failed cycle leaves every accumulator ready to write the same work
        again rather than believing it already did.
        """
        now_ms = self._clock()
        due = [
            active
            for active in self._pending.values()
            if active.close_deadline_ms is not None and now_ms >= active.close_deadline_ms
        ]
        closing = {active.icao for active in due}
        opens = [active for active in self._accumulators() if active.sighting_id is None]
        flushes = [
            active
            for active in self._accumulators()
            # A closing sighting is written by the close itself; flushing it
            # first would be the same row twice in one transaction.
            if active.icao not in closing
            and active.sighting_id is not None
            and active.needs_flush(now_ms, self._flush_interval_ms, force=force_flush)
        ]
        # Checkpoints ride the writes that are already happening. A closing
        # sighting is excluded because its close packs the same points and then
        # deletes the rows this would have written.
        batches = {
            active.icao: batch
            for active in [*opens, *flushes]
            if active.icao not in closing and (batch := active.checkpoint_batch()) is not None
        }
        # Events are written for every accumulator holding any, including one
        # closing this cycle: the transition happened inside the sighting and
        # belongs to its timeline.
        queued = {
            active.icao: active.take_events()
            for active in self._accumulators()
            if active.pending_events
        }

        if not (opens or flushes or due or queued):
            return CycleResult()

        opened_ids: dict[str, SightingIds] = {}
        closed_tracks: list[ClosedTrack] = []
        try:
            async with self._database.writer_session() as session:
                for active in opens:
                    opened_ids[active.icao] = await self._repository.open_sighting(session, active)
                for active in flushes:
                    await self._repository.flush_sighting(session, self._ids(active), active)
                for active in [*opens, *flushes]:
                    batch = batches.get(active.icao)
                    if batch is not None:
                        await self._repository.append_checkpoints(
                            session, self._resolved(active, opened_ids).sighting_id, batch.rows
                        )
                for active in self._accumulators():
                    events = queued.get(active.icao)
                    if events:
                        await self._repository.append_events(
                            session, self._resolved(active, opened_ids).sighting_id, events
                        )
                for active in due:
                    closed_tracks.append(
                        await self._repository.close_sighting(
                            session,
                            self._resolved(active, opened_ids),
                            active,
                            reason=ClosureReason.GAP_TIMEOUT,
                        )
                    )
        except Exception as exc:
            # The accumulators are untouched, so the next cycle retries the
            # whole batch. Ingestion is unaffected either way — that is the
            # point of writing behind a queue.
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "persistence_cycle_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                opens=len(opens),
                flushes=len(flushes),
                closes=len(due),
            )
            return CycleResult(failed=True)

        for active in opens:
            active.aircraft_id, active.sighting_id = opened_ids[active.icao]
            active.mark_flushed(now_ms)
        for active in flushes:
            active.mark_flushed(now_ms)
        for active in self._accumulators():
            batch = batches.get(active.icao)
            if batch is not None:
                active.mark_checkpointed(batch)
            active.mark_events_written(len(queued.get(active.icao, ())))
        for active, track in zip(due, closed_tracks, strict=True):
            self._pending.pop(active.icao, None)
            logger.info(
                "sighting_closed",
                icao=active.icao,
                sighting_id=active.sighting_id,
                duration_ms=active.duration_ms,
                closure_reason=ClosureReason.GAP_TIMEOUT.value,
                track_points=track.point_count,
                track_bytes=track.byte_count,
            )

        await self._establish_t0(opens)
        return CycleResult(
            opened=len(opens),
            flushed=len(flushes),
            closed=len(due),
            checkpointed=sum(len(batch.rows) for batch in batches.values()),
            emitted=sum(len(events) for events in queued.values()),
            track_points=sum(track.point_count for track in closed_tracks),
        )

    @staticmethod
    def _ids(active: ActiveSighting) -> SightingIds:
        aircraft_id, sighting_id = active.aircraft_id, active.sighting_id
        if aircraft_id is None or sighting_id is None:  # pragma: no cover - guarded by callers
            raise LookupError(f"sighting for {active.icao} has not been inserted yet")
        return SightingIds(aircraft_id=aircraft_id, sighting_id=sighting_id)

    @classmethod
    def _resolved(cls, active: ActiveSighting, opened_ids: dict[str, SightingIds]) -> SightingIds:
        """Ids for an accumulator, including one inserted earlier this cycle.

        The accumulator does not learn its own id until the transaction
        commits, so anything written *after* the insert and *before* the commit
        — checkpoints, events, the close itself — has to read it from here.
        """
        return opened_ids.get(active.icao) or cls._ids(active)

    async def _establish_t0(self, opens: list[ActiveSighting]) -> None:
        """Record T0 the first time an observation is actually persisted.

        Set *after* the transaction commits, so T0 can never name a moment no
        sighting exists for. ``set_t0_once`` is write-once in SQL, so a second
        process or a second call cannot move it (SPEC §16); the in-memory flag
        merely saves the round trip.
        """
        if self._t0_established or not opens:
            return
        t0_ms = min(active.started_ms for active in opens)
        if await self._meta.set_t0_once(t0_ms):
            logger.info("t0_established", t0_ms=t0_ms)
        self._t0_established = True

    # ---------------------------------------------------------------- startup

    async def _adopt_open_sightings(self) -> None:
        """Rehydrate sightings a previous process left open.

        Each becomes a pending closure with the deadline it would have had:
        the airframe's last known observation plus ``close_s``. Aircraft still
        being heard resume their sighting on the next event; the rest close on
        the first cycle with ``gap_timeout``, since an absence longer than the
        gap is precisely what happened. Interim behaviour — slice 053 replaces
        it with checkpoint-based repair and ``shutdown_recovery``.
        """
        rows = await self._repository.load_open_sightings()
        if not rows:
            return
        for row in rows:
            adopted = row.to_accumulator()
            adopted.close_deadline_ms = adopted.last_seen_ms + self._close_ms
            self._pending[adopted.icao] = adopted
        logger.info("open_sightings_adopted", count=len(rows))


__all__ = [
    "DEFAULT_CLOSE_S",
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_TICK_INTERVAL_S",
    "CycleResult",
    "EpochClock",
    "PersistenceWorker",
]
