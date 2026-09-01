"""Harness for the live API: a hand-driven app and an in-loop WebSocket probe.

Two decisions shape everything here.

**Time is driven, never waited on.** The live store gets the same
:class:`~tests.live.conftest.ManualClock` its own tests use and a sweep
interval long enough that only explicit :meth:`LiveApp.sweep` calls advance the
lifecycle; the broadcaster gets a second manual clock for its ping schedule and
an interval long enough that only explicit
:meth:`~flightsite.api.ws.LiveBroadcaster.broadcast_once` calls emit a frame.
So a test spells out exactly which frames exist and in which order, and a
loaded machine cannot change the answer (``docs/TEST_STRATEGY.md`` §3).

**The WebSocket is driven through ASGI on the test's own event loop.**
``TestClient`` runs the app in a second thread, which would make "inject an
update, then broadcast, then assert on the next frame" a race rather than a
sequence — and its send side is unbounded, so a client that stops reading is
not actually slow and slow-consumer eviction could not be observed at all.
:class:`WebSocketProbe` speaks the ASGI WebSocket protocol directly, one
coroutine on one loop, and can stall its send side to make a client genuinely
unable to keep up.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.alerts import AlertService
from flightsite.api.ws import (
    DEFAULT_CLIENT_QUEUE_SIZE,
    DEFAULT_PING_INTERVAL_S,
    LiveBroadcaster,
)
from flightsite.app import create_app
from flightsite.ingest import AircraftStateUpdate
from flightsite.live import DEFAULT_QUEUE_SIZE, LiveStore
from flightsite.sightings import PersistenceWorker

from ..live.conftest import SEATTLE, ManualClock

#: Long enough that no background sweep or broadcast tick ever fires during a
#: test: every transition and every frame is one the test asked for.
NEVER_S = 3_600.0

WS_PATH = "/api/v1/ws/live"


async def settle(cycles: int = 5) -> None:
    """Let queued reader/writer tasks run without advancing wall-clock time.

    ``asyncio.sleep(0)`` yields exactly one scheduling round, so a handful of
    them lets a connection's reader consume a pong and its writer drain a
    frame. This is not a timeout in disguise — nothing here waits on time
    passing, only on the loop draining work that is already ready.
    """
    for _ in range(cycles):
        await asyncio.sleep(0)


@dataclass(slots=True)
class LiveApp:
    """An application whose live store and broadcaster the test drives."""

    app: FastAPI
    live: LiveStore
    broadcaster: LiveBroadcaster
    clock: ManualClock
    ping_clock: ManualClock

    def feed(self, *updates: AircraftStateUpdate) -> None:
        """Apply decoder observations straight to the live store."""
        self.live.apply_updates(updates)

    def advance(self, seconds: float) -> None:
        """Move the live store's monotonic clock forward."""
        self.clock.advance(seconds)

    def sweep(self) -> None:
        """Run one lifecycle pass (stale marking, removal)."""
        self.live.sweep()

    async def broadcast(self) -> None:
        """Emit one broadcaster tick and let the connections drain it."""
        await self.broadcaster.broadcast_once()
        await settle()

    async def pause_alerts(self) -> None:
        """Take the alert engine's evaluation loop off the event queue.

        That loop is *event-driven* — it wakes the instant an observation is
        published — so a test that also drove
        :meth:`~flightsite.alerts.engine.AlertEngine.process_pending` would be
        racing it for the same queue. Stopping and re-attaching leaves the
        engine subscribed and idle with the test as its only driver, which is
        the same bargain this harness already makes with the lifecycle sweep
        and the broadcast tick. Called before any traffic is fed, so the
        discarded subscription had nothing in it.
        """
        engine = self.app.state.alerts.engine
        await engine.stop()
        engine.attach()

    async def evaluate_alerts(self) -> None:
        """Run one alert evaluation over the traffic fed so far.

        Four steps, and each is a real one rather than a test convenience:
        let the metadata cache resolve what just appeared, commit the open
        sightings (a match has no ids to be written with until they exist),
        evaluate, and flush the sighting rows the evaluation raised
        ``max_alert_severity`` on.
        """
        await settle()
        await self.app.state.persistence.process_pending()
        await self.app.state.alerts.engine.process_pending()
        await self.app.state.persistence.process_pending()


