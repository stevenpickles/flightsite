"""The live aircraft registry: FlightSite's answer to "what is up there now".

Everything the live map, the live REST endpoints and the WebSocket broadcaster
show comes from this in-memory registry, and from nothing else. That is the
invariant ``docs/ARCHITECTURE.md`` §3.1 states as *"Ingestion is authoritative
for 'now' … no live request or decoder poll ever waits on SQLite"*, and this
module holds it structurally: there is no database import here, no session, no
``await`` inside :meth:`LiveStore.apply`. Persistence is a *consumer* of the
event stream (slice 009), never a dependency of the store.

Lifecycle
---------

Three phases, on the thresholds ``docs/ARCHITECTURE.md`` §3.3 names and
``sighting.stale_s`` / ``sighting.remove_s`` configure (15 s / 60 s by
default):

* **live** — heard within ``stale_s``.
* **stale** — silent for at least ``stale_s``. Still in the live set, still in
  snapshots, still holding its track; the UI shows it as fading rather than
  pretending it is current.
* **removed** — silent for at least ``remove_s``. Dropped from the live set,
  announced with the last record and its track attached.

The third threshold in the settings model, ``sighting.close_s`` (600 s), is
deliberately **not** implemented here. Sighting closure is slice 009's
lifecycle, over persisted sightings rather than live records; what this store
owes it is :attr:`~flightsite.live.aircraft.LiveAircraft.last_seen` on every
record and on every event, which is the instant that rule is measured from.

All three decisions read an injected monotonic clock, never the wall clock.
A Raspberry Pi with no RTC boots with a wildly wrong time and then jumps when
NTP lands; a wall-clock timer would read that jump as every aircraft having
been silent for hours and expire the entire live set at once. The clock is a
constructor argument, so tests drive time by hand rather than sleeping
(``docs/TEST_STRATEGY.md`` §3).

Sweeping
--------

Expiry is time-driven, not update-driven: an aircraft that stops transmitting
produces no update to notice its own absence. :meth:`LiveStore.sweep` performs
one pass and is called by a background task roughly once a second, which is the
"lifecycle timer" of ``docs/ARCHITECTURE.md`` §3.3. Between sweeps a record can
be up to one sweep interval past a threshold with its old ``state``; the
alternative — deriving ``state`` from the clock on every read — would make the
stored state and the reported state two different answers to the same question
and would emit no events. One second of latency on a 15 s threshold is not
worth that.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

import structlog

from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live.aircraft import LiveAircraft, LiveState, appear, mark_stale, merge
from flightsite.live.events import (
    DEFAULT_QUEUE_SIZE,
    AircraftAppeared,
    AircraftRemoved,
    AircraftStale,
    AircraftUpdated,
    EventDispatcher,
    EventSubscription,
)
from flightsite.live.track import DEFAULT_TRACK_CAPACITY

logger = structlog.get_logger(__name__)

#: A source of monotonically increasing seconds. ``time.monotonic`` in
#: production; a hand-driven fake in tests.
MonotonicClock = Callable[[], float]

#: How often the background lifecycle task sweeps. One second is an order of
#: magnitude finer than the 15 s stale threshold and costs one pass over a
#: dictionary of at most a few thousand entries.
DEFAULT_SWEEP_INTERVAL_S: Final = 1.0

#: Defaults mirroring ``SightingTimingSettings``; the app passes the configured
#: values, and these keep the store constructible on its own.
DEFAULT_STALE_S: Final = 15.0
DEFAULT_REMOVE_S: Final = 60.0


@dataclass(frozen=True, slots=True)
class LiveCounts:
    """A cheap summary of the live set, for headers, health and diagnostics.

    ``positioned`` + ``non_positioned`` equals ``total``: an aircraft either
    has a known position or does not. ``stale`` cuts across both — a stale
    aircraft is still counted in whichever of the two it belongs to — because
    "how many aircraft are we tracking" and "how many of those are we still
    hearing" are separate questions.
    """

    total: int = 0
    positioned: int = 0
    non_positioned: int = 0
    stale: int = 0


class LiveStore:
    """The in-memory live aircraft registry.

    Args:
        stale_s: silence after which a live aircraft is marked stale.
        remove_s: silence after which it leaves the live set. Must exceed
            ``stale_s``.
        receiver_location: the receiver's position, used for derived distance
            and bearing. ``None`` — the first-run state, before the setup
            wizard has collected one — simply means no receiver-relative
            fields; nothing else degrades.
        clock: monotonic seconds source, injected for tests.
        track_capacity: per-aircraft cap on retained track points.
        sweep_interval_s: period of the background lifecycle task.
        dispatcher: event dispatcher to publish through; one is created if not
            supplied.
    """

    __slots__ = (
        "_aircraft",
        "_clock",
        "_dispatcher",
        "_receiver_location",
        "_remove_s",
        "_stale_s",
        "_sweep_interval_s",
        "_sweep_task",
        "_track_capacity",
    )

    def __init__(
        self,
        *,
        stale_s: float = DEFAULT_STALE_S,
        remove_s: float = DEFAULT_REMOVE_S,
        receiver_location: Position | None = None,
        clock: MonotonicClock = time.monotonic,
        track_capacity: int = DEFAULT_TRACK_CAPACITY,
        sweep_interval_s: float = DEFAULT_SWEEP_INTERVAL_S,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        if stale_s <= 0.0:
            raise ValueError("stale_s must be greater than zero")
        if remove_s <= stale_s:
            raise ValueError(
                f"remove_s must exceed stale_s (got stale_s={stale_s}, remove_s={remove_s})"
            )
        if sweep_interval_s <= 0.0:
            raise ValueError("sweep_interval_s must be greater than zero")

        self._stale_s = stale_s
        self._remove_s = remove_s
        self._receiver_location = receiver_location
        self._clock = clock
        self._track_capacity = track_capacity
        self._sweep_interval_s = sweep_interval_s
        self._dispatcher = dispatcher if dispatcher is not None else EventDispatcher()
        self._aircraft: dict[str, LiveAircraft] = {}
        self._sweep_task: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- config

    @property
    def stale_s(self) -> float:
        """Silence after which a live aircraft is marked stale."""
        return self._stale_s

    @property
    def remove_s(self) -> float:
        """Silence after which an aircraft leaves the live set."""
        return self._remove_s

    @property
    def receiver_location(self) -> Position | None:
        """The receiver position derived fields are measured from."""
        return self._receiver_location

    def set_receiver_location(self, location: Position | None) -> None:
        """Change the receiver position used for derived distance and bearing.

        Existing records keep the values they were computed with until each is
        observed again — at the 1 Hz poll rate that is under a second for
        anything actually transmitting, and recomputing the whole set here
        would emit a burst of update events describing no new observation.
        The setup wizard (slice 018) is the intended caller.
        """
        self._receiver_location = location

    # ----------------------------------------------------------------- reads

    def get(self, icao: str) -> LiveAircraft | None:
        """The live record for ``icao``, or ``None`` if it is not live."""
        return self._aircraft.get(icao)

    def snapshot(self) -> tuple[LiveAircraft, ...]:
        """Every live aircraft, as an immutable sequence.

        Records are immutable, so a caller may hold this across an ``await``
        without seeing a half-applied batch. This is the resync point a
        consumer returns to after its event queue overflows.
        """
        return tuple(self._aircraft.values())

    def counts(self) -> LiveCounts:
        """Summarize the live set in one pass."""
        positioned = 0
        stale = 0
        for aircraft in self._aircraft.values():
            if aircraft.has_position:
                positioned += 1
            if aircraft.state is LiveState.STALE:
                stale += 1
        total = len(self._aircraft)
        return LiveCounts(
            total=total,
            positioned=positioned,
            non_positioned=total - positioned,
            stale=stale,
        )

    def __len__(self) -> int:
        return len(self._aircraft)

    def __contains__(self, icao: object) -> bool:
        return icao in self._aircraft

    # ------------------------------------------------------------ event seam

    def subscribe(
        self, name: str = "anonymous", *, maxsize: int = DEFAULT_QUEUE_SIZE
    ) -> EventSubscription:
        """Attach a consumer to the live event stream.

        The subscription is a bounded queue: if the consumer falls behind, its
        oldest events are shed and it is told so. See
        :mod:`flightsite.live.events` for the backpressure contract.
        """
        return self._dispatcher.subscribe(name, maxsize=maxsize)

    @property
    def events(self) -> EventDispatcher:
        """The dispatcher live events are published through."""
        return self._dispatcher

    # ----------------------------------------------------------- write path

    def apply(self, batch: AircraftStateBatch) -> None:
        """Apply one decoder batch. This is the ingestion consumer callback.

        Synchronous and allocation-light by design: it runs on the ingestion
        task between polls, and the budget (``docs/ARCHITECTURE.md`` §3.3) is
        a 500-aircraft batch well inside one polling interval.
        """
        self.apply_updates(batch)

    def apply_updates(self, updates: Iterable[AircraftStateUpdate]) -> None:
        """Apply a sequence of updates, publishing an event for each."""
        now = self._clock()
        for update in updates:
            self._apply_update(update, now)

    def _apply_update(self, update: AircraftStateUpdate, now: float) -> None:
        current = self._aircraft.get(update.icao)
        if current is None:
            aircraft = appear(
                update,
                now=now,
                receiver=self._receiver_location,
                track_capacity=self._track_capacity,
            )
            self._aircraft[update.icao] = aircraft
            self._dispatcher.publish(AircraftAppeared(aircraft=aircraft, at=aircraft.last_seen))
            return

        aircraft, changed = merge(current, update, now=now, receiver=self._receiver_location)
        self._aircraft[update.icao] = aircraft
        self._dispatcher.publish(
            AircraftUpdated(aircraft=aircraft, at=aircraft.last_seen, changed=changed)
        )

    # ------------------------------------------------------------- lifecycle

    def sweep(self) -> LiveCounts:
        """Advance every record's lifecycle state once; return the new counts.

        Marks newly silent aircraft stale and removes those past the removal
        threshold, publishing one event per transition. An aircraft that
        crosses both thresholds within a single sweep interval is removed
        without a preceding stale event — the removal is the truthful
        statement, and consumers are documented not to rely on the ordering.
        """
        now = self._clock()
        removed: list[LiveAircraft] = []
        # Snapshot the items: the loop rebinds keys and the removal pass
        # deletes them, and a sweep must not depend on dict-mutation subtleties.
        for icao, aircraft in list(self._aircraft.items()):
            age = aircraft.age_s(now)
            if age >= self._remove_s:
                removed.append(aircraft)
            elif age >= self._stale_s and aircraft.state is not LiveState.STALE:
                stale = mark_stale(aircraft)
                self._aircraft[icao] = stale
                self._dispatcher.publish(AircraftStale(aircraft=stale, at=stale.last_seen))

        for aircraft in removed:
            del self._aircraft[aircraft.icao]
            self._dispatcher.publish(AircraftRemoved(aircraft=aircraft, at=aircraft.last_seen))

        return self.counts()

    @property
    def sweeping(self) -> bool:
        """True while the background lifecycle task is alive."""
        return self._sweep_task is not None and not self._sweep_task.done()

    async def start(self) -> None:
        """Start the background lifecycle sweep. Idempotent."""
        if self.sweeping:
            return
        self._sweep_task = asyncio.create_task(self._sweep_loop(), name="flightsite-live-sweep")
        logger.info(
            "live_store_started",
            stale_s=self._stale_s,
            remove_s=self._remove_s,
            receiver_configured=self._receiver_location is not None,
        )

    async def stop(self) -> None:
        """Stop the sweep task. Idempotent, and safe before start."""
        task, self._sweep_task = self._sweep_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("live_store_stopped", live=len(self._aircraft))

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_interval_s)
            try:
                self.sweep()
            except Exception as exc:  # pragma: no cover - defensive
                # The lifecycle timer outliving a single bad pass matters more
                # than the pass: a dead sweep task would silently freeze the
                # live set with aircraft that never expire.
                logger.warning("live_sweep_error", error=str(exc), error_type=type(exc).__name__)


__all__ = [
    "DEFAULT_REMOVE_S",
    "DEFAULT_STALE_S",
    "DEFAULT_SWEEP_INTERVAL_S",
    "LiveCounts",
    "LiveStore",
    "MonotonicClock",
]
