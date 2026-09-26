"""Demo stand-ins for the Feeders page (SPEC §76, slice 077).

Demo mode runs the full stack with no decoder and no internet, and that has
to include the Feeders page: the e2e and visual suites drive it on the demo
stack. So this module supplies everything the feeder service needs to run
with nothing behind it —

* :func:`demo_probes` — what the application passes as the service's
  ``probes`` in demo mode: a stand-in per configured entry, or, on an install
  with none configured (the usual demo), the six reference-shaped entries of
  :data:`DEMO_ENTRIES` (a receiver, FlightAware, FR24, ADS-B Exchange,
  AeroDataBox, OpenSky). Each stand-in carries its ``entry`` and a public
  network landing page as its stats link — nobody's account — and the list
  carries :data:`DEMO_LOCAL_PAGES`, so the whole page renders with nothing
  configured;
* :func:`demo_probe` — the same stand-ins as a
  :data:`~flightsite.feeders.protocol.ProbeFactory`, and
  :func:`demo_feeder_settings` / :func:`demo_docker_client` for building a
  service from settings instead.

Every value is a pure function of the clock and the feeder's name, so two
runs at the same instant agree and a visual snapshot is reproducible. Two
behaviours are scripted because the page exists to show them:

* **FR24 drops out for three minutes in every twenty** (:data:`FR24_OUTAGE_S`
  of every :data:`FR24_CYCLE_S`), so the timeline has a gap, the card goes
  ``down`` after the debounce, and the activity feed gets an offline/restored
  pair.
* **AeroDataBox's MLAT peers flap between 0 and 1**, as the real server does,
  never for long enough to cross the zero-peer tolerance — the chip shows the
  flapping while the feeder stays ``up``.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from pydantic import SecretStr

from flightsite.feeders.docker import DockerClient
from flightsite.feeders.model import (
    AdsbOutStatus,
    FeederKind,
    FeederState,
    MlatStatus,
    Observability,
    ProbeResult,
    ReceiverUplink,
)
from flightsite.feeders.protocol import FeederEntryLike, FeederProbe, ProbeContext
from flightsite.feeders.service import FeederEntry, LocalPage

#: FR24's scripted outage: this many seconds of every cycle.
FR24_OUTAGE_S: Final = 180
FR24_CYCLE_S: Final = 1200

#: AeroDataBox's peers alternate 1 and 0 on this period (two polls of zero at
#: the default interval — under the three-poll tolerance).
PEER_FLAP_S: Final = 30

#: Placeholder socket path the demo settings name. Never opened.
DEMO_DOCKER_SOCKET: Final = "demo://docker"

#: When the demo "receiver" notionally started, for uptime figures.
_DEMO_BOOT_S: Final = 1_790_000_000

DEMO_ENTRIES: Final[tuple[FeederEntry, ...]] = (
    FeederEntry(
        name="receiver",
        label="Receiver (readsb)",
        kind=FeederKind.READSB,
        url="http://demo.invalid:8080/",
        web_url="http://demo.invalid:8080/",
    ),
    FeederEntry(
        name="flightaware",
        label="FlightAware",
        kind=FeederKind.PIAWARE,
        url="http://demo.invalid:8081/status.json",
        web_url="http://demo.invalid:8081/",
    ),
    FeederEntry(
        name="fr24",
        label="FlightRadar24",
        kind=FeederKind.FR24,
        url="http://demo.invalid:8754/monitor.json",
        web_url="http://demo.invalid:8754/",
    ),
    FeederEntry(
        name="adsbx",
        label="ADS-B Exchange",
        kind=FeederKind.ULTRAFEEDER,
        url="http://demo.invalid:8080/",
        host="feed.adsbexchange.com",
        mlat_port=31090,
        beast_port=30004,
        container="ultrafeeder",
    ),
    FeederEntry(
        name="aerodatabox",
        label="AeroDataBox",
        kind=FeederKind.ULTRAFEEDER,
        url="http://demo.invalid:8080/",
        host="feed.aerodatabox.com",
        mlat_port=31090,
        beast_port=30004,
        container="ultrafeeder",
    ),
    FeederEntry(
        name="opensky",
        label="OpenSky Network",
        kind=FeederKind.OPENSKY_LOGS,
        container="opensky",
    ),
)

DEMO_LOCAL_PAGES: Final[tuple[LocalPage, ...]] = (
    LocalPage(label="tar1090", url="http://demo.invalid:8080/"),
    LocalPage(label="graphs1090", url="http://demo.invalid:8080/graphs1090/"),
    LocalPage(label="SkyAware", url="http://demo.invalid:8081/"),
    LocalPage(label="FR24 feeder", url="http://demo.invalid:8754/"),
)


@dataclass(frozen=True, slots=True)
class DemoFeederSettings:
    """A ``feeders`` section for demo mode; satisfies ``FeederSettingsLike``."""

    poll_interval_s: float = 15.0
    docker_socket: str | None = DEMO_DOCKER_SOCKET
    entries: Sequence[FeederEntry] = DEMO_ENTRIES
    local_pages: Sequence[LocalPage] = DEMO_LOCAL_PAGES
    #: Empty: every demo stand-in carries its own public stats link.
    stats_urls: Mapping[str, SecretStr] = field(default_factory=dict)


def demo_feeder_settings() -> DemoFeederSettings:
    """The demo's feeder configuration."""
    return DemoFeederSettings()


