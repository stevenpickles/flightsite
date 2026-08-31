"""Live domain events and the bounded-queue dispatcher that fans them out.

``docs/ARCHITECTURE.md`` §3.1 puts an **event stream (bounded queues)** between
the live store and everything downstream of it — the sighting engine, alert
evaluation, activity/milestones — and states the rule those queues exist to
enforce: *"A slow consumer can lag or drop to a resync; it cannot stall the
adapter loop."* This module is that seam.

Backpressure policy
-------------------

Each subscriber gets its own bounded :class:`asyncio.Queue`. Publishing is
``put_nowait`` and never awaits, so a consumer that is blocked on a slow
SQLite transaction cannot reach back and stall the ingestion poll. When a
subscriber's queue is full the **oldest** event is discarded to make room for
the newest, the subscriber's ``dropped`` count rises, and its
:attr:`EventSubscription.overflowed` flag is raised.

Dropping the oldest rather than refusing the newest is what makes the flag
recoverable: a consumer that overflowed has an incomplete history but a
current tail, so the documented recovery is exactly the one
``docs/ARCHITECTURE.md`` §3.3 gives the WebSocket broadcaster —
**drop and resync**: read :meth:`~flightsite.live.store.LiveStore.snapshot`,
rebuild from it, then call :meth:`EventSubscription.acknowledge_overflow` and
carry on from the tail. Silently delivering a gap as if it were continuous
would be worse than saying so.

Shedding is never silent: it increments the ``live_events_dropped`` counter
(surfaced by ``/api/v1/health`` and, from slice 042, diagnostics) and logs once
per overflow episode rather than once per dropped event, so an overloaded
consumer produces one warning instead of a log flood.

Event content
-------------

Every event carries the full :class:`~flightsite.live.aircraft.LiveAircraft`
record rather than just an ICAO address. That is what lets a consumer process
a queued event without racing the store back to a value that has since moved
on — and for :class:`AircraftRemoved` it is the only way the record and its
track are still reachable at all, since removal drops the store's reference.
Slice 009 depends on this to persist a track before it disappears.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

import structlog

from flightsite.counters import LIVE_EVENTS_DROPPED, counters
from flightsite.live.aircraft import LiveAircraft

logger = structlog.get_logger(__name__)

#: Events buffered per subscriber before the oldest is shed.
#:
#: ``docs/ARCHITECTURE.md`` §3.3 bounds the live set at roughly 1 000 aircraft;
#: at the 1 Hz decoder poll rate that is about 1 000 events per second, so
#: 4 096 is on the order of four seconds of the busiest realistic stream. That
#: is a generous margin for a consumer batching a SQLite transaction, and small
#: enough that a stalled consumer's buffer stays a rounding error against the
#: <1 GB process budget.
DEFAULT_QUEUE_SIZE: Final = 4096


@dataclass(frozen=True, slots=True)
class LiveEvent:
    """Base class for live-store events.

    ``at`` is a decoder UTC timestamp, never FlightSite's wall clock: for
    appear/update it is the observation's own timestamp, and for stale/remove
    it is :attr:`LiveAircraft.last_seen` — the moment the aircraft was last
    actually heard, which is the instant every downstream lifecycle rule
    (slice 009's sighting closure above all) reasons about.
    """

    aircraft: LiveAircraft
    at: datetime

    @property
    def icao(self) -> str:
        """The ICAO 24-bit address this event concerns."""
        return self.aircraft.icao


@dataclass(frozen=True, slots=True)
class AircraftAppeared(LiveEvent):
    """An ICAO address entered the live set.

    Fires once per entry. An aircraft that is removed and later heard again
    appears again — that is a new entry, and slice 009 turns it into a new
    sighting or a continuation depending on its own closure rules.
    """


@dataclass(frozen=True, slots=True)
class AircraftUpdated(LiveEvent):
    """A live aircraft was observed again.

    ``changed`` names the fields whose value differs from the previous record
    (:data:`~flightsite.live.aircraft.CHANGE_TRACKED_FIELDS`). It is a hint for
    consumers that only care about meaningful transitions — a callsign change,
    a squawk change, crossing into the live set again — and it excludes the
    per-poll bookkeeping that changes every time. An empty set is possible and
    means the decoder re-served an identical view.
    """

    changed: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class AircraftStale(LiveEvent):
    """A live aircraft passed the stale threshold without being heard.

    Fires once per staleness episode: a subsequent observation returns the
    aircraft to ``live``, and only a further silence fires it again.
    """


@dataclass(frozen=True, slots=True)
class AircraftRemoved(LiveEvent):
    """An aircraft left the live set after the removal threshold.

    The attached record is the last one held, including its track. This is a
    consumer's final chance to persist anything about it; the store keeps no
    reference afterwards.

    Removal does not imply a preceding :class:`AircraftStale`. If a sweep is
    delayed long enough that an aircraft crosses both thresholds between
    sweeps, only the removal fires — a consumer must not treat "stale" as a
    guaranteed precondition of "removed".
    """


class EventSubscription:
    """One consumer's bounded view of the event stream.

    Read it with ``async for event in subscription`` in a consumer task, or
    with :meth:`drain` from synchronous code that wants whatever has arrived so
    far without awaiting.
    """

    __slots__ = ("_dispatcher", "_dropped", "_name", "_overflowed", "_queue")

    def __init__(
        self,
        *,
        name: str,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        if maxsize < 1:
            raise ValueError("event queue size must be at least 1")
        self._name = name
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=maxsize)
        self._dropped = 0
        self._overflowed = False
        self._dispatcher = dispatcher

    @property
    def name(self) -> str:
        """Consumer name, used in shedding logs and diagnostics."""
        return self._name

    @property
    def dropped(self) -> int:
        """Events shed from this subscription because the consumer fell behind."""
        return self._dropped

    @property
    def overflowed(self) -> bool:
        """True while unacknowledged shedding has left a gap in this stream.

        A consumer seeing this must resync from
        :meth:`~flightsite.live.store.LiveStore.snapshot` rather than assume
        continuity.
        """
        return self._overflowed

    @property
    def pending(self) -> int:
        """Events currently buffered and not yet consumed."""
        return self._queue.qsize()

    def acknowledge_overflow(self) -> int:
        """Clear the overflow flag after resyncing; return the events shed.

        The ``dropped`` total is cumulative and is not reset — it is a
        diagnostics figure — while the flag is per-episode.
        """
        self._overflowed = False
        return self._dropped

    def deliver(self, event: LiveEvent) -> bool:
        """Offer ``event`` to this subscription without ever blocking.

        Returns ``False`` when an older event had to be shed to make room.
        Called only by :class:`EventDispatcher`.
        """
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._shed()
            self._queue.put_nowait(event)
            return False
        return True

    def _shed(self) -> None:
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover - a full queue cannot be empty
            return
        self._dropped += 1
        counters.increment(LIVE_EVENTS_DROPPED)
        if not self._overflowed:
            self._overflowed = True
            # Once per episode, not once per event: a consumer stalled for a
            # minute would otherwise emit tens of thousands of log lines.
            logger.warning(
                "live_event_queue_overflow",
                consumer=self._name,
                capacity=self._queue.maxsize,
                dropped=self._dropped,
            )

    def drain(self) -> tuple[LiveEvent, ...]:
        """Take every buffered event, oldest first, without awaiting."""
        events: list[LiveEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return tuple(events)

    async def get(self) -> LiveEvent:
        """Await the next event."""
        return await self._queue.get()

    def __aiter__(self) -> AsyncIterator[LiveEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[LiveEvent]:
        while True:
            yield await self.get()

    def close(self) -> None:
        """Detach from the dispatcher. Idempotent."""
        dispatcher, self._dispatcher = self._dispatcher, None
        if dispatcher is not None:
            dispatcher.detach(self)


class EventDispatcher:
    """Fans live events out to bounded per-subscriber queues.

    Publishing is synchronous and non-blocking by construction, which is what
    lets the live store publish from inside a batch application on the
    ingestion task without any risk of yielding to a consumer mid-batch.
    """

    __slots__ = ("_published", "_subscriptions")

    def __init__(self) -> None:
        self._subscriptions: list[EventSubscription] = []
        self._published = 0

    @property
    def subscriber_count(self) -> int:
        """Number of attached subscriptions."""
        return len(self._subscriptions)

    @property
    def published(self) -> int:
        """Events published since this dispatcher was created."""
        return self._published

    def subscribe(
        self, name: str = "anonymous", *, maxsize: int = DEFAULT_QUEUE_SIZE
    ) -> EventSubscription:
        """Attach a new subscriber and return its subscription."""
        subscription = EventSubscription(name=name, maxsize=maxsize, dispatcher=self)
        self._subscriptions.append(subscription)
        return subscription

    def detach(self, subscription: EventSubscription) -> None:
        """Stop delivering to ``subscription``. Idempotent.

        Called by :meth:`EventSubscription.close`; consumers use that rather
        than this.
        """
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    def publish(self, event: LiveEvent) -> None:
        """Deliver ``event`` to every subscriber, shedding rather than waiting."""
        self._published += 1
        for subscription in self._subscriptions:
            subscription.deliver(event)

    def close(self) -> None:
        """Detach every subscription."""
        for subscription in list(self._subscriptions):
            subscription.close()
        self._subscriptions.clear()


__all__ = [
    "DEFAULT_QUEUE_SIZE",
    "AircraftAppeared",
    "AircraftRemoved",
    "AircraftStale",
    "AircraftUpdated",
    "EventDispatcher",
    "EventSubscription",
    "LiveEvent",
]
