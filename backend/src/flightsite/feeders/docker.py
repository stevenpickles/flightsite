"""A read-only Docker Engine API client over the unix socket — no SDK.

ADR-0017: two of the owner's feeds publish nothing over HTTP. OpenSky's
feeder only logs a statistics block, and ultrafeeder only logs its ADS-B
(Beast) output connection coming and going. FlightSite can read both only
through the Docker Engine API, so when — and only when — the owner sets
``feeders.docker_socket`` this client is built against that socket.

What it does, and all it does
-----------------------------

* ``GET /_ping`` — is the socket there at all (diagnostics'
  ``docker_socket: available | unreachable``).
* ``GET /containers/{name}/json`` — the ``docker_health`` kind: running, and
  the container's own healthcheck verdict.
* ``GET /containers/{name}/logs?stdout=1&stderr=1&timestamps=1&since=&tail=`` —
  the log-only kinds.

Every call is a ``GET``. Nothing here starts, stops, execs into or inspects
anything beyond the named containers; the socket's trust boundary is
documented in ``docs/SECURITY.md``. API version ``v1.41`` (Docker 20.10) is
pinned in the path so a newer engine answers in the shape parsed here.

Log framing
-----------

A container without a TTY multiplexes stdout and stderr into one stream of
frames: an 8-byte header — stream id (1 stdout, 2 stderr), three zero bytes,
a big-endian 32-bit payload length — then the payload. A container *with* a
TTY sends raw bytes. :class:`LogDemuxer` tells the two apart from the first
bytes and handles frames split anywhere across chunk boundaries.

``timestamps=1`` makes Docker prefix each line with its own RFC 3339 UTC
receive time. That matters for OpenSky, whose own timestamps are in the
container's local zone: FlightSite's staleness arithmetic runs on Docker's
clock instead, which is UTC by construction.

Never raises
------------

Every public coroutine answers ``None`` for "could not ask" (socket missing,
permission denied, timeout, 5xx) and a value otherwise, so a probe maps an
unreachable socket to ``unknown`` rather than to an exception or to ``down``.
"""

from __future__ import annotations

import asyncio
import struct
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import quote

import httpx
import structlog

from flightsite.feeders.model import DetailValue, FeederState, Observability, ProbeResult

logger = structlog.get_logger(__name__)

#: Engine API version pinned into every path (Docker 20.10 and later).
API_VERSION: Final = "v1.41"

#: Per-request timeout. A local socket that cannot answer in three seconds is
#: a daemon under enough load that FlightSite should not add to it.
REQUEST_TIMEOUT_S: Final = 3.0

#: Hard ceiling on one log response. A first read of a long-running
#: container's ``tail`` can be a few megabytes; this is headroom, not a target.
MAX_LOG_BYTES: Final = 32 * 1024 * 1024

#: Header length of one multiplexed log frame.
FRAME_HEADER_BYTES: Final = 8

#: Placeholder host for requests over the unix socket; never resolved.
_BASE_URL: Final = "http://docker"


@dataclass(frozen=True, slots=True)
class ContainerState:
    """What ``GET /containers/{name}/json`` said about one container."""

    found: bool
    running: bool = False
    status: str | None = None
    #: The container's own healthcheck verdict, ``None`` without one.
    health: str | None = None
    started_ms: int | None = None


@dataclass(frozen=True, slots=True)
class LogLine:
    """One log line, with Docker's UTC receive time when it supplied one."""

    ts_ms: int | None
    text: str


def parse_docker_time(value: object) -> int | None:
    """An RFC 3339 timestamp (nanosecond precision allowed) as epoch ms."""
    if not isinstance(value, str) or not value or value.startswith("0001-"):
        return None
    stamp = value.strip()
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    # Python parses at most microseconds; Docker writes nanoseconds.
    head, dot, rest = stamp.partition(".")
    if dot:
        digits = "".join(ch for ch in rest if ch.isdigit())
        zone = rest[len(digits) :]
        stamp = f"{head}.{digits[:6].ljust(6, '0')}{zone}"
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def split_timestamp(line: str) -> LogLine:
    """Separate Docker's ``timestamps=1`` prefix from the line it stamps."""
    head, space, rest = line.partition(" ")
    ts_ms = parse_docker_time(head) if space else None
    if ts_ms is None:
        return LogLine(ts_ms=None, text=line)
    return LogLine(ts_ms=ts_ms, text=rest)


