"""The live WebSocket: ``/api/v1/ws/live`` — protocol, broadcaster, clients.

OpenAPI 3.1 cannot describe a WebSocket, so ``docs/API.md`` §2.10's published
schema stops at the REST surface and **this docstring is the reference for the
socket**. It restates ``docs/API.md`` §4 and pins down the two things a
document can leave implicit: the exact order a client applies a delta in, and
what the server does to a client that cannot keep up.

Envelope
--------

Every server-to-client frame is one JSON object (§4.1)::

    {"type": "snapshot", "seq": 1, "ts": "2026-08-31T14:03:22.418Z", "data": {...}}

``seq`` is **per connection** and starts at 1 with the snapshot. It exists so a
client can detect a gap; this server never leaves one, because a client it
cannot deliver to in order is disconnected instead (see *Slow consumers*).
``ts`` is the server's UTC send time in the §2.2 format. ``type`` is one of
``snapshot``, ``delta``, ``ping`` or ``pong`` in this slice; slice 035 adds
``activity``. Per §6 a client must ignore types it does not know.

Frames
------

**snapshot** — sent immediately on connect, and again if the broadcaster has to
resync (below). It replaces the client's entire picture::

    {"aircraft": [ /* §3.3 objects */ ], "receiver": { /* §3.2 block */ }}

**delta** — emitted about once a second, batching everything that happened in
that second (§4.3)::

    {"updated": [ /* complete §3.3 objects */ ], "stale": ["ae1463"], "removed": ["a9c2f0"]}

``updated`` carries **complete** aircraft objects, never field patches, so a
client can upsert without merge logic. A frame with nothing in any of the three
lists is not sent — silence means nothing changed, and ``ping`` is the
keepalive.

*Application order is: ``removed``, then ``stale``, then ``updated``.* Within
one batch an aircraft is listed at most once in ``removed``, and an aircraft
that both changed and crossed the staleness threshold appears in ``stale``
*and* in ``updated`` — its complete object already carries ``state: "stale"``,
so the two agree and the order only matters for a client that applies ``stale``
as a flag flip. A client that follows this order ends each batch holding
exactly what ``GET /api/v1/aircraft/current`` would have returned at the moment
the frame was built, which is roadmap slice 010's REST/WS agreement criterion.

**ping / pong** — the server sends a ``ping`` frame every
:data:`DEFAULT_PING_INTERVAL_S` seconds and the client **must** answer with
``{"type": "pong"}`` (a bare ``"ping"``/``"pong"`` string is also accepted).
A client that has not sent *anything* across :data:`MISSED_PING_LIMIT`
consecutive pings is disconnected (§4.5). A client may also send
``{"type": "ping"}`` at any time and gets a ``pong`` envelope back. This is the
application-level keepalive, layered over — not instead of — the transport
ping frames uvicorn sends; the application-level one is what survives an
intermediary proxy that answers protocol pings on the client's behalf.

Reconnect and resync
--------------------

There is no delta replay (§4.5). Every connection begins with a snapshot, and
the snapshot is the only resync mechanism, which is why a client's recovery
from any inconsistency is simply to reconnect with backoff.

The server resyncs the same way. The broadcaster reads the live store through a
bounded event subscription; if it ever falls far enough behind that the store
sheds events, its stream has a hole, and it broadcasts a fresh ``snapshot``
frame to every client instead of a delta built on a gap
(:mod:`flightsite.live.events` calls this drop-and-resync).

Slow consumers
--------------

Each connection has its own bounded outbound queue
(:data:`DEFAULT_CLIENT_QUEUE_SIZE` frames). When a frame will not fit, that
client is disconnected with close code :data:`RESYNC_CLOSE_CODE` and the
``ws_disconnects`` counter rises. The server never buffers without bound and
never waits for a slow socket — SPEC §5 and ``docs/ARCHITECTURE.md`` §3.3 both
say distribution must not stall, and one client on a saturated Wi-Fi link must
not be able to slow ingestion, the live store, or anybody else's stream. The
dropped client reconnects and gets a coherent snapshot, which is strictly
better than a stream it is already behind on.

Serialization cost
------------------

One frame is serialized **once** per tick, not once per client: the aircraft
objects and the frame body are rendered to a JSON string a single time, and
each client's envelope is finished by splicing its own ``seq`` around that
string (:class:`Frame`). Fanning out to N clients therefore costs N small
string joins rather than N JSON encodings of 500 aircraft.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from flightsite.api.context import LiveApiContext
from flightsite.api.serializers import iso_utc
from flightsite.counters import WS_DISCONNECTS, CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.live import (
    DEFAULT_QUEUE_SIZE,
    AircraftAppeared,
    AircraftRemoved,
    AircraftStale,
    AircraftUpdated,
    EventSubscription,
    LiveEvent,
)

logger = structlog.get_logger(__name__)

#: How often batched deltas are emitted (``docs/API.md`` §4.3, "~1 Hz").
DEFAULT_BROADCAST_INTERVAL_S: Final = 1.0

#: How often a ``ping`` frame is sent (§4.5).
DEFAULT_PING_INTERVAL_S: Final = 30.0

#: Consecutive unanswered pings after which a client is disconnected (§4.5).
MISSED_PING_LIMIT: Final = 2

#: Frames buffered per connection before the client is dropped.
#:
#: Thirty-two frames is half a minute of deltas: long enough to absorb a
#: garbage-collection pause, a browser tab being restored, or a burst of
#: snapshot-sized frames, and short enough that a client which has genuinely
#: stopped reading is disconnected before its buffer matters against the
#: <1 GB process budget. The bound is frames, not bytes, because the failure
#: being defended against is a socket that has stopped draining at all.
DEFAULT_CLIENT_QUEUE_SIZE: Final = 32

#: Close code for a server-initiated drop. 1013 ("try again later") says
#: exactly what the client should do: reconnect with backoff and take the
#: fresh snapshot (§4.5).
RESYNC_CLOSE_CODE: Final = 1013

#: Close code used when the process is shutting down.
GOING_AWAY_CLOSE_CODE: Final = 1001

#: A source of monotonically increasing seconds, injected for tests.
MonotonicClock = Callable[[], float]


class MessageType(StrEnum):
    """Frame types this slice's protocol defines (``docs/API.md`` §4)."""

    SNAPSHOT = "snapshot"
    DELTA = "delta"
    PING = "ping"
    PONG = "pong"


