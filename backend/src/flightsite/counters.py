"""Internal counters registry.

A small, dependency-free registry of named integer counters that any subsystem
can increment. It is safe to call from both synchronous and asynchronous
(asyncio) code because a plain ``threading.Lock`` protects a short, non-blocking
critical section — there is never an ``await`` while the lock is held, so it
cannot deadlock or stall the event loop.

Counter names are predeclared: later slices (ingestion, persistence,
enrichment, WebSocket broadcaster) increment these as they land. This slice
only exposes the registry and its zeroed snapshot via the health payload.
"""

from __future__ import annotations

import threading
from typing import Final

#: Live domain events shed because an event-stream subscriber fell behind
#: (``flightsite.live.events``). Shedding is the documented backpressure
#: response — a slow consumer must never stall ingestion — so it has to be
#: visible rather than silent.
LIVE_EVENTS_DROPPED: Final = "live_events_dropped"

KNOWN_COUNTERS: Final[tuple[str, ...]] = (
    "ingestion_failures",
    "db_errors",
    "enrichment_failures",
    "ws_disconnects",
    LIVE_EVENTS_DROPPED,
)


class CounterRegistry:
    """Thread-safe / asyncio-safe registry of named integer counters."""

    def __init__(self, names: tuple[str, ...] = KNOWN_COUNTERS) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = dict.fromkeys(names, 0)

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a predeclared counter by ``amount`` (default 1).

        Raises ``KeyError`` if ``name`` was not predeclared, to catch typos
        early rather than silently creating unbounded counter names.
        """
        with self._lock:
            if name not in self._counters:
                raise KeyError(f"Unknown counter: {name!r}")
            self._counters[name] += amount

    def snapshot(self) -> dict[str, int]:
        """Return an independent copy of the current counter values."""
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        """Zero every predeclared counter, keeping the declared names.

        The module-level :data:`counters` registry is process-global, so the
        test suite resets it between tests to keep one test's failures out of
        another's assertions.
        """
        with self._lock:
            self._counters = dict.fromkeys(self._counters, 0)


counters = CounterRegistry()
