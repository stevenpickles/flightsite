"""The load itself: the real pipeline, wired as production wires it, at 500 aircraft.

What this is
------------

:class:`Workload` builds the actual application — :func:`flightsite.app.create_app`,
its real database, live store, persistence worker, alert engine, WebSocket
broadcaster and HTTP surface — and drives 500 aircraft of deterministic demo
traffic (SPEC §76, slice 011) through it one 1 Hz tick at a time. Nothing here
is a mock or a stand-in: every component is the object the container runs, and
every measurement is of production code doing production work.

Why the components are hand-driven
----------------------------------

The live sweep, the persistence cycle, the alert evaluation and the broadcast
tick each normally run on their own ~1 Hz background task. This harness stands
them all down (``NEVER_S`` intervals, the same technique
``tests/api/conftest.py`` uses) and calls their tick methods itself, in the
order the pipeline runs them. Two reasons, and both are about honesty:

* **Attribution.** A background task that fires whenever the loop happens to
  schedule it puts its cost into whichever measurement is running at the time.
  Driving each stage explicitly means ``persistence_ms`` is the persistence
  cycle and nothing else.
* **The duty cycle is the real gate.** SPEC §85's "ingestion keeps up" is not a
  statement about one stage; it is the claim that *everything a tick must do*
  fits inside the poll interval. Summing explicitly driven stages gives that
  number directly (:attr:`TickCost.total_ms`), where sampling concurrent tasks
  would only ever give a lower bound.

The decoder poll itself is deliberately excluded. A load harness measures this
pipeline, not the network round trip to a decoder that is not under test;
``live.apply`` is the exact callback :func:`flightsite.app._start_ingestion`
registers as ingestion's sole consumer, so feeding it is feeding the production
path.

The sustained window
--------------------

:func:`flightsite.demo.scenario.batch_at` is a pure function of
``(roster, tick_index)`` with a 30-minute period, and the population inside that
period is a bell: it climbs from nothing, plateaus, and thins out again as
profiles reach the end of their active spans. At ``population=500`` the plateau
runs from roughly tick 500 to tick 1200 — see
:data:`SUSTAINED_FIRST_TICK` — so that is the window the harness draws from, and
it wraps back to the start when a run is longer than the window. Wrapping makes
a large slice of the live set disappear and reappear at once, which is a harder
tick than any inside the window rather than an easier one.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.alerts import AlertService
from flightsite.api.ws import ClientConnection, LiveBroadcaster
from flightsite.app import create_app
from flightsite.demo import DEFAULT_SEED, DemoAdapter
from flightsite.live import LiveStore
from flightsite.perf.budgets import TARGET_AIRCRAFT, TICK_INTERVAL_S
from flightsite.sightings import PersistenceWorker

#: Long enough that no background sweep, persistence cycle, alert pass or
#: broadcast tick ever fires on its own: every stage runs when this harness
#: says so. Borrowed from ``tests/api/conftest.py``'s ``NEVER_S``.
NEVER_S: Final = 3_600.0

#: First tick of the demo scenario's sustained plateau at ``population=500``
#: (see the module docstring). Before this the population is still climbing.
SUSTAINED_FIRST_TICK: Final = 500

#: Ticks available before the plateau decays below the target population.
SUSTAINED_TICKS: Final = 700

#: Default simulated WebSocket clients attached to the broadcaster. A home
#: install is a handful of browser tabs, not a fleet; ``docs/API.md`` §4.3
#: describes fan-out to "multiple clients" rather than to many.
DEFAULT_WS_CLIENTS: Final = 4


@dataclass(frozen=True, slots=True)
class WorkloadConfig:
    """How much load to apply, and for how long.

    Args:
        population: target concurrent aircraft (SPEC §5's envelope).
        ticks: measured 1 Hz ticks, after warm-up.
        warmup_ticks: ticks applied but not measured. The first tick into an
            empty store is all appearances, which is the cheap case and not
            what a running receiver does every second.
        ws_clients: simulated WebSocket clients attached to the broadcaster.
        seed: demo roster seed; the same seed is the same traffic, forever.
        realtime: pace ticks against the wall clock at ``tick_interval_s``.
            The truthful mode for a standalone run on real hardware, where the
            question is whether the machine sustains 1 Hz. Off in-suite, where
            the question is only what each stage costs.
        tick_interval_s: the poll interval the duty cycle is measured against.
    """

    population: int = TARGET_AIRCRAFT
    ticks: int = 60
    warmup_ticks: int = 5
    ws_clients: int = DEFAULT_WS_CLIENTS
    seed: int = DEFAULT_SEED
    realtime: bool = False
    tick_interval_s: float = TICK_INTERVAL_S

    def __post_init__(self) -> None:
        if self.population < 1:
            raise ValueError("population must be at least 1")
        if self.ticks < 1:
            raise ValueError("ticks must be at least 1")
        if self.warmup_ticks < 0:
            raise ValueError("warmup_ticks cannot be negative")
        if self.tick_interval_s <= 0.0:
            raise ValueError("tick_interval_s must be greater than zero")


@dataclass(frozen=True, slots=True)
class TickCost:
    """What one 1 Hz tick cost, stage by stage, in milliseconds.

    The stages are summed rather than measured end to end so that a regression
    names itself: a duty cycle that doubled is reported alongside the one stage
    that caused it.
    """

    apply_ms: float
    sweep_ms: float
    alerts_ms: float
    persistence_ms: float
    broadcast_ms: float
    population: int
    events_written: int

    @property
    def total_ms(self) -> float:
        """Everything a tick must do, which is what must fit inside a poll."""
        return (
            self.apply_ms + self.sweep_ms + self.alerts_ms + self.persistence_ms + self.broadcast_ms
        )

    def duty_cycle(self, tick_interval_s: float) -> float:
        """:attr:`total_ms` as a fraction of the poll interval."""
        return self.total_ms / (tick_interval_s * 1_000.0)


class Workload:
    """The application under sustained 500-aircraft load.

    Use as an async context manager: entering builds the app, replaces the
    components that must answer to the harness, runs the real lifespan and
    attaches the simulated WebSocket clients; leaving tears the lifespan down.

    Args:
        config: how much load, for how long.
        data_dir: where the SQLite database lives. A caller measuring real
            hardware points this at real storage — SD card behavior is a large
            part of what a Pi 4 qualification is testing.
    """

    def __init__(self, config: WorkloadConfig, *, data_dir: Path | None = None) -> None:
        self._config = config
        self._data_dir = data_dir
        self._adapter = DemoAdapter(population=config.population, seed=config.seed)
        self._app: FastAPI | None = None
        self._live: LiveStore | None = None
        self._worker: PersistenceWorker | None = None
        self._broadcaster: LiveBroadcaster | None = None
        self._clients: list[ClientConnection] = []
        self._lifespan: Any = None
        self._tick = 0

    # ------------------------------------------------------------- properties

    @property
    def config(self) -> WorkloadConfig:
        """The configuration this workload was built for."""
        return self._config

    @property
    def app(self) -> FastAPI:
        """The running application. Only valid inside the context manager."""
        if self._app is None:
            raise RuntimeError("workload is not started")
        return self._app

    @property
    def live(self) -> LiveStore:
        """The live store the traffic is being applied to."""
        if self._live is None:
            raise RuntimeError("workload is not started")
        return self._live

    @property
    def worker(self) -> PersistenceWorker:
        """The persistence worker draining the live event stream."""
        if self._worker is None:
            raise RuntimeError("workload is not started")
        return self._worker

    @property
    def broadcaster(self) -> LiveBroadcaster:
        """The WebSocket broadcaster fanning deltas out to :attr:`clients`."""
        if self._broadcaster is None:
            raise RuntimeError("workload is not started")
        return self._broadcaster

    @property
    def clients(self) -> tuple[ClientConnection, ...]:
        """The simulated WebSocket clients receiving every tick's delta."""
        return tuple(self._clients)

    @property
    def population(self) -> int:
        """Aircraft currently in the live set."""
        return len(self.live)

    # -------------------------------------------------------------- lifecycle

    async def __aenter__(self) -> Self:
        app = create_app(self._data_dir) if self._data_dir is not None else create_app()

        # The store, the worker and the alert service are replaced together:
        # the latter two *capture* the store rather than reading app.state, so
        # a worker left on the original store would never see this traffic.
        # Every interval is NEVER_S so no background task competes with the
        # explicit tick (see the module docstring).
        live = LiveStore(receiver_location=self._adapter.center, sweep_interval_s=NEVER_S)
        app.state.live = live
        worker = PersistenceWorker(database=app.state.database, live=live, tick_interval_s=NEVER_S)
        app.state.persistence = worker
        app.state.alerts = AlertService(
            database=app.state.database,
            live=live,
            metadata=app.state.metadata.cache,
            watchlists=app.state.watchlists,
            persistence=worker,
        )
        broadcaster = LiveBroadcaster(context=app.state.api_context, interval_s=NEVER_S)
        app.state.broadcaster = broadcaster

        self._app = app
        self._live = live
        self._worker = worker
        self._broadcaster = broadcaster

        self._lifespan = app.router.lifespan_context(app)
        await self._lifespan.__aenter__()

        # The alert engine's loop is event-driven rather than timed, so
        # NEVER_S cannot stand it down; stopping and re-attaching leaves it
        # subscribed and idle with this harness as its only driver — the same
        # bargain tests/api/conftest.py makes.
        engine = app.state.alerts.engine
        await engine.stop()
        engine.attach()

        receiver = await app.state.api_context.receiver()
        self._clients = [
            broadcaster.connect(dict(receiver)) for _ in range(self._config.ws_clients)
        ]
        for client in self._clients:
            await client.next_frame()  # drain the opening snapshot

        self._tick = 0
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        lifespan, self._lifespan = self._lifespan, None
        if lifespan is not None:
            await lifespan.__aexit__(exc_type, exc, traceback)
        self._app = None
        self._live = None
        self._worker = None
        self._broadcaster = None
        self._clients = []

    # ------------------------------------------------------------------ ticks

    def scenario_tick(self, offset: int) -> int:
        """The demo tick index this harness's ``offset``-th tick draws from.

        Wraps inside the sustained plateau (see the module docstring) so a run
        of any length keeps the live set at the target population.
        """
        return SUSTAINED_FIRST_TICK + offset % SUSTAINED_TICKS

    async def run_tick(self) -> TickCost:
        """Advance the pipeline by one 1 Hz tick and report what it cost.

        The stage order is the pipeline's own: the batch lands in the live
        store, the lifecycle sweep ages what stopped transmitting, alerts
        evaluate the new picture, persistence commits the cycle, and the
        broadcaster fans the delta out to every client.
        """
        started_wall = time.perf_counter()
        batch = self._adapter.batch_for_tick(self.scenario_tick(self._tick))
        self._tick += 1

        live = self.live
        started = time.perf_counter()
        live.apply(batch)
        apply_ms = (time.perf_counter() - started) * 1_000.0

        started = time.perf_counter()
        live.sweep()
        sweep_ms = (time.perf_counter() - started) * 1_000.0

        started = time.perf_counter()
        await self.app.state.alerts.engine.process_pending()
        alerts_ms = (time.perf_counter() - started) * 1_000.0

        started = time.perf_counter()
        result = await self.worker.process_pending()
        persistence_ms = (time.perf_counter() - started) * 1_000.0

        started = time.perf_counter()
        await self.broadcaster.broadcast_once()
        broadcast_ms = (time.perf_counter() - started) * 1_000.0

        # Clients must actually consume, or the fan-out is measured against
        # queues that only ever fill and a slow-consumer eviction would be
        # mistaken for cheap delivery.
        for client in self._clients:
            await client.next_frame()

        cost = TickCost(
            apply_ms=apply_ms,
            sweep_ms=sweep_ms,
            alerts_ms=alerts_ms,
            persistence_ms=persistence_ms,
            broadcast_ms=broadcast_ms,
            population=len(live),
            events_written=result.events,
        )

        if self._config.realtime:
            remaining = self._config.tick_interval_s - (time.perf_counter() - started_wall)
            if remaining > 0.0:
                await asyncio.sleep(remaining)
        return cost

    async def warm_up(self) -> None:
        """Run the configured warm-up ticks, discarding their cost."""
        for _ in range(self._config.warmup_ticks):
            await self.run_tick()

    @asynccontextmanager
    async def http(self) -> AsyncIterator[AsyncClient]:
        """An HTTP client for the app, on this event loop.

        ASGI rather than a socket: the harness measures the application's own
        cost under load, and a loopback TCP round trip would add a quantity
        that belongs to the kernel rather than to FlightSite.
        """
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://flightsite-perf"
        ) as client:
            yield client


__all__ = [
    "DEFAULT_WS_CLIENTS",
    "NEVER_S",
    "SUSTAINED_FIRST_TICK",
    "SUSTAINED_TICKS",
    "TickCost",
    "Workload",
    "WorkloadConfig",
]