class LogDemuxer:
    """Incremental decoder for a Docker log stream, framed or raw.

    Feed it chunks as they arrive; it yields complete lines. Lines are kept
    per stream so a stderr frame arriving mid-way through a stdout line cannot
    splice two lines together.
    """

    __slots__ = ("_buffer", "_framed", "_partial")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._framed: bool | None = None
        self._partial: dict[int, bytearray] = {}

    def feed(self, chunk: bytes) -> list[str]:
        """Consume ``chunk``; return every line it completed."""
        self._buffer.extend(chunk)
        if self._framed is None:
            if len(self._buffer) < FRAME_HEADER_BYTES:
                return []
            head = self._buffer[:4]
            self._framed = head[0] in (0, 1, 2) and head[1:4] == b"\x00\x00\x00"
        if not self._framed:
            data = bytes(self._buffer)
            self._buffer.clear()
            return self._lines(0, data)

        lines: list[str] = []
        while len(self._buffer) >= FRAME_HEADER_BYTES:
            stream_id = self._buffer[0]
            (length,) = struct.unpack(">I", self._buffer[4:FRAME_HEADER_BYTES])
            if len(self._buffer) < FRAME_HEADER_BYTES + length:
                break
            payload = bytes(self._buffer[FRAME_HEADER_BYTES : FRAME_HEADER_BYTES + length])
            del self._buffer[: FRAME_HEADER_BYTES + length]
            lines.extend(self._lines(stream_id, payload))
        return lines

    def close(self) -> list[str]:
        """Flush whatever partial lines remain at end of stream."""
        lines: list[str] = []
        if self._framed is False or (self._framed is None and self._buffer):
            lines.extend(self._lines(0, bytes(self._buffer)))
            self._buffer.clear()
        for stream_id in sorted(self._partial):
            rest = self._partial[stream_id]
            if rest:
                lines.append(rest.decode("utf-8", errors="replace").rstrip("\r"))
        self._partial.clear()
        return lines

    def _lines(self, stream_id: int, data: bytes) -> list[str]:
        pending = self._partial.setdefault(stream_id, bytearray())
        pending.extend(data)
        *complete, rest = bytes(pending).split(b"\n")
        pending.clear()
        pending.extend(rest)
        return [line.decode("utf-8", errors="replace").rstrip("\r") for line in complete]


def demux(data: bytes) -> list[str]:
    """Every line of a complete log response. The one-shot form of :class:`LogDemuxer`."""
    demuxer = LogDemuxer()
    return [*demuxer.feed(data), *demuxer.close()]