@dataclass(frozen=True, slots=True)
class Frame:
    """One rendered frame body, ready to be given a per-connection ``seq``.

    The expensive half of a frame — the ``data`` object — is JSON-encoded once
    in :meth:`build`; :meth:`render` only splices the envelope around it. Every
    value interpolated into the envelope is server-generated and drawn from a
    fixed vocabulary (a :class:`MessageType`, a formatted timestamp, an
    integer), so the concatenation cannot produce anything but valid JSON.
    """

    type: MessageType
    ts: str
    data_json: str

    @classmethod
    def build(cls, message_type: MessageType, data: Any) -> Frame:
        """Encode ``data`` once, stamped with the current UTC instant."""
        return cls(
            type=message_type,
            ts=iso_utc(datetime.now(UTC)),
            data_json=json.dumps(data, separators=(",", ":")),
        )

    def render(self, seq: int) -> str:
        """The complete §4.1 envelope for a connection at sequence ``seq``."""
        return (
            f'{{"type":"{self.type.value}","seq":{seq},"ts":"{self.ts}","data":{self.data_json}}}'
        )


class ClientConnection:
    """One WebSocket client's outbound queue, sequence counter and liveness.

    Owned by the connection's request handler for its lifetime and written to
    by the broadcaster. Nothing here awaits: enqueueing is ``put_nowait`` and a
    full queue disconnects the client rather than applying backpressure to the
    broadcaster, which is the whole point (§4.5).
    """

    __slots__ = (
        "_close_code",
        "_close_reason",
        "_closed",
        "_counters",
        "_name",
        "_pings_outstanding",
        "_queue",
        "_seq",
    )

    def __init__(
        self,
        *,
        name: str,
        queue_size: int = DEFAULT_CLIENT_QUEUE_SIZE,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if queue_size < 1:
            raise ValueError("client queue size must be at least 1")
        self._name = name
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_size)
        self._counters = counters
        self._seq = 0
        self._pings_outstanding = 0
        self._closed = False
        self._close_code = RESYNC_CLOSE_CODE
        self._close_reason = ""

    @property
    def name(self) -> str:
        """Connection label used in logs."""
        return self._name

    @property
    def seq(self) -> int:
        """Sequence number of the last frame handed to this connection."""
        return self._seq

    @property
    def closed(self) -> bool:
        """True once the server has decided this connection is finished."""
        return self._closed

    @property
    def close_code(self) -> int:
        """WebSocket close code the writer should use."""
        return self._close_code

    @property
    def close_reason(self) -> str:
        """Human-readable close reason, sent alongside the code."""
        return self._close_reason

    @property
    def pending(self) -> int:
        """Frames queued and not yet written to the socket."""
        return self._queue.qsize()

    @property
    def capacity(self) -> int:
        """Bound on :attr:`pending` before this client is dropped."""
        return self._queue.maxsize

    def deliver(self, frame: Frame) -> bool:
        """Queue ``frame`` for this connection.

        Returns:
            ``False`` when the client could not take it and has been dropped —
            either because it was already closed or because its queue is full.
            The caller's only job on ``False`` is to stop tracking it.
        """
        if self._closed:
            return False
        # The sequence number advances only if the frame is actually queued, so
        # a dropped frame cannot leave a hole in a surviving connection's
        # numbering (§4.1 gives `seq` gaps a meaning, so they must not happen
        # by accident).
        seq = self._seq + 1
        try:
            self._queue.put_nowait(frame.render(seq))
        except asyncio.QueueFull:
            self._terminate(RESYNC_CLOSE_CODE, "slow_consumer", counted=True)
            return False
        self._seq = seq
        return True

    def note_client_message(self) -> None:
        """Record that the client is alive, clearing its unanswered pings."""
        self._pings_outstanding = 0

    def note_ping(self) -> bool:
        """Account for a ping about to be sent.

        Returns:
            ``False`` if the client has already ignored
            :data:`MISSED_PING_LIMIT` pings, in which case it has been dropped.
        """
        if self._pings_outstanding >= MISSED_PING_LIMIT:
            self._terminate(RESYNC_CLOSE_CODE, "unresponsive", counted=True)
            return False
        self._pings_outstanding += 1
        return True

    def shut_down(self) -> None:
        """End the connection because the server is stopping.

        Deliberately not counted: ``ws_disconnects`` measures clients the
        server had to abandon (§4.5), and a clean shutdown is not one.
        """
        self._terminate(GOING_AWAY_CLOSE_CODE, "shutdown", counted=False)

    def _terminate(self, code: int, reason: str, *, counted: bool) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_code = code
        self._close_reason = reason
        # Discard whatever is queued before signalling: those frames describe a
        # picture the client is about to be resynced out of, and holding them
        # would only delay the close behind a backlog.
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(None)
        if counted:
            self._counters.increment(WS_DISCONNECTS)
            logger.warning(
                "ws_client_dropped",
                client=self._name,
                reason=reason,
                seq=self._seq,
                capacity=self._queue.maxsize,
            )

    async def next_frame(self) -> str | None:
        """Await the next frame to write, or ``None`` once the client is done."""
        return await self._queue.get()


