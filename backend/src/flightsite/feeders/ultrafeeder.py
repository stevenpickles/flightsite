"""Networks fed by ultrafeeder connectors — the ``ultrafeeder`` kind.

ADS-B Exchange and AeroDataBox are not containers of their own on the owner's
receiver: each is a *connector* inside ultrafeeder, which runs one
mlat-client and one Beast output per network. So one feeder of this kind is
two signals, read two ways.

MLAT — over HTTP, always
------------------------

Each mlat-client writes a statistics document ultrafeeder serves at
``/mlat-client-stats/<host>:<mlat_port>.json``, refreshed about every 15 s.

================================== ==========================================
Field                              Used as
================================== ==========================================
``now``                            staleness (epoch seconds)
``peer_count``                     ``mlat.peers``
``good_sync_percentage_last_hour`` ``mlat.good_sync_pct``
``bad_sync_timeout``               ``mlat.bad_sync_timeout_s``
``outlier_percent``                ``detail.outlier_pct``
``last_bad_sync``                  ``mlat.last_bad_sync_at`` (``-1`` = never)
================================== ==========================================

``peer_count == 0`` does **not** mean down. A connected client with no peers
to synchronise against is still sending its data; AeroDataBox's server flaps
between 0 and 1 peers routinely. Zero peers becomes ``degraded`` only after
:data:`ZERO_PEER_TOLERANCE` consecutive polls, and never ``down``.

ADS-B out — from ultrafeeder's logs, when the Docker socket is set
-------------------------------------------------------------------

The Beast output's state is logged only on a transition —
``BeastReduce TCP output: Connection established: <host> … port <n>`` or a
disconnect line for the same host and port — so "connected" means "the latest
line for this host and port says established". The first read goes a long way
back (:data:`FIRST_READ_TAIL` lines, filtered as they stream) to find the last
transition; later reads only ask for what is new since the previous one. With
no socket, ``adsb_out`` is ``null`` and the feeder is judged on MLAT alone.
The ``/run/adsbexchange-stats`` documents are never read: they carry the
feeder's UUID.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import httpx

from flightsite.feeders.docker import DockerClient
from flightsite.feeders.fetch import FetchError, count, fetch_json, join_url, number
from flightsite.feeders.model import (
    AdsbOutStatus,
    DetailValue,
    FeederState,
    MetricValue,
    MlatStatus,
    Observability,
    ProbeResult,
)

#: Consecutive zero-peer polls tolerated before MLAT reads ``degraded``.
ZERO_PEER_TOLERANCE: Final = 3

#: An mlat-client statistics document older than this is a client that stopped.
MLAT_STALE_AFTER_MS: Final = 60 * 1000

#: Log lines scanned (filtered while streaming) on the first read.
FIRST_READ_TAIL: Final = 20_000

#: Log lines asked for on each later read, which only covers one poll interval.
NEXT_READ_TAIL: Final = 2_000

#: Seconds of overlap between consecutive log reads, so a line logged at the
#: boundary second is never missed. Re-reading it is harmless.
LOG_OVERLAP_S: Final = 5

_BEAST_MARKER: Final = "BeastReduce TCP output"
_ESTABLISHED: Final = "Connection established"

#: Values mlat-client uses for "never" and plausibility floors for epoch values.
_EPOCH_FLOOR_S: Final = 1_000_000_000


def mlat_stats_path(host: str, mlat_port: int) -> str:
    """The statistics document path for one network's mlat-client."""
    return f"mlat-client-stats/{host}:{mlat_port}.json"


def _last_bad_sync_ms(value: object, written_s: float | None) -> int | None:
    stamp = number(value)
    if stamp is None or stamp <= 0:
        return None
    if stamp >= _EPOCH_FLOOR_S:
        return int(stamp * 1000)
    # A small value is an age in seconds relative to the document.
    return None if written_s is None else int((written_s - stamp) * 1000)


def parse_mlat_stats(document: object) -> tuple[MlatStatus, float | None, int | None]:
    """Normalize one statistics document: the status, outlier %, and its own time."""
    doc: dict[str, Any] = document if isinstance(document, dict) else {}
    written_s = number(doc.get("now"))
    status = MlatStatus(
        peers=count(doc.get("peer_count")),
        good_sync_pct=number(doc.get("good_sync_percentage_last_hour")),
        bad_sync_timeout_s=number(doc.get("bad_sync_timeout")),
        last_bad_sync_ms=_last_bad_sync_ms(doc.get("last_bad_sync"), written_s),
    )
    written_ms = None if written_s is None else int(written_s * 1000)
    return status, number(doc.get("outlier_percent")), written_ms


def beast_line_matcher(host: str, beast_port: int) -> Callable[[str], bool]:
    """A predicate selecting the Beast output transitions for one network."""
    port_marker = f"port {beast_port}"

    def match(line: str) -> bool:
        return _BEAST_MARKER in line and host in line and port_marker in line

    return match


def beast_connected(line: str) -> bool:
    """Whether a matched transition line is the connection opening."""
    return _ESTABLISHED in line