class DockerClient:
    """Read-only Docker Engine API client over a unix socket.

    Args:
        socket_path: the socket, e.g. ``/var/run/docker.sock``.
        transport: replaces the unix-socket transport; tests pass an
            :class:`httpx.MockTransport`.
        timeout_s: per-request timeout.
    """

    __slots__ = ("_client", "_reachable", "_socket_path", "_timeout_s", "_transport")

    def __init__(
        self,
        socket_path: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = REQUEST_TIMEOUT_S,
    ) -> None:
        self._socket_path = socket_path
        self._transport = transport
        self._timeout_s = timeout_s
        self._client: httpx.AsyncClient | None = None
        self._reachable: bool | None = None

    @property
    def socket_path(self) -> str:
        """The socket this client talks to."""
        return self._socket_path

    @property
    def reachable(self) -> bool | None:
        """Whether the last request got an answer; ``None`` before the first."""
        return self._reachable

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            transport = self._transport or httpx.AsyncHTTPTransport(uds=self._socket_path)
            self._client = httpx.AsyncClient(
                transport=transport, base_url=_BASE_URL, timeout=self._timeout_s
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying client. Idempotent."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def _failed(self, what: str, exc: BaseException) -> None:
        if self._reachable is not False:
            logger.info("feeders_docker_unreachable", request=what, error=type(exc).__name__)
        self._reachable = False

    async def ping(self) -> bool:
        """True when the daemon answers ``/_ping``."""
        try:
            response = await self._http().get(f"/{API_VERSION}/_ping")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed("ping", exc)
            return False
        self._reachable = True
        return response.status_code == 200

    async def container(self, name: str) -> ContainerState | None:
        """The named container's state, ``found=False`` if it does not exist."""
        path = f"/{API_VERSION}/containers/{quote(name, safe='')}/json"
        try:
            response = await self._http().get(path)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed("container", exc)
            return None
        self._reachable = True
        if response.status_code == 404:
            return ContainerState(found=False)
        if response.status_code != 200:
            return None
        try:
            document: Any = response.json()
        except ValueError:
            return None
        state = document.get("State") if isinstance(document, dict) else None
        if not isinstance(state, dict):
            return ContainerState(found=True)
        health = state.get("Health")
        return ContainerState(
            found=True,
            running=state.get("Running") is True,
            status=state.get("Status") if isinstance(state.get("Status"), str) else None,
            health=(
                health.get("Status")
                if isinstance(health, dict) and isinstance(health.get("Status"), str)
                else None
            ),
            started_ms=parse_docker_time(state.get("StartedAt")),
        )

    async def logs(
        self,
        name: str,
        *,
        since_s: int | None = None,
        tail: int = 500,
        match: Callable[[str], bool] | None = None,
    ) -> list[LogLine] | None:
        """Recent log lines of ``name``, oldest first; ``None`` if it cannot be read.

        ``match`` filters lines as they stream in, so a large ``tail`` costs
        the bytes on the wire but not the memory of keeping them. At most
        ``tail`` matching lines are returned — the newest ones.
        """
        params: dict[str, str | int] = {
            "stdout": 1,
            "stderr": 1,
            "timestamps": 1,
            "tail": tail,
        }
        if since_s is not None:
            params["since"] = max(0, since_s)
        path = f"/{API_VERSION}/containers/{quote(name, safe='')}/logs"
        kept: deque[LogLine] = deque(maxlen=max(1, tail))
        demuxer = LogDemuxer()

        def keep(lines: list[str]) -> None:
            for raw in lines:
                line = split_timestamp(raw)
                if match is None or match(line.text):
                    kept.append(line)

        try:
            async with self._http().stream("GET", path, params=params) as response:
                if response.status_code != 200:
                    self._reachable = True
                    return None
                received = 0
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    keep(demuxer.feed(chunk))
                    if received > MAX_LOG_BYTES:
                        break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed("logs", exc)
            return None
        keep(demuxer.close())
        self._reachable = True
        return list(kept)


#: Builds the Docker client for a configured socket path.
DockerFactory = Callable[[str], DockerClient]


class DockerHealthProbe:
    """The ``docker_health`` kind: a container's own verdict, as a backstop.

    For a feed whose software publishes nothing FlightSite can read, "the
    container is running and its healthcheck passes" is the best available
    evidence. Without the socket this reads ``unknown`` / ``none`` — never
    ``down``, because FlightSite cannot see, not because the feed stopped.
    """

    __slots__ = ("_container", "_docker", "_name")

    kind = "docker_health"

    def __init__(self, name: str, *, container: str | None, docker: DockerClient | None) -> None:
        self._name = name
        self._container = container or name
        self._docker = docker

    @property
    def name(self) -> str:
        return self._name

    async def probe(self, now_ms: int) -> ProbeResult:
        """Read the container's state. Never raises."""
        if self._docker is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="Docker socket not configured",
            )
        state = await self._docker.container(self._container)
        if state is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="Docker socket unreachable",
                failed=True,
            )
        detail: dict[str, DetailValue] = {
            "container": self._container,
            "container_status": state.status,
            "container_health": state.health,
            "container_started_at_ms": state.started_ms,
        }
        if not state.found:
            return ProbeResult(
                state=FeederState.DOWN,
                observability=Observability.DOCKER,
                message=f"Container {self._container} not found",
                detail=detail,
            )
        if not state.running:
            return ProbeResult(
                state=FeederState.DOWN,
                observability=Observability.DOCKER,
                message=f"Container {self._container} is {state.status or 'not running'}",
                detail=detail,
            )
        if state.health == "unhealthy":
            return ProbeResult(
                state=FeederState.DEGRADED,
                observability=Observability.DOCKER,
                message=f"Container {self._container} reports unhealthy",
                detail=detail,
            )
        return ProbeResult(state=FeederState.UP, observability=Observability.DOCKER, detail=detail)


__all__ = [
    "API_VERSION",
    "FRAME_HEADER_BYTES",
    "MAX_LOG_BYTES",
    "REQUEST_TIMEOUT_S",
    "ContainerState",
    "DockerClient",
    "DockerFactory",
    "DockerHealthProbe",
    "LogDemuxer",
    "LogLine",
    "demux",
    "parse_docker_time",
    "split_timestamp",
]