class LiveBroadcaster:
    """The single app-level task that fans live changes out to every client.

    One subscription to the live event stream, one delta built per tick, one
    serialization per frame — see the module docstring. Constructing it
    subscribes to nothing and starts nothing; :meth:`start` does both.

    Args:
        context: assembles the aircraft and receiver payloads.
        interval_s: delta batching period (§4.3's "~1 Hz").
        ping_interval_s: keepalive period (§4.5).
        client_queue_size: per-connection outbound bound.
        event_queue_size: bound on this broadcaster's live-event subscription.
            Overflowing it triggers a snapshot resync, never a stall.
        clock: monotonic seconds source, injected for tests.
        counters: registry receiving ``ws_disconnects``.
    """

    __slots__ = (
        "_client_queue_size",
        "_clients",
        "_clock",
        "_connections",
        "_context",
        "_counters",
        "_event_queue_size",
        "_interval_s",
        "_last_ping",
        "_ping_interval_s",
        "_subscription",
        "_task",
    )

    def __init__(
        self,
        *,
        context: LiveApiContext,
        interval_s: float = DEFAULT_BROADCAST_INTERVAL_S,
        ping_interval_s: float = DEFAULT_PING_INTERVAL_S,
        client_queue_size: int = DEFAULT_CLIENT_QUEUE_SIZE,
        event_queue_size: int = DEFAULT_QUEUE_SIZE,
        clock: MonotonicClock = time.monotonic,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if interval_s <= 0.0:
            raise ValueError("broadcast interval must be greater than zero")
        if ping_interval_s <= 0.0:
            raise ValueError("ping interval must be greater than zero")

        self._context = context
        self._interval_s = interval_s
        self._ping_interval_s = ping_interval_s
        self._client_queue_size = client_queue_size
        self._event_queue_size = event_queue_size
        self._clock = clock
        self._counters = counters

        self._clients: list[ClientConnection] = []
        self._subscription: EventSubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_ping = 0.0
        self._connections = 0

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the broadcast task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def client_count(self) -> int:
        """Connections currently receiving frames."""
        return len(self._clients)

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Subscribe to live events and start broadcasting. Idempotent."""
        if self.running:
            return
        self._subscription = self._context.live.subscribe(
            "websocket", maxsize=self._event_queue_size
        )
        self._last_ping = self._clock()
        self._task = asyncio.create_task(self._loop(), name="flightsite-ws-broadcast")
        logger.info(
            "ws_broadcaster_started",
            interval_s=self._interval_s,
            ping_interval_s=self._ping_interval_s,
            client_queue_size=self._client_queue_size,
        )

    async def stop(self) -> None:
        """Stop broadcasting and close every connection. Idempotent."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()

        clients, self._clients = self._clients, []
        for client in clients:
            client.shut_down()
        logger.info("ws_broadcaster_stopped", clients=len(clients))

    # ------------------------------------------------------------ connections

    def connect(self, receiver: dict[str, Any]) -> ClientConnection:
        """Register a new client and queue its opening snapshot (§4.2).

        Synchronous from end to end, and that is the point: the live snapshot
        is taken and the connection joins the fan-out set without an ``await``
        between the two, so no delta can be published into the gap. The
        connection's first frame is ``seq: 1``, a full picture, every time.

        Args:
            receiver: the §3.2 block to embed, already read by the caller (it
                needs a database round trip for T0, which must happen before
                this call rather than inside it).
        """
        self._connections += 1
        client = ClientConnection(
            name=f"ws-{self._connections}",
            queue_size=self._client_queue_size,
            counters=self._counters,
        )
        client.deliver(self._snapshot_frame(receiver))
        self._clients.append(client)
        logger.info("ws_client_connected", client=client.name, clients=len(self._clients))
        return client

    def disconnect(self, client: ClientConnection) -> None:
        """Stop delivering to ``client``. Idempotent."""
        if client in self._clients:
            self._clients.remove(client)
            logger.info("ws_client_disconnected", client=client.name, clients=len(self._clients))

    # ------------------------------------------------------------ broadcasting

    async def broadcast_once(self) -> None:
        """Run one tick: drain events, emit a delta or a resync, then keepalive.

        Split out from :meth:`_loop` so tests drive it a tick at a time instead
        of sleeping (``docs/TEST_STRATEGY.md`` §3).
        """
        subscription = self._subscription
        if subscription is None:
            return

        events = subscription.drain()
        overflowed = subscription.overflowed
        if overflowed:
            subscription.acknowledge_overflow()

        # With nobody listening the events are simply discarded: draining is
        # what keeps the subscription from overflowing on an idle socket, and
        # serializing frames no one will read would be pure waste.
        if self._clients:
            if overflowed:
                await self._resync()
            else:
                self._emit_delta(events)
        self._maybe_ping()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            try:
                await self.broadcast_once()
            except Exception as exc:  # pragma: no cover - defensive
                # One bad tick must not end live distribution for the process:
                # a dead broadcaster would leave every client silently frozen
                # on a stale picture, which is worse than a skipped frame.
                logger.warning("ws_broadcast_error", error=str(exc), error_type=type(exc).__name__)

    def _snapshot_frame(self, receiver: dict[str, Any]) -> Frame:
        return Frame.build(
            MessageType.SNAPSHOT,
            {"aircraft": self._context.aircraft(), "receiver": receiver},
        )

    async def _resync(self) -> None:
        """Broadcast a fresh snapshot after the event stream lost events.

        The receiver block needs a database read, so it is fetched first and
        the live snapshot is taken *after* the await — the frame then describes
        one coherent instant no earlier than the gap it repairs.
        """
        receiver = await self._context.receiver()
        self._deliver_all(self._snapshot_frame(receiver))
        logger.warning("ws_resynced_from_snapshot", clients=len(self._clients))

    def _emit_delta(self, events: Sequence[LiveEvent]) -> None:
        """Collapse one tick's events into a single §4.3 delta frame."""
        if not events:
            return

        # The last event for an ICAO decides which notice it belongs in;
        # `observed` remembers whether it also carried a new observation, so an
        # aircraft that changed and then went stale in the same second is
        # reported in both lists rather than losing its update.
        last: dict[str, type[LiveEvent]] = {}
        observed: set[str] = set()
        for event in events:
            last[event.icao] = type(event)
            if isinstance(event, AircraftAppeared | AircraftUpdated):
                observed.add(event.icao)
            elif isinstance(event, AircraftRemoved):
                observed.discard(event.icao)

        removed = [icao for icao, kind in last.items() if kind is AircraftRemoved]
        stale = [icao for icao, kind in last.items() if kind is AircraftStale]
        updated = self._context.aircraft_for(icao for icao in last if icao in observed)
        if not (updated or stale or removed):
            return

        self._deliver_all(
            Frame.build(
                MessageType.DELTA,
                {"updated": updated, "stale": stale, "removed": removed},
            )
        )

    def _maybe_ping(self) -> None:
        """Send a keepalive if one is due, dropping clients that ignored two."""
        now = self._clock()
        if now - self._last_ping < self._ping_interval_s:
            return
        self._last_ping = now

        frame = Frame.build(MessageType.PING, {})
        for client in list(self._clients):
            if not client.note_ping() or not client.deliver(frame):
                self._clients.remove(client)

    def _deliver_all(self, frame: Frame) -> None:
        for client in list(self._clients):
            if not client.deliver(frame):
                self._clients.remove(client)


router = APIRouter()


@router.websocket("/ws/live")
async def live_stream(websocket: WebSocket) -> None:
    """The live picture: a snapshot on connect, then ~1 Hz deltas (§4).

    Documented in this module's docstring; OpenAPI has no vocabulary for it.
    """
    broadcaster: LiveBroadcaster = websocket.app.state.broadcaster
    context: LiveApiContext = websocket.app.state.api_context

    await websocket.accept()
    # Read the receiver block (one indexed T0 lookup) before registering: the
    # snapshot and the fan-out registration must not be separated by an await.
    receiver = await context.receiver()
    client = broadcaster.connect(receiver)
    try:
        await _serve(websocket, client)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.disconnect(client)


async def _serve(websocket: WebSocket, client: ClientConnection) -> None:
    """Run the connection's reader and writer until either one finishes."""
    tasks = {
        asyncio.create_task(_read_from_client(websocket, client), name=f"{client.name}-reader"),
        asyncio.create_task(_write_to_client(websocket, client), name=f"{client.name}-writer"),
    }
    done: set[asyncio.Task[None]] = set()
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    for task in done:
        error = task.exception()
        if error is not None and not isinstance(error, WebSocketDisconnect):
            raise error


async def _write_to_client(websocket: WebSocket, client: ClientConnection) -> None:
    """Drain the connection's queue to the socket until it is closed."""
    while True:
        frame = await client.next_frame()
        try:
            if frame is None:
                await websocket.close(code=client.close_code, reason=client.close_reason)
                return
            await websocket.send_text(frame)
        except RuntimeError:
            # Starlette raises RuntimeError when the peer has already gone.
            # There is nothing to report: the reader sees the same disconnect
            # and the handler's `finally` deregisters the client either way.
            return


async def _read_from_client(websocket: WebSocket, client: ClientConnection) -> None:
    """Track client liveness and answer client-initiated pings (§4.5)."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        client.note_client_message()
        text = message.get("text")
        if text is not None and _is_ping(text) and not client.deliver(_pong_frame()):
            return


def _pong_frame() -> Frame:
    return Frame.build(MessageType.PONG, {})


def _is_ping(text: str) -> bool:
    """True when a client message is a ping — an envelope or a bare word."""
    stripped = text.strip()
    if stripped == MessageType.PING.value:
        return True
    try:
        message: Any = json.loads(stripped)
    except ValueError:
        return False
    if isinstance(message, str):
        return message == MessageType.PING.value
    return isinstance(message, dict) and message.get("type") == MessageType.PING.value


__all__ = [
    "DEFAULT_BROADCAST_INTERVAL_S",
    "DEFAULT_CLIENT_QUEUE_SIZE",
    "DEFAULT_PING_INTERVAL_S",
    "GOING_AWAY_CLOSE_CODE",
    "MISSED_PING_LIMIT",
    "RESYNC_CLOSE_CODE",
    "ClientConnection",
    "Frame",
    "LiveBroadcaster",
    "MessageType",
    "MonotonicClock",
    "router",
]