class UltrafeederProbe:
    """One ultrafeeder connector: MLAT over HTTP, ADS-B out from the logs."""

    __slots__ = (
        "_adsb_out",
        "_beast_port",
        "_client",
        "_container",
        "_docker",
        "_host",
        "_log_cursor_s",
        "_mlat_port",
        "_name",
        "_url",
        "_zero_peer_polls",
    )

    kind = "ultrafeeder"

    def __init__(
        self,
        name: str,
        *,
        url: str | None,
        host: str | None,
        mlat_port: int | None,
        beast_port: int | None,
        container: str | None,
        client: httpx.AsyncClient,
        docker: DockerClient | None,
    ) -> None:
        self._name = name
        self._url = url
        self._host = host
        self._mlat_port = mlat_port
        self._beast_port = beast_port
        self._container = container or "ultrafeeder"
        self._client = client
        self._docker = docker
        self._zero_peer_polls = 0
        self._adsb_out: AdsbOutStatus | None = None
        self._log_cursor_s: int | None = None

    @property
    def name(self) -> str:
        return self._name

    async def _read_mlat(
        self, now_ms: int
    ) -> tuple[FeederState | None, MlatStatus | None, float | None, str | None, bool]:
        """(state, status, outlier %, message, failed); state ``None`` = not configured."""
        if self._url is None or self._host is None or self._mlat_port is None:
            return None, None, None, None, False
        url = join_url(self._url, mlat_stats_path(self._host, self._mlat_port))
        try:
            document = await fetch_json(self._client, url)
        except FetchError as exc:
            self._zero_peer_polls = 0
            return FeederState.DOWN, None, None, f"MLAT client not reporting ({exc})", True
        status, outliers, written_ms = parse_mlat_stats(document)
        if written_ms is not None and now_ms - written_ms > MLAT_STALE_AFTER_MS:
            return FeederState.DOWN, status, outliers, "MLAT client statistics are stale", False
        if status.peers == 0:
            self._zero_peer_polls += 1
            if self._zero_peer_polls >= ZERO_PEER_TOLERANCE:
                return FeederState.DEGRADED, status, outliers, "MLAT has no peers", False
        else:
            self._zero_peer_polls = 0
        return FeederState.UP, status, outliers, None, False

    async def _read_adsb_out(self, now_ms: int) -> tuple[bool, bool]:
        """Refresh the Beast output state; (observed through Docker, read failed)."""
        if self._docker is None or self._host is None or self._beast_port is None:
            return False, False
        now_s = now_ms // 1000
        first = self._log_cursor_s is None
        lines = await self._docker.logs(
            self._container,
            since_s=None if first else (self._log_cursor_s or 0) - LOG_OVERLAP_S,
            tail=FIRST_READ_TAIL if first else NEXT_READ_TAIL,
            match=beast_line_matcher(self._host, self._beast_port),
        )
        if lines is None:
            return False, True
        self._log_cursor_s = now_s
        if lines:
            latest = lines[-1]
            since = latest.ts_ms
            current = self._adsb_out
            if (
                current is None
                or since is None
                or current.since_ms is None
                or (since >= current.since_ms)
            ):
                self._adsb_out = AdsbOutStatus(
                    connected=beast_connected(latest.text), since_ms=since
                )
        elif self._adsb_out is None:
            self._adsb_out = AdsbOutStatus(connected=None, since_ms=None)
        return True, False

    async def probe(self, now_ms: int) -> ProbeResult:
        """Read both signals and combine them. Never raises."""
        mlat_state, mlat, outliers, mlat_message, mlat_failed = await self._read_mlat(now_ms)
        via_docker, docker_failed = await self._read_adsb_out(now_ms)
        adsb_out = self._adsb_out if via_docker else None
        connected = adsb_out.connected if adsb_out is not None else None

        detail: dict[str, DetailValue] = {
            "host": self._host,
            "outlier_pct": outliers,
        }
        metrics: dict[str, MetricValue] = {
            "mlat_peers": mlat.peers if mlat is not None else None,
            "good_sync_pct": mlat.good_sync_pct if mlat is not None else None,
            "adsb_out_connected": None if connected is None else int(connected),
        }

        message: str | None
        if connected is False:
            state, message = FeederState.DOWN, "ADS-B output disconnected"
        elif mlat_state is None:
            state = FeederState.UP if connected else FeederState.UNKNOWN
            message = None if connected else "Nothing observable is configured"
        elif mlat_state is FeederState.UP:
            state, message = FeederState.UP, None
        elif connected:
            # Beast data is flowing; only the MLAT side is unwell.
            state, message = FeederState.DEGRADED, mlat_message
        else:
            state, message = mlat_state, mlat_message
        if docker_failed and message is None:
            message = "Docker socket unreachable; ADS-B output not observed"

        if via_docker:
            observability = Observability.DOCKER
        elif mlat_state is not None:
            observability = Observability.HTTP
        else:
            observability = Observability.NONE
        return ProbeResult(
            state=state,
            observability=observability,
            message=message,
            last_data_sent_ms=now_ms if connected else None,
            mlat=mlat,
            adsb_out=adsb_out,
            detail=detail,
            metrics=metrics,
            failed=mlat_failed or docker_failed,
        )


__all__ = [
    "FIRST_READ_TAIL",
    "MLAT_STALE_AFTER_MS",
    "NEXT_READ_TAIL",
    "ZERO_PEER_TOLERANCE",
    "UltrafeederProbe",
    "beast_connected",
    "beast_line_matcher",
    "mlat_stats_path",
    "parse_mlat_stats",
]
