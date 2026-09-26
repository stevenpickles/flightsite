"""OpenSky Network — the ``opensky_logs`` kind. The only module that speaks it.

The OpenSky feeder publishes nothing over HTTP. Every ten minutes it logs a
statistics block, and that block is all there is:

.. code-block:: text

    Statistics
     - currently online
     - 86190 [99.76%] seconds online (overall)
     - 2 disconnections (overall)
     - 51234567 bytes sent (1.23 kB/s)

================================ =========================================
Line                             Used as
================================ =========================================
``currently online|offline``     the state
``N [P%] seconds online``        ``detail.seconds_online`` / ``availability_pct``
``N disconnections``             ``detail.disconnections``
``N bytes sent (R unit/s)``      ``detail.bytes_sent`` / ``bytes_out_per_s``
================================ =========================================

The feeder stamps its lines in the container's *local* zone, so they are not
used: the logs are read with Docker's own UTC ``timestamps=1`` prefix
(:mod:`flightsite.feeders.docker`) and the block's age is measured on that.
A newest block older than :data:`STALE_AFTER_MS` — two and a half intervals —
reads ``unknown``: FlightSite has lost sight of the feed, which is not evidence
that the feed stopped. Only the socket makes this observable at all; without
it the feeder is ``unknown`` / ``none``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from flightsite.feeders.docker import DockerClient, LogLine
from flightsite.feeders.model import (
    DetailValue,
    FeederState,
    MetricValue,
    Observability,
    ProbeResult,
)

#: The feeder logs a block every ten minutes; this is two and a half of them.
STALE_AFTER_MS: Final = 25 * 60 * 1000

#: How far back each read looks. Covers the stale window with room to spare.
LOOKBACK_S: Final = 30 * 60

#: Log lines asked for per read (the feeder is quiet between blocks).
LOG_TAIL: Final = 400

_HEADER: Final = re.compile(r"\bStatistics\b")
_ONLINE: Final = re.compile(r"\bcurrently\s+(online|offline)\b", re.IGNORECASE)
_SECONDS: Final = re.compile(r"(\d+)\s*\[\s*([\d.]+)\s*%\s*\]\s*seconds online", re.IGNORECASE)
_DISCONNECTS: Final = re.compile(r"(\d+)\s+disconnections?", re.IGNORECASE)
_BYTES: Final = re.compile(
    r"(\d+)\s+bytes sent(?:\s*\(\s*([\d.]+)\s*([kKMG]?i?B|bytes)/s\s*\))?", re.IGNORECASE
)
_UNIT_BYTES: Final = {"b": 1.0, "bytes": 1.0, "kb": 1e3, "kib": 1024.0, "mb": 1e6, "mib": 1048576.0}


@dataclass(frozen=True, slots=True)
class StatisticsBlock:
    """One parsed statistics block."""

    logged_ms: int | None
    online: bool | None = None
    seconds_online: int | None = None
    availability_pct: float | None = None
    disconnections: int | None = None
    bytes_sent: int | None = None
    bytes_per_s: float | None = None


def _rate(value: str | None, unit: str | None) -> float | None:
    if value is None or unit is None:
        return None
    scale = _UNIT_BYTES.get(unit.lower())
    return None if scale is None else float(value) * scale


def last_statistics_block(lines: Sequence[LogLine]) -> StatisticsBlock | None:
    """The newest complete-enough statistics block in ``lines``, or ``None``."""
    start = None
    for index in range(len(lines) - 1, -1, -1):
        if _HEADER.search(lines[index].text):
            start = index
            break
    if start is None:
        return None

    fields: dict[str, object] = {}
    for line in lines[start + 1 :]:
        text = line.text
        if _HEADER.search(text):
            break
        if (online := _ONLINE.search(text)) is not None:
            fields["online"] = online.group(1).lower() == "online"
        elif (seconds := _SECONDS.search(text)) is not None:
            fields["seconds_online"] = int(seconds.group(1))
            fields["availability_pct"] = float(seconds.group(2))
        elif (disconnects := _DISCONNECTS.search(text)) is not None:
            fields["disconnections"] = int(disconnects.group(1))
        elif (sent := _BYTES.search(text)) is not None:
            fields["bytes_sent"] = int(sent.group(1))
            fields["bytes_per_s"] = _rate(sent.group(2), sent.group(3))

    def value[T](key: str, kind: type[T]) -> T | None:
        found = fields.get(key)
        return found if isinstance(found, kind) else None

    return StatisticsBlock(
        logged_ms=lines[start].ts_ms,
        online=value("online", bool),
        seconds_online=value("seconds_online", int),
        availability_pct=value("availability_pct", float),
        disconnections=value("disconnections", int),
        bytes_sent=value("bytes_sent", int),
        bytes_per_s=value("bytes_per_s", float),
    )


def block_result(block: StatisticsBlock | None, *, now_ms: int) -> ProbeResult:
    """Judge one statistics block (or its absence) at ``now_ms``."""
    if block is None:
        return ProbeResult(
            state=FeederState.UNKNOWN,
            observability=Observability.DOCKER,
            message="No statistics logged in the last 30 minutes",
        )
    detail: dict[str, DetailValue] = {
        "seconds_online": block.seconds_online,
        "availability_pct": block.availability_pct,
        "disconnections": block.disconnections,
        "bytes_sent": block.bytes_sent,
        "statistics_at_ms": block.logged_ms,
    }
    metrics: dict[str, MetricValue] = {
        "bytes_out_per_s": block.bytes_per_s,
        "availability_pct": block.availability_pct,
        "disconnections": block.disconnections,
    }
    if block.logged_ms is not None and now_ms - block.logged_ms > STALE_AFTER_MS:
        return ProbeResult(
            state=FeederState.UNKNOWN,
            observability=Observability.DOCKER,
            message="No statistics logged in the last 25 minutes",
            detail=detail,
            metrics=metrics,
        )
    if block.online is None:
        state, message = FeederState.UNKNOWN, "Statistics block did not say online or offline"
    elif block.online:
        state, message = FeederState.UP, None
    else:
        state, message = FeederState.DOWN, "OpenSky feeder reports offline"
    return ProbeResult(
        state=state,
        observability=Observability.DOCKER,
        message=message,
        last_data_sent_ms=block.logged_ms if block.online else None,
        detail=detail,
        metrics=metrics,
    )


class OpenSkyLogsProbe:
    """Reads the OpenSky feeder's statistics block from its container logs."""

    __slots__ = ("_container", "_docker", "_name")

    kind = "opensky_logs"

    def __init__(self, name: str, *, container: str | None, docker: DockerClient | None) -> None:
        self._name = name
        self._container = container or "opensky"
        self._docker = docker

    @property
    def name(self) -> str:
        return self._name

    async def probe(self, now_ms: int) -> ProbeResult:
        """One read of the recent logs. Never raises."""
        if self._docker is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="Docker socket not configured",
            )
        lines = await self._docker.logs(
            self._container, since_s=now_ms // 1000 - LOOKBACK_S, tail=LOG_TAIL
        )
        if lines is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="Could not read the container's logs",
                failed=True,
            )
        return block_result(last_statistics_block(lines), now_ms=now_ms)


__all__ = [
    "LOG_TAIL",
    "LOOKBACK_S",
    "STALE_AFTER_MS",
    "OpenSkyLogsProbe",
    "StatisticsBlock",
    "block_result",
    "last_statistics_block",
]
