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
profiles reach the end of their active spans. At ``population=500`` the batch
first exceeds 520 aircraft at tick 560 and stays there until about tick 1170,
so :data:`SUSTAINED_FIRST_TICK` and :data:`SUSTAINED_TICKS` draw from inside
that band rather than from its shoulders.

The margin above 500 is deliberate. The live-population floor is a hard gate
read off the *minimum* sample, so a window that merely touched 500 would fail
on its own first tick — the harness would be reporting the scenario's shape
rather than the pipeline's health. Starting where the scenario carries a
comfortable surplus means a dip below 500 is a real finding about the live
store, which is what the gate is for.

Runs longer than the window wrap back to its start. Wrapping makes a large
slice of the live set disappear and reappear at once, which is a harder tick
than any inside the window rather than an easier one.
"""

from __future__ import annotations

import asyncio
import contextlib
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

#: First tick of the demo scenario's sustained plateau at ``population=500``:
#: the batch first carries more than 520 aircraft here. Before this the
#: population is still climbing (see the module docstring).
SUSTAINED_FIRST_TICK: Final = 560

#: Ticks drawn from the plateau before wrapping. The batch holds above 520
#: aircraft until roughly tick 1170, so this stops short of the decay.
SUSTAINED_TICKS: Final = 600

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
        self._readers: list[asyncio.Task[None]] = []
        self._receiver: dict[str, Any] = {}
        self._frames_read = 0
        self._reconnects = 0
        self._running = False
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

    @property
    def frames_read(self) -> int:
        """Frames the simulated clients have actually consumed.

        Zero while frames are being produced means the readers are not running,
        which would make the fan-out figure a measurement of filling queues
        rather than of delivering to clients.
        """
        return self._frames_read

    @property
    def reconnects(self) -> int:
        """Times a simulated client was closed and came back.

        A real signal rather than harness bookkeeping: each one is the
        broadcaster shedding a consumer that could not keep up with a burst,
        which ``docs/API.md`` §4.5 makes a resync rather than a stall. Reported
        alongside the fan-out figure so a run with many of them is not read as
        a quiet one.
        """
        return self._reconnects

    @property
    def clients_connected(self) -> int:
        """Clients the broadcaster still has. Drops mean a consumer fell behind.

        Worth checking at the end of a run: the broadcaster evicts a slow
        consumer rather than stalling for it, so a fan-out figure measured
        after an eviction is a figure for fewer clients than the report claims.
        """
        return self.broadcaster.client_count

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

        # Clients are NOT connected here; :meth:`warm_up` attaches them once
        # the system is running. See :meth:`connect_clients`.
        self._tick = 0
        return self

    async def connect_clients(self) -> None:
        """Attach the simulated WebSocket clients and start their readers.

        Deliberately *after* warm-up rather than at startup, and the reason is
        a first-run artefact rather than a preference. On an empty database
        every one of 500 aircraft is a first-ever sighting, so the activity
        service's first pass publishes a burst of ~500 events — and
        ``LiveBroadcaster.publish_activity`` sends one frame per event with no
        await between them. That burst overflows every client's 32-frame queue
        in a single call and the broadcaster evicts the lot as slow consumers,
        which is the documented behaviour (``docs/API.md`` §4.5) and not a
        product fault.

        It is, however, not the load this harness is trying to measure. A
        browser connects to a system that is already running; it does not sit
        through an install's first-ever backlog. So warm-up drains that backlog
        with nobody connected — ``publish_activity`` is a no-op with no clients
        — and the clients arrive afterwards, to steady-state traffic.
        """
        if self._clients:
            return
        self._receiver = dict(await self.app.state.api_context.receiver())
        self._running = True
        self._clients = [
            self.broadcaster.connect(dict(self._receiver)) for _ in range(self._config.ws_clients)
        ]
        self._readers = [
            asyncio.create_task(self._read_client(client), name=f"flightsite-perf-{client.name}")
            for client in self._clients
        ]
        await self._drain_clients()

    async def _read_client(self, client: ClientConnection) -> None:
        """Consume everything the broadcaster queues for one client.

        A reader task per client, which is exactly the shape of production's
        ``_write_to_client``: the connection's queue is bounded and a client
        that stops draining is dropped as a slow consumer rather than allowed
        to apply backpressure to the broadcaster (``docs/API.md`` §4.5).

        Draining a fixed number of frames per tick — one, say — is *not*
        equivalent and was the first thing this harness got wrong: a tick can
        emit a delta, a ping and an activity frame, so a fixed drain falls
        steadily behind until the queue overflows and every simulated client is
        evicted. The fan-out figure then quietly becomes a measurement of
        delivering to nobody.

        The reader also marks the client alive on every frame it takes, which
        is what production's ``_read_from_client`` does for any inbound client
        text — a real browser answers each keepalive ping with a pong
        (``docs/API.md`` §4.5). Without it a simulated client accumulates
        unanswered pings and is dropped as unresponsive after
        ``MISSED_PING_LIMIT``, which a ``--realtime`` run longer than a couple
        of ping intervals would hit every time.

        When the server does end the connection, the reader reconnects and
        carries on, which is the last piece of modelling a real client. The
        broadcaster closes a slow consumer with code 1013 — "try again later" —
        precisely so the client comes back and takes a fresh snapshot, and a
        browser does exactly that. Demo traffic on a new database produces
        activity bursts larger than a client's 32-frame queue as the roster
        keeps introducing first-ever aircraft, so a harness that did not
        reconnect would slowly lose every client and end up timing delivery to
        nobody.
        """
        while True:
            frame = await client.next_frame()
            if frame is not None:
                self._frames_read += 1
                client.note_client_message()
                continue

            # The server closed this connection. Come back, as a browser would.
            if not self._running:
                return
            self._reconnects += 1
            client = self.broadcaster.connect(dict(self._receiver))
            self._clients = [existing for existing in self._clients if not existing.closed]
            self._clients.append(client)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._running = False
        readers, self._readers = self._readers, []
        for reader in readers:
            reader.cancel()
        for reader in readers:
            with contextlib.suppress(asyncio.CancelledError):
                await reader

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

        await self._drain_clients()

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

    async def _drain_clients(self) -> None:
        """Yield until every reader task has consumed everything queued.

        Outside the measured window: fan-out cost is what the broadcaster
        spends, and a client's consumption belongs to the client.

        Yielding a *fixed* number of scheduling rounds is not enough, which is
        the second way this harness got client draining wrong. Each round lets
        one reader take one frame, so a tick that queues more frames than the
        fixed count leaves a remainder — and a remainder of even one frame per
        tick overflows a 32-frame queue within a couple of minutes and evicts
        every client.

        Yielding until a full round passes in which nobody consumed anything is
        exact instead of approximate, and it is still bounded: nothing produces
        frames between ticks, so the loop drains what is there and stops.
        Nothing here waits on time passing, only on tasks already runnable.
        """
        previous = -1
        while self._frames_read != previous:
            previous = self._frames_read
            await asyncio.sleep(0)

    async def warm_up(self) -> None:
        """Reach steady state, then attach the clients. Costs are discarded.

        Three things have to happen before a measured tick is representative:
        the live set has to fill (the first tick into an empty store is all
        appearances, the cheap case), the activity service's first-ever backlog
        has to drain, and only then may the clients connect — see
        :meth:`connect_clients` for why that order matters.
        """
        for _ in range(self._config.warmup_ticks):
            await self.run_tick()
        await self.app.state.activity.flush()
        await self.connect_clients()

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
