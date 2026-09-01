"""The activity service: one pass, every producer, one transaction.

Where this runs, and why
------------------------

The same shape as :mod:`flightsite.analytics.service`, because the constraint
is the same one (``docs/ARCHITECTURE.md`` §3.1): nothing on the live path may
wait on SQLite, and only one thing in the process may write to it.

* **Driven by the persistence worker's seam.** The service subscribes to
  :meth:`~flightsite.sightings.worker.PersistenceWorker.subscribe_lifecycle`
  and records what each *committed* cycle closed. That callback is synchronous,
  allocation-light and never raises — it runs inside the worker's cycle.
  :meth:`ActivityService.record_alert_matches` (slice 038) is the same shape
  and the same contract, called from the alert engine's cycle once its own
  transaction has committed.
* **Written on this service's own task, in its own transaction.** A pass reads
  the facts, asks the producers what they justify, and writes the result
  through :meth:`~flightsite.db.engine.Database.writer_session`. A feed bug can
  therefore delay the feed; it cannot fail a sighting.
* **Repaired by a catch-up scan.** Everything the seam could lose is
  recoverable from ``sightings`` itself, so the pass does not depend on the
  seam for correctness — see below.

Exactly-once, and what it survives
----------------------------------

Three mechanisms stack, and each covers what the one before it cannot:

1. **The watermark.** Opens are found by scanning ``sightings`` for ids above
   ``meta['activity.scanned_sighting_id']``, not by trusting a notification.
   A process that dies between a committed cycle and the pass that would have
   examined it comes back and examines it, however long it was down. On a
   database that has never run this service the watermark is initialized to the
   *present* rather than to zero, so an install upgrading into slice 035 does
   not narrate years of history into the feed on its first boot.
2. **Value-derived dedupe keys.** Every producer names its event after a fact —
   an ICAO address, a type designator, a distance, a sighting id — never after
   the moment it ran (:mod:`flightsite.activity.model`). Re-examining a
   sighting therefore recomputes the identical key.
3. **The ``UNIQUE`` index and the milestone primary key.** The second insert of
   the same key is refused by SQLite, and only rows that were genuinely created
   come back from :meth:`~flightsite.activity.repository.ActivityRepository.record`
   — so a re-examination is silent on the WebSocket as well as in the table.

That is the roadmap's *"no duplicates on restart/replay"*, and none of it
depends on the service remembering anything across a restart. The watermark is
an optimisation for how *much* is re-examined, not for whether re-examination
is safe: if it were lost entirely, the pass would re-derive everything and
write nothing.

What is deliberately *not* recovered after a stop
--------------------------------------------------

Rolling records — the furthest detection, the busiest day, the highest
simultaneous count, the longest sighting — are compared against a baseline this
service seeds from the database at :meth:`ActivityService.start`. A record
beaten while the service was stopped is therefore adopted silently rather than
announced late. That is the correct trade: the alternative is a first boot
after an upgrade announcing every standing record as though it had just
happened, and the records themselves are never wrong, because the seed reads
ground truth.

Degradation
-----------

Every failure mode ends in the feed being later, and none of them ends anywhere
else. A failed pass counts ``db_errors``, keeps its pending work and retries on
the next one; a listener that raises is logged and skipped; a notification that
arrives while the service is stopped is remembered in plain memory, and either
a later start flushes it or the process is going away.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

import structlog

from flightsite.activity.facts import (
    AlertMatchFact,
    HealthEpisode,
    ImportOutcome,
    LongestSighting,
    ReceiverRecords,
    SightingObservation,
)
from flightsite.activity.model import (
    MILESTONE_FIRST_MILITARY,
    ActivityBatch,
    StoredActivityEvent,
)
from flightsite.activity.producers import (
    alert_events,
    best_closed,
    first_ever_events,
    health_events,
    import_events,
    longest_sighting_event,
    merge,
    military_milestone,
    new_type_events,
    record_events,
)
from flightsite.activity.repository import (
    DEFAULT_SCAN_LIMIT,
    SCAN_WATERMARK_KEY,
    ActivityRepository,
)
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import MS_PER_SECOND, utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.meta import MetaRepository
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.metadata.importer import ImportRun
from flightsite.sightings.worker import PersistenceWorker, SightingLifecycle

logger = structlog.get_logger(__name__)

#: How often a pass runs. Five seconds rather than the thirty the analytics
#: rollups use: this is the latency between an aircraft appearing and the feed
#: saying so, and the feed is something a user watches. A pass over an idle
#: receiver is two indexed reads and no transaction.
DEFAULT_FLUSH_INTERVAL_S: Final = 5.0

#: How long a decoder connection state must hold before a transition is
#: announced. A minute is far longer than any reconnect
#: (:data:`~flightsite.ingest.health.BACKOFF_MAX_S` is 60 s at the extreme and
#: the first retry is a second), so a decoder restart, a Wi-Fi hiccup or a
#: dropped poll cannot reach the feed — while a real outage is reported inside
#: the minute it becomes real. Flapping between up and down produces no events
#: at all, because neither state ever holds long enough to be announced.
DEFAULT_OFFLINE_DEBOUNCE_S: Final = 60.0

#: A source of UTC epoch milliseconds, injected so debounce and cadence tests
#: run against a hand-driven clock rather than ``asyncio.sleep``.
EpochClock = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]

#: Reads the decoder's current connection health, or ``None`` when this install
#: has no decoder at all (a first run, or demo mode). A callable rather than a
#: service reference because ``app.state.ingestion`` is assigned *during*
#: startup, after this service has already been constructed and started.
HealthProbe = Callable[[], AdapterHealth | None]

#: Notified after a pass commits, with the events it actually created. The seam
#: the WebSocket's ``activity`` frame hangs off (``docs/API.md`` §4.4).
#: Synchronous by contract, like the sighting worker's own listeners: a
#: broadcaster enqueues and returns, and anything that needs to await is its
#: own task's problem.
ActivityListener = Callable[[Sequence[StoredActivityEvent]], None]


def _offline(state: HealthState) -> bool | None:
    """Map decoder health onto the feed's two-valued question.

    ``degraded`` maps to ``None`` — *no opinion* — on purpose:
    :mod:`flightsite.ingest.health` defines it as "polls are failing, but not
    yet often enough to call the decoder gone", which is precisely the state
    the feed should stay quiet about. It is the first half of the debounce, and
    it costs nothing.
    """
    if state is HealthState.CONNECTED:
        return False
    if state is HealthState.DOWN:
        return True
    return None


@dataclass(frozen=True, slots=True)
class PassResult:
    """What one pass examined and wrote, for tests and logs."""

    examined: int = 0
    #: Events actually created — never merely proposed.
    recorded: int = 0
    milestones: int = 0
    failed: bool = False


class ActivityService:
    """Detects, records and announces everything in the feed (SPEC §54/§55).

    Args:
        database: the application database; writes take its single writer.
        persistence: the sighting worker whose lifecycle seam reports closes.
            ``None`` means "nothing reports closes" — the catch-up scan still
            finds opens, which is what a test or a read-only process wants.
        health: reads the decoder's connection health, or ``None`` for an
            install with no decoder.
        flush_interval_s: how often a pass runs.
        offline_debounce_s: how long a decoder state must hold to be announced.
        scan_limit: sightings examined by one catch-up pass.
        clock: UTC epoch-millisecond source.
        sleep: awaited between passes; injected so tests drive the cadence.
        counters: registry receiving write failures.
    """

    __slots__ = (
        "_announced_offline",
        "_announced_since_ms",
        "_candidate_offline",
        "_candidate_since_ms",
        "_clock",
        "_counters",
        "_debounce_ms",
        "_flush_interval_s",
        "_health",
        "_listeners",
        "_longest",
        "_meta",
        "_milestones",
        "_pending_alerts",
        "_pending_closed",
        "_pending_episodes",
        "_pending_imports",
        "_persistence",
        "_records",
        "_repository",
        "_scan_limit",
        "_sleep",
        "_task",
        "_watermark",
    )

    def __init__(
        self,
        *,
        database: Database,
        persistence: PersistenceWorker | None = None,
        health: HealthProbe | None = None,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        offline_debounce_s: float = DEFAULT_OFFLINE_DEBOUNCE_S,
        scan_limit: int = DEFAULT_SCAN_LIMIT,
        clock: EpochClock = utc_now_ms,
        sleep: Sleeper = asyncio.sleep,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if flush_interval_s <= 0.0:
            raise ValueError("flush_interval_s must be greater than zero")
        if offline_debounce_s < 0.0:
            raise ValueError("offline_debounce_s must not be negative")
        if scan_limit < 1:
            raise ValueError("scan_limit must be at least one")

        self._repository = ActivityRepository(database)
        self._meta = MetaRepository(database)
        self._persistence = persistence
        self._health = health
        self._flush_interval_s = flush_interval_s
        self._debounce_ms = int(offline_debounce_s * MS_PER_SECOND)
        self._scan_limit = scan_limit
        self._clock = clock
        self._sleep = sleep
        self._counters = counters

        self._task: asyncio.Task[None] | None = None
        self._listeners: list[ActivityListener] = []
        self._watermark = 0
        self._records = ReceiverRecords()
        self._longest: LongestSighting | None = None
        self._milestones: set[str] = set()
        self._pending_closed: set[int] = set()
        self._pending_imports: list[ImportOutcome] = []
        self._pending_episodes: list[HealthEpisode] = []
        self._pending_alerts: list[AlertMatchFact] = []
        self._announced_offline: bool | None = None
        self._announced_since_ms = 0
        self._candidate_offline: bool | None = None
        self._candidate_since_ms = 0

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the pass task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def repository(self) -> ActivityRepository:
        """The feed's query layer, which the API reads through."""
        return self._repository

    @property
    def watermark(self) -> int:
        """Highest ``sightings.id`` examined so far. For tests and diagnostics."""
        return self._watermark

    @property
    def milestones(self) -> frozenset[str]:
        """Milestone keys known to be claimed."""
        return frozenset(self._milestones)

    # --------------------------------------------------------------- the seams

    def subscribe(self, listener: ActivityListener) -> None:
        """Register a listener notified with each pass's new events.

        Idempotent per listener object, exactly like the sighting worker's own
        seam: registering the same callable twice registers it once, so a
        broadcaster restarted against a running service cannot end up
        broadcasting in duplicate.
        """
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: ActivityListener) -> None:
        """Remove a listener registered by :meth:`subscribe`."""
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    def record_lifecycle(self, event: SightingLifecycle) -> None:
        """Note the sightings a committed cycle closed.

        Synchronous, allocation-light and never raising: it runs inside the
        persistence worker's cycle (see
        :data:`~flightsite.sightings.worker.SightingLifecycleListener`).

        Only closes are recorded. Opens need no notification at all — the
        catch-up scan finds them by id — and taking them here as well would
        make the seam load-bearing for a fact that is already durable.
        """
        for reference in event.closed:
            self._pending_closed.add(reference.sighting_id)

    async def record_import(self, run: ImportRun) -> None:
        """Note a completed metadata import run, per source (SPEC §27).

        Registered as a :data:`~flightsite.metadata.service.ImportListener`.
        It only records; the events are written by the next pass, on this
        service's own transaction, so a feed failure can never turn a
        successful import into a failed request.
        """
        for result in run.results:
            self._pending_imports.append(
                ImportOutcome(
                    source=result.source,
                    ok=result.ok,
                    finished_ms=run.finished_ms,
                    rows_imported=result.rows_imported,
                    rows_rejected=result.rows_rejected,
                    dataset_version=result.dataset_version,
                    error=result.error,
                )
            )

    def record_alert_matches(self, matches: Sequence[AlertMatchFact]) -> None:
        """Note alert matches the alert engine has just recorded (slice 038).

        Synchronous and memory-only, the same contract
        :meth:`record_lifecycle` has: it is called from
        :class:`flightsite.alerts.engine.AlertEngine`'s cycle, right after that
        cycle's own transaction committed, and it must not be able to fail one.
        The events are written by the next pass, on this service's own
        transaction, so a feed failure can never turn a recorded alert into an
        unrecorded one.

        Only matches the alert tables actually *created* reach here — the two
        partial unique indexes on ``alert_matches`` decide that — so this
        method never sees a duplicate to filter, and the ``dedupe_key`` the
        producer derives is a second, independent guarantee rather than the
        only one.
        """
        self._pending_alerts.extend(matches)

    def _publish(self, events: Sequence[StoredActivityEvent]) -> None:
        """Hand new events to every listener, defensively.

        A listener that raises is logged and skipped: the transaction has
        already committed, so an exception here could only turn a successful
        pass into a failed one and make it rewrite rows that already landed.
        """
        if not events:
            return
        for listener in self._listeners:
            try:
                listener(events)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "activity_listener_failed", error=str(exc), error_type=type(exc).__name__
                )

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Seed the baselines, subscribe, and start the pass task. Idempotent.

        The seeding runs *before* the subscription and before the first pass,
        because every rolling record is measured against it: a baseline taken
        after a pass had already looked would let that pass announce a record
        that was standing before this process existed.
        """
        if self.running:
            return

        self._milestones = set(await self._repository.milestone_keys())
        self._watermark = await self._initial_watermark()
        self._records = await self._repository.receiver_records()
        self._longest = await self._repository.longest_sighting()

        if self._persistence is not None:
            self._persistence.subscribe_lifecycle(self.record_lifecycle)
        self._task = asyncio.create_task(self._loop(), name="flightsite-activity")
        logger.info(
            "activity_started",
            watermark=self._watermark,
            milestones=len(self._milestones),
            flush_interval_s=self._flush_interval_s,
        )

    async def stop(self) -> None:
        """Unsubscribe, stop the task, and run one last pass. Idempotent.

        The final pass is not required for correctness — everything it would
        find is still findable from the watermark on the next boot — but it is
        cheap and it means a clean shutdown leaves the feed current.
        """
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if self._persistence is not None:
            self._persistence.unsubscribe_lifecycle(self.record_lifecycle)

        result = await self.flush()
        logger.info("activity_stopped", recorded=result.recorded)

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._flush_interval_s)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                # The loop outliving a bad pass matters more than the pass: a
                # dead detector would freeze the feed with no indication why.
                logger.warning("activity_pass_error", error=str(exc), error_type=type(exc).__name__)

    async def _initial_watermark(self) -> int:
        """The watermark to start from, initializing it on a first ever boot.

        An absent key means this database has never run the activity service,
        and the honest starting point is *now*: the sightings already in it
        happened before the feed existed, and narrating them would fill a new
        user's feed with a year of history in one second. A key that exists is
        trusted as-is, including the zero a test may have written.
        """
        raw = await self._meta.get(SCAN_WATERMARK_KEY)
        if raw is not None:
            try:
                return int(raw)
            except ValueError:
                logger.warning("activity_watermark_unreadable", value=raw)
        watermark = await self._repository.max_sighting_id()
        await self._meta.set(SCAN_WATERMARK_KEY, str(watermark))
        return watermark

    # ------------------------------------------------------------- one pass

    async def flush(self) -> PassResult:
        """Run one detection pass. Never raises.

        Split out from the loop so tests drive it one pass at a time against a
        hand-driven clock, with no sleeping and no background task.

        Pending work — closes from the seam, import outcomes, debounced health
        episodes — is drained *before* the write and restored if the write
        fails, so a notification that arrives mid-pass is handled by the next
        pass rather than lost to this one.
        """
        now_ms = self._clock()
        self._observe_health(now_ms)

        closed = self._pending_closed
        self._pending_closed = set()
        imports = self._pending_imports
        self._pending_imports = []
        episodes = self._pending_episodes
        self._pending_episodes = []
        alerts = self._pending_alerts
        self._pending_alerts = []

        observations: tuple[SightingObservation, ...] = ()
        try:
            scanned = await self._repository.sighting_ids_after(
                self._watermark, limit=self._scan_limit
            )
            observations = await self._repository.observations(sorted(set(scanned) | closed))
            records = await self._repository.receiver_records()
            batch = await self._detect(
                observations,
                records=records,
                imports=imports,
                episodes=episodes,
                alerts=alerts,
                now_ms=now_ms,
            )
            watermark = max(scanned, default=self._watermark)
            published = await self._repository.record(batch)
            if watermark != self._watermark:
                await self._meta.set(SCAN_WATERMARK_KEY, str(watermark))
        except Exception as exc:
            # The reads are inside the guard as well as the write, because
            # `stop()` runs a final pass unconditionally and a database that
            # failed to migrate is exactly the case where every one of them
            # raises. A shutdown must not turn that into a traceback.
            self._pending_closed |= closed
            self._pending_imports = imports + self._pending_imports
            self._pending_episodes = episodes + self._pending_episodes
            self._pending_alerts = alerts + self._pending_alerts
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning("activity_pass_failed", error=str(exc), error_type=type(exc).__name__)
            return PassResult(examined=len(observations), failed=True)

        # Advanced only after the write: a pass that failed leaves every
        # baseline where it was, so the next one proposes the same events.
        self._watermark = watermark
        self._records = records
        self._longest = best_closed(self._longest, self._closed_observations(observations))
        self._milestones.update(milestone.key for milestone in batch.milestones)
        self._publish(published)
        if published:
            logger.info(
                "activity_recorded",
                events=len(published),
                types=sorted({event.type for event in published}),
            )
        return PassResult(
            examined=len(observations),
            recorded=len(published),
            milestones=len(batch.milestones),
        )

    async def _detect(
        self,
        observations: Sequence[SightingObservation],
        *,
        records: ReceiverRecords,
        imports: Sequence[ImportOutcome],
        episodes: Sequence[HealthEpisode],
        alerts: Sequence[AlertMatchFact],
        now_ms: int,
    ) -> ActivityBatch:
        """Ask every producer what these facts justify, and merge the answers."""
        fresh = [
            observation for observation in observations if observation.sighting_id > self._watermark
        ]
        closed = self._closed_observations(observations)
        batches = [
            first_ever_events(fresh),
            new_type_events(fresh),
            longest_sighting_event(self._longest, closed),
            record_events(self._records, records, now_ms=now_ms),
            health_events(episodes),
            import_events(imports),
            alert_events(alerts),
        ]
        if await self._military_due(observations):
            batches.append(military_milestone(await self._repository.military_first()))
        return merge(batches)

    @staticmethod
    def _closed_observations(
        observations: Sequence[SightingObservation],
    ) -> list[SightingObservation]:
        """The observations that describe a sighting that has actually ended."""
        return [
            observation
            for observation in observations
            if observation.duration_ms is not None and observation.ended_ms is not None
        ]

    async def _military_due(self, observations: Sequence[SightingObservation]) -> bool:
        """Whether this pass should look for the first military sighting ever.

        Two guards, and both are needed. The milestone being unclaimed makes
        the question askable at all; a military airframe actually appearing in
        this pass makes it worth asking, because
        :meth:`~flightsite.activity.repository.ActivityRepository.military_first`
        scans history from the beginning and a receiver that has never heard a
        military aircraft would otherwise pay for that scan every five seconds
        forever.
        """
        if MILESTONE_FIRST_MILITARY in self._milestones:
            return False
        return any(observation.military for observation in observations)

    # ------------------------------------------------------------- health

    def _observe_health(self, now_ms: int) -> None:
        """Fold the decoder's current health into the debounced announcement.

        The first opinion this service forms seeds the announced state
        *silently*: at boot the decoder's state predates the process, so there
        is no transition to report. A receiver that was already down when
        FlightSite started therefore produces no ``receiver_offline`` — but the
        ``receiver_restored`` that ends the outage is still reported, which is
        exactly the question the feed answers ("what happened while I wasn't
        watching?").
        """
        probe = self._health
        health = None if probe is None else probe()
        if health is None:
            return
        offline = _offline(health.state)
        if offline is None:
            return

        if offline is not self._candidate_offline:
            self._candidate_offline = offline
            self._candidate_since_ms = now_ms

        if self._announced_offline is None:
            self._announced_offline = offline
            self._announced_since_ms = now_ms
            return
        if offline is self._announced_offline:
            return
        if now_ms - self._candidate_since_ms < self._debounce_ms:
            return

        self._pending_episodes.append(
            HealthEpisode(
                offline=offline,
                at_ms=self._candidate_since_ms,
                previous_duration_ms=self._candidate_since_ms - self._announced_since_ms,
                error=health.last_error if offline else None,
            )
        )
        self._announced_offline = offline
        self._announced_since_ms = self._candidate_since_ms


__all__ = [
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_OFFLINE_DEBOUNCE_S",
    "ActivityListener",
    "ActivityService",
    "EpochClock",
    "HealthProbe",
    "PassResult",
]
