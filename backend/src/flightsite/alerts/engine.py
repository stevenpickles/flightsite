"""The incremental alert engine: live updates in, matches and their effects out.

Where this runs, and what it is allowed to touch
------------------------------------------------

The engine is a consumer of the live event stream, exactly like the metadata
cache, the WebSocket broadcaster and the persistence worker
(``docs/ARCHITECTURE.md`` §3.1 names *"alert evaluation"* among them). It holds
a bounded subscription and does its work on its own task, so the coupling runs
one way: the live store publishes and moves on.

Evaluation itself reads **only memory**, and that is structural rather than a
convention. A subject (:class:`~flightsite.alerts.model.AlertSubject`) is
assembled from four in-memory sources —

* the live record (:class:`~flightsite.live.store.LiveStore`),
* the resolved metadata view and the resident rarity counters
  (:class:`~flightsite.metadata.cache.MetadataCache`, which slice 021 built for
  exactly this),
* the watchlist match index
  (:class:`~flightsite.watchlists.matcher.WatchlistMatcher`),
* the persistence worker's open accumulator, for the sighting's ids and the
  severity already standing on it

— and every one of those is a dict lookup with no ``await``. There is no code
path from evaluation to SQLite, so the ≤50 ms/500-aircraft budget is a property
of arithmetic rather than of a database being fast today.

Incremental, and what that actually means
------------------------------------------

A cycle evaluates the aircraft **this cycle heard about**, never the live set:
the union of the addresses named by the drained events and a small
*re-evaluation* set (below). At a 1 Hz decoder poll those two sets are similar
in size, and that is fine — the property that matters is that a burst of ten
updates for one aircraft costs one evaluation, and that evaluating one aircraft
never costs a pass over the other 499. Cost is ``O(changed * rules)``.

The re-evaluation set is the aircraft whose metadata the cache had not resolved
when they were last looked at. Every condition is a requirement and an unknown
input fails it (:mod:`flightsite.alerts.evaluator`), so a military aircraft
must not be decided against on the half-second before its classification
arrives. Keeping the set explicit rather than re-scanning the live set is what
keeps "no full rescan per update" true even for that repair.

The match lifecycle
-------------------

SPEC §48: *"notify once per sighting per rule ... a newly matched
higher-priority condition may create another notification."* Three rules, and
each one is enforced in exactly one place:

1. **Once per sighting per rule.** The engine holds, per live aircraft, the set
   of dedupe keys already fired within its *current* sighting; a proposal whose
   key is in that set is dropped without a write. The set is reset when the
   aircraft's sighting id changes, because a new sighting is a new dedupe
   scope, and it is rehydrated at start from ``alert_matches`` for the
   sightings a previous process left open. The two partial unique indexes are
   the same statement in storage — so a lost in-memory set costs a wasted
   insert attempt, never a duplicate row.
2. **The allowed extra.** A *different* rule matching later is a different key
   and therefore a new match. When its severity outranks the one already
   standing on the sighting it also raises ``sightings.max_alert_severity`` and
   emits an ``alert_severity_upgraded`` sighting event — which is the
   distinction SPEC §48 draws, recorded rather than left for the notification
   layer to re-derive. A built-in that escalates does the same thing through a
   different ``builtin_key`` (``emergency_7600`` then ``emergency_7700``).
3. **Nothing is announced twice.** Only the rows
   :meth:`~flightsite.alerts.repository.AlertRepository.record_matches`
   actually *created* produce downstream effects. A row that lost a conflict
   was already recorded by someone, so re-announcing it would be a second
   notification for one match.

Persistence, in two halves
---------------------------

An alert produces writes to two different owners, and each rides its own
transaction:

* ``alert_matches`` is this package's table and is written on this engine's own
  writer session — the shape :mod:`flightsite.analytics.service` and
  :mod:`flightsite.activity.service` already take, so an alert bug can delay
  the alert and nothing else.
* ``sightings.max_alert_severity`` is a column of the *sighting* row, so it is
  applied to the persistence worker's accumulator
  (:meth:`~flightsite.sightings.worker.PersistenceWorker.apply_alert_severity`)
  and written by the flush that writes the rest of that row, together with its
  ``alert_matched`` / ``alert_severity_upgraded`` sighting event. One fact, one
  owner, one transaction.

A match whose sighting the worker has not committed yet — the first second or
so of a new aircraft — has no ids to write with. It is *held*, not dropped: the
proposal stays pending on that aircraft and the next cycle writes it, which is
the same write-behind bargain every other consumer of the worker makes.

Degradation
-----------

Every failure mode ends in an alert being later, and none of them ends anywhere
else. A failed write counts ``db_errors``, keeps its pending matches and
retries next cycle; an event-queue overflow resyncs from the live snapshot and
carries on; a listener that raises is logged and skipped. Ingestion is never
affected, because nothing on the decoder path can reach this task.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

import structlog

from flightsite.activity.facts import AlertMatchFact
from flightsite.alerts.evaluator import evaluate
from flightsite.alerts.model import (
    AlertSubject,
    CompiledRule,
    InterestingState,
    MatchProposal,
)
from flightsite.alerts.repository import AlertRepository, NewAlertMatch
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.classification.model import Classification
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.live import (
    AircraftRemoved,
    AircraftStale,
    EventSubscription,
    LiveEvent,
    LiveStore,
)
from flightsite.metadata.cache import MetadataCache
from flightsite.sightings.worker import PersistenceWorker
from flightsite.watchlists.matcher import WatchlistMatcher

logger = structlog.get_logger(__name__)

#: Events buffered for the engine before the live store sheds the oldest.
#:
#: Sized like the metadata cache's rather than the persistence worker's:
#: recovery from a shed event is trivially cheap here — the engine resyncs
#: against the live snapshot, which is the set it wants to evaluate anyway — so
#: it needs no headroom for a stalled transaction.
DEFAULT_QUEUE_SIZE: Final = 2048

#: A source of UTC epoch milliseconds, injected so tests stamp matches from a
#: hand-driven clock rather than the wall clock.
EpochClock = Callable[[], int]

#: Notified with the matches one committed cycle created. The seam the activity
#: feed hangs off (:meth:`flightsite.activity.service.ActivityService.
#: record_alert_matches`), and the seam slice 040's notifications will use.
#:
#: Synchronous by contract, like the sighting worker's own listeners: it runs
#: inside this engine's cycle, so it may only touch memory.
AlertListener = Callable[[Sequence[AlertMatchFact]], None]

#: The classification an aircraft the metadata cache has not reached yet gets:
#: complete, and asserting nothing. Shared rather than constructed per subject
#: because it is immutable and a cycle builds up to 500 subjects.
_UNKNOWN_CLASSIFICATION: Final = Classification()


@dataclass(slots=True)
class AircraftAlertState:
    """What the engine remembers about one live aircraft's alerts.

    Scoped to the aircraft's *current sighting*: :attr:`sighting_id` is what
    the engine compares to decide whether :attr:`fired` still applies, because
    the dedupe scope SPEC §48 defines is the sighting, not the airframe. An
    aircraft that leaves and returns inside the closure gap continues the same
    sighting and therefore keeps its fired set; one that returns after it
    starts fresh.
    """

    #: The sighting these keys belong to, or ``None`` while the persistence
    #: worker has not committed one yet.
    sighting_id: int | None = None
    #: Dedupe keys already recorded in this sighting, and the severity each
    #: fired at. Membership is the once-per-sighting-per-rule check.
    fired: dict[str, AlertSeverity] = field(default_factory=dict)
    #: Proposals that matched but had no sighting id to be written with, or
    #: whose write failed. Keyed so a repeat while pending cannot enqueue twice.
    pending: dict[str, MatchProposal] = field(default_factory=dict)
    #: The §3.3 ``interesting`` block: what is matching *right now*.
    interesting: InterestingState | None = None
    #: True while the metadata cache had not resolved this airframe at the last
    #: evaluation, which is what puts it in the re-evaluation set.
    awaiting_metadata: bool = True


@dataclass(frozen=True, slots=True)
class CycleResult:
    """What one engine cycle did, for tests and logs."""

    events: int = 0
    evaluated: int = 0
    #: Proposals held because their sighting had no id yet, or a write failed.
    pending: int = 0
    #: ``alert_matches`` rows this cycle actually created.
    recorded: int = 0
    #: Matches that raised their sighting's ``max_alert_severity``.
    upgraded: int = 0
    resynced: bool = False
    failed: bool = False


def subject_for(
    icao: str,
    *,
    live: LiveStore,
    metadata: MetadataCache,
    watchlists: WatchlistMatcher,
    persistence: PersistenceWorker,
    now_ms: int,
) -> AlertSubject | None:
    """Assemble one aircraft's evaluation subject from memory alone.

    ``None`` when the aircraft is no longer in the live set — an ordinary
    outcome for an address named by an event this cycle drained after the sweep
    removed it.

    Two figures deserve their reasoning spelled out, because both are rarity
    (SPEC §44) and both come from counters that trail live state:

    ``sightings_here`` is the airframe's lifetime sighting count **including
    the sighting happening now**. The cache's own figure is the count as of
    population, and population precedes the current sighting's ``INSERT``: the
    cache resolves on the appear event it is woken by, while the persistence
    worker opens the sighting on its next one-second cycle and increments
    ``aircraft.sighting_count`` there (021 documents this as "the figure can
    trail the current sighting by one"). Adding one therefore produces exactly
    the value ``aircraft.sighting_count`` will hold a moment later — which is
    what makes a ``rare_aircraft`` condition and ``GET
    /api/v1/analytics/rarity`` answer "rare here" identically, and what makes
    ``max_sightings=1`` mean *never seen before*. An airframe with no persisted
    row at all reads ``None`` from the cache and lands on 1, which is the same
    answer by the same arithmetic.

    ``type_aircraft_here`` is distinct airframes of this type ever recorded,
    floored at one because *this* aircraft is one of them: the resident type
    map is rebuilt when a metadata import completes rather than continuously,
    so a type first heard since the last import legitimately reads zero, and a
    floor of one is the truthful minimum rather than a guess.
    """
    record = live.get(icao)
    if record is None:
        return None
    view = metadata.get(icao)
    resolved = None if view is None else view.metadata
    active = persistence.sighting_for(icao)
    type_count = None if view is None else view.type_count
    return AlertSubject(
        icao=icao,
        at_ms=now_ms,
        sighting_id=None if active is None else active.sighting_id,
        aircraft_id=None if active is None else active.aircraft_id,
        squawk=record.squawk,
        distance_nm=record.distance_nm,
        altitude_ft=record.altitude_ft,
        ground_state=record.ground_state,
        classification=view.classification if view is not None else _UNKNOWN_CLASSIFICATION,
        type_code=None if resolved is None else resolved.type_code,
        model=None if resolved is None else resolved.model,
        watchlists=watchlists.matches(icao),
        sightings_here=1 if view is None else (view.sighting_count or 0) + 1,
        type_aircraft_here=None if type_count is None else max(1, type_count),
        metadata_resolved=view is not None,
    )


class AlertEngine:
    """Evaluates rules against live updates and records what matched.

    Args:
        database: the application database; matches are written on its single
            writer.
        live: the live store whose event stream drives evaluation.
        metadata: the metadata & rarity cache (slice 021).
        watchlists: the in-memory watchlist match index (slice 037).
        persistence: the sighting worker, for the open sighting's ids and for
            the ``max_alert_severity`` apply seam.
        alert_radius_nm: the configured alert radius, or ``None`` for unlimited
            (SPEC §66). Read through a callable by
            :class:`~flightsite.alerts.service.AlertService`, because ``PUT
            /api/internal/config`` replaces the settings on a running app.
        queue_size: bounded event-queue capacity.
        clock: UTC epoch-millisecond source, injected for tests.
        counters: registry receiving ``db_errors`` when a cycle's write fails.
    """

    __slots__ = (
        "_adopted",
        "_alert_radius_nm",
        "_clock",
        "_counters",
        "_idle",
        "_listeners",
        "_live",
        "_metadata",
        "_persistence",
        "_queue_size",
        "_repository",
        "_rules",
        "_states",
        "_subscription",
        "_task",
        "_watchlists",
    )

    def __init__(
        self,
        *,
        database: Database,
        live: LiveStore,
        metadata: MetadataCache,
        watchlists: WatchlistMatcher,
        persistence: PersistenceWorker,
        alert_radius_nm: float | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        clock: EpochClock = utc_now_ms,
        counters: CounterRegistry = default_counters,
    ) -> None:
        self._repository = AlertRepository(database)
        self._live = live
        self._metadata = metadata
        self._watchlists = watchlists
        self._persistence = persistence
        self._alert_radius_nm = alert_radius_nm
        self._queue_size = queue_size
        self._clock = clock
        self._counters = counters

        self._rules: tuple[CompiledRule, ...] = ()
        self._states: dict[str, AircraftAlertState] = {}
        self._adopted: dict[int, dict[str, AlertSeverity]] = {}
        self._listeners: list[AlertListener] = []
        self._subscription: EventSubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the evaluation task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def rules(self) -> tuple[CompiledRule, ...]:
        """The compiled rule set currently in force. Read-only; tests inspect it."""
        return self._rules

    @property
    def tracked(self) -> int:
        """Live aircraft the engine currently holds alert state for."""
        return len(self._states)

    def interesting(self, icao: str) -> InterestingState | None:
        """The ``docs/API.md`` §3.3 ``interesting`` block for ``icao``.

        Pure memory: no ``await``, no session, no I/O — the same shape as
        :meth:`~flightsite.metadata.cache.MetadataCache.get`, which is what
        lets :func:`flightsite.api.serializers.aircraft_payload` carry the
        block with zero hot-path work.

        ``None`` means *nothing is matching right now*, which is what
        ``docs/API.md`` §3.3 defines the null block as. An aircraft that
        matched earlier in this sighting and no longer does — it flew outside a
        rule's distance window, or its emergency squawk cleared — reads
        ``None`` again, and the record of what happened lives where records
        belong: ``sightings.max_alert_severity``, the sighting's own timeline,
        and the alert history.
        """
        state = self._states.get(icao)
        return None if state is None else state.interesting

    # --------------------------------------------------------------- the seams

    def subscribe(self, listener: AlertListener) -> None:
        """Register a listener notified with each cycle's created matches.

        Idempotent per listener object, exactly like the sighting worker's and
        the activity service's own seams: registering the same callable twice
        registers it once, so a service restarted against a running engine
        cannot end up notified in duplicate.
        """
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: AlertListener) -> None:
        """Remove a listener registered by :meth:`subscribe`."""
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    def _publish(self, matches: Sequence[AlertMatchFact]) -> None:
        """Hand created matches to every listener, defensively.

        A listener that raises is logged and skipped: the transaction has
        already committed at this point, so an exception here could only turn a
        successful cycle into a failed one and make it rewrite rows that
        already landed.
        """
        if not matches:
            return
        for listener in self._listeners:
            try:
                listener(matches)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "alert_listener_failed", error=str(exc), error_type=type(exc).__name__
                )

    # ---------------------------------------------------------- configuration

    def set_rules(self, rules: Iterable[CompiledRule]) -> None:
        """Replace the rule set in force.

        A full replace rather than an incremental edit, for the reason
        :meth:`flightsite.watchlists.matcher.WatchlistMatcher.reload` gives: at
        the scale rules are configured (dozens, through a settings-style UI)
        rebuilding is free, and an incremental path would have to reason about
        a rename changing what a condition resolves to.

        What is deliberately **not** reset is the per-sighting fired set. A
        rule edited mid-sighting keeps its id, so it keeps its dedupe identity
        — editing a rule must not make it alert again on aircraft it has
        already alerted on, which is exactly what SPEC §48's "once per sighting
        per rule" says. Deleting a rule removes its matches with it
        (:meth:`~flightsite.alerts.repository.AlertRepository.delete_rule`), so
        a re-created rule gets a new id and a clean scope.
        """
        self._rules = tuple(rules)

    def set_alert_radius(self, alert_radius_nm: float | None) -> None:
        """Update the configured alert radius (SPEC §66)."""
        self._alert_radius_nm = alert_radius_nm

    def adopt_open_matches(self, keys: dict[int, dict[str, AlertSeverity]]) -> None:
        """Seed the dedupe state from matches already recorded on open sightings.

        Called once at start with
        :meth:`~flightsite.alerts.repository.AlertRepository.
        open_sighting_match_keys`. Without it, a restart mid-sighting would
        re-propose every match that sighting had already recorded: the unique
        indexes would refuse the rows, so nothing would be duplicated, but the
        engine would pay a failed insert per rule per cycle for the rest of
        that sighting and would announce nothing — a silent waste rather than a
        bug, and worth one query at boot to avoid.

        Keyed by sighting rather than by aircraft, because the engine does not
        yet know which aircraft is live: :meth:`_state_for` claims the right
        entry the first time each aircraft is evaluated.
        """
        self._adopted = dict(keys)

    # -------------------------------------------------------------- lifecycle

    def attach(self) -> None:
        """Take the live subscription without starting the evaluation task.

        :meth:`start` is this plus the task, and the two are separable on
        purpose. This engine's loop is *event-driven* — it wakes the instant an
        event is published — so a test that both ran the loop and called
        :meth:`process_pending` would be racing itself for the same queue. The
        persistence worker gets the same determinism for free from its
        tick-driven loop; this one has to be given it.

        Idempotent: an engine that already holds a subscription keeps it, so a
        :meth:`start` after an :meth:`attach` does not open a second one.
        """
        if self._subscription is None:
            self._subscription = self._live.subscribe("alerts", maxsize=self._queue_size)

    async def start(self) -> None:
        """Subscribe and start the evaluation task. Idempotent."""
        if self.running:
            return
        self.attach()
        self._task = asyncio.create_task(self._loop(), name="flightsite-alerts")
        logger.info("alert_engine_started", rules=len(self._rules))

    async def stop(self) -> None:
        """Stop the task and release the subscription. Idempotent.

        No final cycle: a match still pending at shutdown belongs to a sighting
        that is still open, and the next process re-evaluates the aircraft the
        moment it hears it again. Forcing a write here would race the
        persistence worker's own final flush for the sighting row those ids
        point at.
        """
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()
        self._idle.set()
        logger.info("alert_engine_stopped", tracked=len(self._states))

    async def wait_idle(self) -> None:
        """Wait until the evaluation task finishes the cycle it is in.

        Tests await this rather than sleeping, the same way
        :meth:`flightsite.metadata.cache.MetadataCache.wait_idle` is used, so a
        latency measurement measures the engine rather than a poll interval.
        """
        await self._idle.wait()

    async def _loop(self) -> None:
        subscription = self._subscription
        if subscription is None:  # pragma: no cover - start() always sets one
            return
        while True:
            event = await subscription.get()
            self._idle.clear()
            try:
                await self._cycle((event, *subscription.drain()))
            except asyncio.CancelledError:  # pragma: no cover - see below
                # A shutdown almost always cancels this task while it is
                # awaiting the next event above, not mid-cycle. The arm is
                # still needed: without it the `except Exception` below would
                # swallow a cancellation that *did* land inside a cycle and
                # turn `stop()` into a hang.
                raise
            except Exception as exc:  # pragma: no cover - defensive
                # The loop outliving a bad cycle matters more than the cycle: a
                # dead evaluator would stop alerting with no indication why.
                logger.warning("alert_cycle_error", error=str(exc), error_type=type(exc).__name__)
            finally:
                if subscription.pending == 0:
                    self._idle.set()

    # -------------------------------------------------------------- one cycle

    async def process_pending(self) -> CycleResult:
        """Drain whatever has arrived and run one evaluation cycle.

        Split out from the loop so tests drive it deterministically: no
        sleeping, no waiting on a background task, one call per simulated
        instant — the same affordance
        :meth:`flightsite.sightings.worker.PersistenceWorker.process_pending`
        provides.
        """
        subscription = self._subscription
        if subscription is None:
            return CycleResult()
        return await self._cycle(subscription.drain())

    async def _cycle(self, events: Sequence[LiveEvent]) -> CycleResult:
        now_ms = self._clock()
        subscription = self._subscription
        resynced = subscription is not None and subscription.overflowed

        if resynced and subscription is not None:
            wanted = self._resync(subscription)
        else:
            wanted = self._collect(events)

        proposals = self._evaluate(wanted, now_ms)
        result = await self._record(proposals, now_ms)
        return CycleResult(
            events=len(events),
            evaluated=len(wanted),
            pending=result.pending,
            recorded=result.recorded,
            upgraded=result.upgraded,
            resynced=resynced,
            failed=result.failed,
        )

    def _collect(self, events: Sequence[LiveEvent]) -> list[str]:
        """Addresses to evaluate this cycle: what changed, plus what is owed.

        Removals are applied here rather than deferred: dropping the state is
        what bounds this engine's memory to the live set, and an aircraft that
        left before its appear was evaluated must not be evaluated at all.

        ``AircraftStale`` is skipped (issue #138). It announces *silence* — no
        new position, altitude, squawk, callsign or metadata — so every
        condition would be evaluated against exactly the inputs that produced
        the last answer, and would reach exactly that answer again. Before
        slice 062 the event fired minutes late and rarely enough for the wasted
        pass not to show; now it fires on schedule for every aircraft that goes
        quiet for fifteen seconds, which on a marginal-coverage receiver is a
        large fraction of the live set. An aircraft that genuinely still owes
        an evaluation — one whose metadata had not resolved, or whose match is
        pending — is picked up by the repair pass below regardless, so nothing
        is lost by not asking here.
        """
        wanted: dict[str, None] = {}
        for event in events:
            if isinstance(event, AircraftRemoved):
                self._states.pop(event.icao, None)
                wanted.pop(event.icao, None)
            elif isinstance(event, AircraftStale):
                continue
            else:
                wanted[event.icao] = None
        # The repair pass: aircraft whose metadata was still unresolved when
        # they were last looked at. See the module docstring.
        for icao, state in self._states.items():
            if state.awaiting_metadata or state.pending:
                wanted.setdefault(icao, None)
        return list(wanted)

    def _resync(self, subscription: EventSubscription) -> list[str]:
        """Rebuild from the live snapshot after the event queue overflowed.

        Shed events may have hidden a removal, so the snapshot — not the event
        history — decides what the engine should hold; and they may equally
        have hidden the update that would have triggered a match, so everything
        live is re-evaluated. Both are cheap: the snapshot *is* the set a cycle
        would evaluate at full rate anyway.
        """
        live = {record.icao for record in self._live.snapshot()}
        for icao in [icao for icao in self._states if icao not in live]:
            del self._states[icao]
        dropped = subscription.acknowledge_overflow()
        logger.warning("alert_engine_resynced_from_snapshot", dropped=dropped, live=len(live))
        return sorted(live)

    def _evaluate(self, icaos: Sequence[str], now_ms: int) -> list[tuple[str, MatchProposal]]:
        """Evaluate each address and return the matches owed a write.

        Pure memory and no ``await``: this is the whole of the acceptance
        criterion's "full evaluation cycle", and it is deliberately separable
        from the write leg so the perf test measures evaluation rather than
        SQLite.
        """
        owed: list[tuple[str, MatchProposal]] = []
        for icao in icaos:
            subject = subject_for(
                icao,
                live=self._live,
                metadata=self._metadata,
                watchlists=self._watchlists,
                persistence=self._persistence,
                now_ms=now_ms,
            )
            if subject is None:  # pragma: no cover - see below
                # An address with no live record. Unreachable as the cycle
                # stands — `_collect` drops an aircraft whose removal it
                # drained, and `_resync` takes its addresses from the snapshot
                # — but the guard is what keeps that a *local* property rather
                # than a coupling between three methods, and it is what a
                # future `_evaluate` that awaited would need.
                self._states.pop(icao, None)
                continue
            state = self._state_for(icao, subject)
            proposals = evaluate(subject, self._rules, alert_radius_nm=self._alert_radius_nm)
            state.interesting = _interesting(proposals)
            for proposal in proposals:
                if proposal.key not in state.fired:
                    state.pending.setdefault(proposal.key, proposal)
            owed.extend((icao, proposal) for proposal in state.pending.values())
        return owed

    def _state_for(self, icao: str, subject: AlertSubject) -> AircraftAlertState:
        """This aircraft's alert state, scoped to its *current* sighting.

        A sighting id that differs from the one the state was built for resets
        the fired set: the dedupe scope SPEC §48 defines is the sighting, so a
        second sighting of the same airframe alerts again — which is the whole
        point of "once per sighting" rather than "once per aircraft". The id
        arriving for the first time (``None`` → a number) adopts whatever a
        previous process had already recorded on that sighting, so a restart
        mid-sighting does not re-propose what is already there.
        """
        state = self._states.get(icao)
        if state is None:
            state = AircraftAlertState()
            self._states[icao] = state
        sighting_id = subject.sighting_id
        if sighting_id != state.sighting_id:
            state.fired = (
                dict(self._adopted.get(sighting_id, {})) if sighting_id is not None else {}
            )
            state.sighting_id = sighting_id
        state.awaiting_metadata = not subject.metadata_resolved
        return state

    # --------------------------------------------------------- the write leg

    async def _record(self, owed: Sequence[tuple[str, MatchProposal]], now_ms: int) -> CycleResult:
        """Write this cycle's new matches and apply what each one implies.

        Only proposals whose sighting the persistence worker has committed can
        be written; the rest stay pending on their aircraft and the next cycle
        tries again. Ordering within the write is highest severity first, so
        that when several rules match at once the sighting's
        ``max_alert_severity`` reaches its final value in one step and emits
        one ``alert_matched`` event rather than a staircase of upgrades for a
        single instant.
        """
        writable: list[tuple[str, MatchProposal, NewAlertMatch]] = []
        held = 0
        for icao, proposal in owed:
            active = self._persistence.sighting_for(icao)
            sighting_id = None if active is None else active.sighting_id
            aircraft_id = None if active is None else active.aircraft_id
            if sighting_id is None or aircraft_id is None:
                held += 1
                continue
            writable.append(
                (
                    icao,
                    proposal,
                    NewAlertMatch(
                        sighting_id=sighting_id,
                        aircraft_id=aircraft_id,
                        matched_ms=now_ms,
                        severity=proposal.severity,
                        reason=proposal.reason,
                        rule_id=proposal.rule_id,
                        builtin_key=proposal.builtin_key,
                    ),
                )
            )
        if not writable:
            return CycleResult(pending=held)

        writable.sort(key=lambda item: -item[1].severity.rank)
        try:
            created = await self._repository.record_matches([match for _, _, match in writable])
        except Exception as exc:
            # The pending proposals are untouched, so the next cycle retries
            # the whole batch. Ingestion and the live picture are unaffected.
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "alert_write_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                matches=len(writable),
            )
            return CycleResult(pending=held + len(writable), failed=True)

        # A conflict means the row was already there, which still means the key
        # has fired within this sighting — so every attempted key leaves the
        # pending set, and only the created ones have downstream effects.
        facts: list[AlertMatchFact] = []
        upgraded = 0
        for (icao, proposal, match), match_id in zip(writable, created, strict=True):
            state = self._states.get(icao)
            if state is not None:
                state.pending.pop(proposal.key, None)
                state.fired[proposal.key] = proposal.severity
            if match_id is None:
                continue
            if self._persistence.apply_alert_severity(
                icao, proposal.severity.value, proposal.reason, at_ms=now_ms
            ):
                upgraded += 1
            facts.append(self._fact(match_id, icao, proposal, match))
        self._publish(facts)
        if facts:
            logger.info(
                "alerts_matched",
                matches=len(facts),
                upgraded=upgraded,
                severities=sorted({fact.severity for fact in facts}),
            )
        return CycleResult(pending=held, recorded=len(facts), upgraded=upgraded)

    def _fact(
        self, match_id: int, icao: str, proposal: MatchProposal, match: NewAlertMatch
    ) -> AlertMatchFact:
        """The activity fact for one created match, read from memory.

        Everything SPEC §48 asks a notification to carry — callsign, tail,
        type, classification, altitude, distance, reason — is taken from the
        live record and the metadata view *now*, at the instant the match was
        recorded, rather than queried back later: those are the values the
        aircraft actually had when it matched, and a later read would be a
        second opinion about a moment that has passed.
        """
        record = self._live.get(icao)
        view = self._metadata.get(icao)
        resolved = None if view is None else view.metadata
        classification = _UNKNOWN_CLASSIFICATION if view is None else view.classification
        rule = next(
            (compiled.rule for compiled in self._rules if compiled.rule.id == proposal.rule_id),
            None,
        )
        return AlertMatchFact(
            match_id=match_id,
            matched_ms=match.matched_ms,
            severity=proposal.severity.value,
            reason=proposal.reason,
            aircraft_id=match.aircraft_id,
            sighting_id=match.sighting_id,
            icao24=icao,
            rule_id=proposal.rule_id,
            rule_name=None if rule is None else rule.name,
            builtin_key=proposal.builtin_key,
            squawk=None if record is None else record.squawk,
            callsign=None if record is None else record.callsign,
            registration=None if resolved is None else resolved.registration,
            type_code=None if resolved is None else resolved.type_code,
            model=None if resolved is None else resolved.model,
            operator=None if resolved is None else resolved.operator_name,
            distance_nm=None if record is None else record.distance_nm,
            altitude_ft=None if record is None else record.altitude_ft,
            military=classification.military,
            government=classification.government,
            law_enforcement=classification.law_enforcement,
        )


def _interesting(proposals: Sequence[MatchProposal]) -> InterestingState | None:
    """The §3.3 ``interesting`` block for a set of current matches, or ``None``.

    The severity is the highest matching one and the reasons are every match's,
    in the order :func:`~flightsite.alerts.evaluator.evaluate` produced them
    (severity first) — so a client showing one line shows the most important
    one without having to sort.
    """
    if not proposals:
        return None
    # By rank, never by the enum's string value: `max` over a `StrEnum` would
    # compare "critical" against "info" alphabetically and answer "info".
    return InterestingState(
        severity=max((proposal.severity for proposal in proposals), key=lambda s: s.rank),
        reasons=tuple(proposal.reason for proposal in proposals),
    )


__all__ = [
    "DEFAULT_QUEUE_SIZE",
    "AircraftAlertState",
    "AlertEngine",
    "AlertListener",
    "CycleResult",
    "EpochClock",
    "subject_for",
]