def build_live_app(
    *,
    client_queue_size: int = DEFAULT_CLIENT_QUEUE_SIZE,
    ping_interval_s: float = DEFAULT_PING_INTERVAL_S,
    event_queue_size: int = DEFAULT_QUEUE_SIZE,
) -> LiveApp:
    """Build an app whose live store and broadcaster answer to the test.

    The store, the persistence worker and the alert service are replaced
    together, because each of the latter two *captures* the store rather than
    reading it from ``app.state`` — a worker or an engine left subscribed to
    the original store would simply never see the traffic a test feeds. The
    broadcaster and the API context read ``app.state`` lazily and therefore
    pick all three up without being told.
    """
    app = create_app()
    clock = ManualClock()
    live = LiveStore(clock=clock, receiver_location=SEATTLE, sweep_interval_s=NEVER_S)
    app.state.live = live
    app.state.persistence = PersistenceWorker(database=app.state.database, live=live)
    app.state.alerts = AlertService(
        database=app.state.database,
        live=live,
        metadata=app.state.metadata.cache,
        watchlists=app.state.watchlists,
        persistence=app.state.persistence,
    )

    ping_clock = ManualClock()
    broadcaster = LiveBroadcaster(
        context=app.state.api_context,
        interval_s=NEVER_S,
        ping_interval_s=ping_interval_s,
        client_queue_size=client_queue_size,
        event_queue_size=event_queue_size,
        clock=ping_clock,
    )
    app.state.broadcaster = broadcaster
    return LiveApp(app=app, live=live, broadcaster=broadcaster, clock=clock, ping_clock=ping_clock)


@pytest.fixture
async def live_app() -> AsyncIterator[LiveApp]:
    """A started app on driven clocks, torn down through its real lifespan."""
    harness = build_live_app()
    async with harness.app.router.lifespan_context(harness.app):
        await harness.pause_alerts()
        yield harness


@pytest.fixture
async def rest(live_app: LiveApp) -> AsyncIterator[AsyncClient]:
    """An HTTP client for the same app, on the same event loop."""
    async with AsyncClient(
        transport=ASGITransport(app=live_app.app), base_url="http://testserver"
    ) as client:
        yield client


@dataclass(slots=True)
class WebSocketProbe:
    """A WebSocket client that speaks ASGI to the app on the test's own loop.

    Frames the app sends land in :attr:`_inbound`; text the test sends lands in
    :attr:`_outbound`. :meth:`stall` blocks the send side, which is what a
    client on a saturated link looks like from the server's point of view.
    """

    app: FastAPI
    path: str = WS_PATH
    _inbound: asyncio.Queue[MutableMapping[str, Any]] = field(default_factory=asyncio.Queue)
    _outbound: asyncio.Queue[MutableMapping[str, Any]] = field(default_factory=asyncio.Queue)
    _stalled: asyncio.Event | None = None
    _task: asyncio.Task[None] | None = None

    async def _receive(self) -> MutableMapping[str, Any]:
        return await self._outbound.get()

    async def _send(self, message: MutableMapping[str, Any]) -> None:
        stalled = self._stalled
        if stalled is not None:
            await stalled.wait()
        await self._inbound.put(message)

    async def connect(self) -> None:
        """Open the connection and wait for the server to accept it."""
        scope: dict[str, Any] = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        await self._outbound.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self.app(scope, self._receive, self._send))
        accept = await self._inbound.get()
        assert accept["type"] == "websocket.accept", accept

    def stall(self) -> None:
        """Stop draining the socket: every further server send blocks."""
        self._stalled = asyncio.Event()

    def resume(self) -> None:
        """Start draining again."""
        stalled, self._stalled = self._stalled, None
        if stalled is not None:
            stalled.set()

    async def frame(self) -> dict[str, Any]:
        """The next envelope the server sent, decoded."""
        message = await self._inbound.get()
        assert message["type"] == "websocket.send", message
        decoded: dict[str, Any] = json.loads(message["text"])
        return decoded

    async def frames(self) -> list[dict[str, Any]]:
        """Every envelope buffered so far, decoded, without waiting for more."""
        collected: list[dict[str, Any]] = []
        while not self._inbound.empty():
            message = self._inbound.get_nowait()
            if message["type"] != "websocket.send":
                break
            collected.append(json.loads(message["text"]))
        return collected

    async def close_code(self) -> int:
        """Read forward to the server's close message and return its code."""
        while True:
            message = await self._inbound.get()
            if message["type"] == "websocket.close":
                code: int = message["code"]
                return code

    async def send(self, payload: Any) -> None:
        """Send a text message to the server."""
        text = payload if isinstance(payload, str) else json.dumps(payload)
        await self._outbound.put({"type": "websocket.receive", "text": text})
        await settle()

    async def disconnect(self) -> None:
        """Close from the client side and wait for the handler to finish."""
        await self._outbound.put({"type": "websocket.disconnect", "code": 1000})
        task = self._task
        if task is not None:
            await asyncio.wait_for(task, timeout=5.0)
            self._task = None


async def open_probe(harness: LiveApp) -> tuple[WebSocketProbe, dict[str, Any]]:
    """Connect a probe and return it with its opening snapshot frame."""
    probe = WebSocketProbe(app=harness.app)
    await probe.connect()
    return probe, await probe.frame()