class _DemoDockerClient(DockerClient):
    """A Docker client that answers without a socket. Only :meth:`ping` is used."""

    async def ping(self) -> bool:
        return True

    @property
    def reachable(self) -> bool | None:
        return True


def demo_docker_client(socket_path: str) -> DockerClient:
    """The demo :data:`~flightsite.feeders.docker.DockerFactory`."""
    return _DemoDockerClient(socket_path)


def _phase(name: str) -> float:
    """A stable per-feeder phase offset in [0, 2π)."""
    return (zlib.crc32(name.encode()) % 3600) / 3600 * 2 * math.pi


def _wave(now_ms: int, name: str, period_s: float) -> float:
    """A smooth value in [0, 1] cycling over ``period_s``."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * (now_ms / 1000) / period_s + _phase(name))


#: Public landing pages the demo links as "stats" — deliberately nobody's
#: account, so a demo click never leads to a real feeder's page.
DEMO_STATS_LINKS: Final[Mapping[str, str]] = {
    FeederKind.PIAWARE: "https://www.flightaware.com/adsb/",
    FeederKind.FR24: "https://www.flightradar24.com/",
    FeederKind.OPENSKY_LOGS: "https://opensky-network.org/",
    "adsbx": "https://www.adsbexchange.com/",
    "aerodatabox": "https://aerodatabox.com/",
}


def fr24_outage(now_ms: int) -> bool:
    """Whether the scripted FR24 outage is in progress at ``now_ms``."""
    return (now_ms // 1000) % FR24_CYCLE_S < FR24_OUTAGE_S


def aerodatabox_peers(now_ms: int) -> int:
    """AeroDataBox's flapping peer count at ``now_ms``."""
    return 1 if (now_ms // 1000 // PEER_FLAP_S) % 2 == 0 else 0


class DemoProbe:
    """A plausible, deterministic probe for any kind."""

    __slots__ = ("_entry",)

    def __init__(self, entry: FeederEntry) -> None:
        self._entry = entry

    @property
    def name(self) -> str:
        return self._entry.name

    @property
    def kind(self) -> str:
        return self._entry.kind

    @property
    def entry(self) -> FeederEntry:
        """The entry this stand-in answers for; the service adopts it if unconfigured."""
        return self._entry

    @property
    def stats_fallback(self) -> str | None:
        """A public landing page for the network — never an account page."""
        return DEMO_STATS_LINKS.get(self._entry.name) or DEMO_STATS_LINKS.get(self._entry.kind)

    async def probe(self, now_ms: int) -> ProbeResult:
        return demo_result(self._entry, now_ms)


def demo_result(entry: FeederEntry, now_ms: int) -> ProbeResult:
    """What the demo probe for ``entry`` reports at ``now_ms``."""
    kind, name = entry.kind, entry.name
    wave = _wave(now_ms, name, 3600)
    if kind == FeederKind.READSB:
        messages = int(24_000 + 14_000 * wave)
        uplink = ReceiverUplink(
            bytes_out_rate_per_s=round(1800 + 2400 * wave, 1),
            messages_per_min=messages,
            positions_per_min=int(messages * 0.18),
            aircraft=int(40 + 30 * wave),
            aircraft_with_pos=int(32 + 26 * wave),
            mlat_inbound=int(2 + 4 * wave),
            dropped_samples=0,
            max_range_nm=round(180 + 40 * wave, 1),
            gain_db=43.9,
            signal_db=round(-18 + 4 * wave, 1),
            noise_db=-31.2,
            uptime_s=float(now_ms // 1000 - _DEMO_BOOT_S),
            updated_ms=now_ms,
        )
        return ProbeResult(
            state=FeederState.UP,
            observability=Observability.HTTP,
            last_data_sent_ms=now_ms,
            detail={
                "uptime_s": uplink.uptime_s,
                "messages_per_min": messages,
                "aircraft_with_pos": uplink.aircraft_with_pos,
            },
            metrics={
                "bytes_out_rate_per_s": uplink.bytes_out_rate_per_s,
                "messages_per_min": messages,
                "positions_per_min": uplink.positions_per_min,
                "aircraft_with_pos": uplink.aircraft_with_pos,
                "mlat_inbound": uplink.mlat_inbound,
            },
            receiver=uplink,
        )
    if kind == FeederKind.PIAWARE:
        return ProbeResult(
            state=FeederState.UP,
            observability=Observability.HTTP,
            last_data_sent_ms=now_ms,
            detail={
                "version": "10.2",
                "cpu_temp_c": round(47 + 6 * wave, 1),
                "system_uptime_s": now_ms // 1000 - _DEMO_BOOT_S,
                "connection": "green",
                "service": "green",
                "radio": "green",
                "mlat": "green",
            },
            metrics={"cpu_temp_c": round(47 + 6 * wave, 1)},
        )
    if kind == FeederKind.FR24:
        outage = fr24_outage(now_ms)
        cycle_start_ms = (now_ms // 1000 // FR24_CYCLE_S) * FR24_CYCLE_S * 1000
        last_sent_ms = cycle_start_ms if outage else now_ms - 2000
        sent = 0 if outage else int(30 + 25 * wave)
        return ProbeResult(
            state=FeederState.DOWN if outage else FeederState.UP,
            observability=Observability.HTTP,
            message="Feed status: disconnected (demo outage)" if outage else None,
            last_data_sent_ms=last_sent_ms,
            detail={
                "status": "disconnected" if outage else "connected",
                "server": None if outage else "demo.fr24.invalid",
                "receiver_input": True,
                "aircraft_sent": sent,
                "messages": int(now_ms // 1000 % 10_000_000),
                "timing_source": "System",
                "version": "1.0.48-0",
            },
            metrics={"aircraft_sent": sent, "messages": None},
        )
    if kind == FeederKind.ULTRAFEEDER:
        flapping = name == "aerodatabox"
        peers = aerodatabox_peers(now_ms) if flapping else int(12 + 8 * wave)
        since_ms = (_DEMO_BOOT_S + 42) * 1000
        return ProbeResult(
            state=FeederState.UP,
            observability=Observability.DOCKER,
            last_data_sent_ms=now_ms,
            mlat=MlatStatus(
                peers=peers,
                good_sync_pct=round(82 + 15 * wave, 1),
                bad_sync_timeout_s=0.0,
                last_bad_sync_ms=None,
            ),
            adsb_out=AdsbOutStatus(connected=True, since_ms=since_ms),
            detail={"host": entry.host, "outlier_pct": round(1.5 * wave, 2)},
            metrics={
                "mlat_peers": peers,
                "good_sync_pct": round(82 + 15 * wave, 1),
                "adsb_out_connected": 1,
            },
        )
    if kind == FeederKind.OPENSKY_LOGS:
        online_s = now_ms // 1000 - _DEMO_BOOT_S
        rate = round(900 + 600 * wave, 1)
        return ProbeResult(
            state=FeederState.UP,
            observability=Observability.DOCKER,
            last_data_sent_ms=now_ms - (now_ms % 600_000),
            detail={
                "seconds_online": online_s,
                "availability_pct": 99.81,
                "disconnections": 3,
                "bytes_sent": int(online_s * rate),
                "statistics_at_ms": now_ms - (now_ms % 600_000),
            },
            metrics={"bytes_out_rate_per_s": rate, "availability_pct": 99.81, "disconnections": 3},
        )
    if kind == FeederKind.DOCKER_HEALTH:
        return ProbeResult(
            state=FeederState.UP,
            observability=Observability.DOCKER,
            detail={"container": entry.container or name, "container_health": "healthy"},
        )
    return ProbeResult(state=FeederState.UNKNOWN, observability=Observability.NONE)


def demo_probe(entry: FeederEntryLike, context: ProbeContext) -> FeederProbe:
    """The demo :data:`~flightsite.feeders.protocol.ProbeFactory`. Ignores the clients."""
    return DemoProbe(FeederEntry.of(entry))


class DemoProbes(list[DemoProbe]):
    """The demo's probe list, carrying the local pages the demo links to."""

    local_pages: Sequence[LocalPage] = DEMO_LOCAL_PAGES


def demo_probes(entries: Sequence[FeederEntryLike]) -> DemoProbes:
    """A stand-in per configured entry — or for :data:`DEMO_ENTRIES` when none are."""
    chosen: Sequence[FeederEntryLike] = entries or DEMO_ENTRIES
    return DemoProbes(DemoProbe(FeederEntry.of(entry)) for entry in chosen)


__all__ = [
    "DEMO_DOCKER_SOCKET",
    "DEMO_ENTRIES",
    "DEMO_LOCAL_PAGES",
    "DEMO_STATS_LINKS",
    "FR24_CYCLE_S",
    "FR24_OUTAGE_S",
    "PEER_FLAP_S",
    "DemoFeederSettings",
    "DemoProbe",
    "DemoProbes",
    "aerodatabox_peers",
    "demo_docker_client",
    "demo_feeder_settings",
    "demo_probe",
    "demo_probes",
    "demo_result",
    "fr24_outage",
]
