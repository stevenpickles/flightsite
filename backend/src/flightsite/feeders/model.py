"""Feeder domain types — FlightSite's own vocabulary, no vendor's.

Every vendor module (:mod:`~flightsite.feeders.piaware`,
:mod:`~flightsite.feeders.fr24`, :mod:`~flightsite.feeders.ultrafeeder`,
:mod:`~flightsite.feeders.readsb`, :mod:`~flightsite.feeders.opensky`) turns
whatever its network's software publishes into a :class:`ProbeResult`, and
nothing above those modules sees anything else. The names here say what a
value *is* — ``dropped_samples``, ``max_range_nm``, ``peers`` — never which
field of which document happened to supply it
(``tests/feeders/test_field_isolation.py`` enforces the boundary).

Absence is a value, as everywhere in FlightSite (SPEC §39, ``docs/API.md``
§2.7): a metric a source does not publish is ``None``, never a zero, and a
signal FlightSite has no way to observe is :attr:`FeederState.UNKNOWN` with
:attr:`Observability.NONE`, never :attr:`FeederState.DOWN`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

#: A value a vendor module may put in a feeder's ``detail`` block: scalars only,
#: so the block serializes as-is and can never carry a nested document (and
#: with it an unreviewed vendor field) through to the API.
DetailValue = str | int | float | bool | None

#: A value in a sample's ``metrics`` block. Numbers only — these are chart
#: series, and ``None`` is a gap, not a zero.
MetricValue = int | float | None


class FeederState(StrEnum):
    """What a feeder is doing, as far as FlightSite can tell.

    ``unknown`` is not a softer ``down``: it is "FlightSite cannot see this" —
    no Docker socket for a log-only feed, a statistics block gone quiet, a
    link-only entry. A feeder is only ever ``down`` on positive evidence that
    it is not feeding, and only after the service's two-poll debounce.
    """

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class Observability(StrEnum):
    """Where a feeder's current state was read from."""

    HTTP = "http"
    DOCKER = "docker"
    NONE = "none"


class FeederKind(StrEnum):
    """The probe kinds a configured entry can name (``docs/CONFIGURATION.md``)."""

    READSB = "readsb"
    PIAWARE = "piaware"
    FR24 = "fr24"
    ULTRAFEEDER = "ultrafeeder"
    OPENSKY_LOGS = "opensky_logs"
    DOCKER_HEALTH = "docker_health"
    LINK_ONLY = "link_only"


#: Kinds that can only be observed through the Docker socket. Without it they
#: read ``unknown`` / ``none``, never ``down`` (ADR-0017).
SOCKET_ONLY_KINDS: Final = frozenset({FeederKind.OPENSKY_LOGS, FeederKind.DOCKER_HEALTH})


@dataclass(frozen=True, slots=True)
class MlatStatus:
    """A multilateration client's link to its network's MLAT server."""

    peers: int | None = None
    good_sync_pct: float | None = None
    bad_sync_timeout_s: float | None = None
    last_bad_sync_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AdsbOutStatus:
    """Whether the ADS-B (Beast) output connection to a network is open."""

    connected: bool | None = None
    #: When the connection last changed state, as far as the logs say.
    since_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ReceiverUplink:
    """The receiver's own view of what it decodes and sends onward.

    The summary tiles at the top of the Feeders page. Every field is
    independently optional: a decoder that publishes half of them yields half
    a summary rather than none.
    """

    #: Bytes per second to *all* network connectors together, differenced
    #: between two polls of a cumulative counter.
    bytes_out_rate_per_s: float | None = None
    messages_per_min: int | None = None
    positions_per_min: int | None = None
    aircraft: int | None = None
    aircraft_with_pos: int | None = None
    #: Aircraft positioned by multilateration results coming back *in*.
    mlat_inbound: int | None = None
    dropped_samples: int | None = None
    max_range_nm: float | None = None
    gain_db: float | None = None
    signal_db: float | None = None
    noise_db: float | None = None
    uptime_s: float | None = None
    updated_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One probe's reading of one feeder — never an exception.

    ``state`` is the *raw* reading. The service, not the probe, owns the
    two-poll debounce before ``down`` and the episodes a committed change
    produces, so a probe only has to say what it sees right now.

    ``failed`` marks a genuine poll failure — an unreachable endpoint, a
    malformed document — which is what ``feeder_poll_failures`` counts. A
    source that answered and said "offline" is a successful poll of a down
    feeder, and is not a failure.
    """

    state: FeederState
    observability: Observability
    message: str | None = None
    last_data_sent_ms: int | None = None
    mlat: MlatStatus | None = None
    adsb_out: AdsbOutStatus | None = None
    detail: Mapping[str, DetailValue] = field(default_factory=dict)
    metrics: Mapping[str, MetricValue] = field(default_factory=dict)
    receiver: ReceiverUplink | None = None
    failed: bool = False


@dataclass(frozen=True, slots=True)
class FeederStatus:
    """A feeder's committed, debounced state — one card on the Feeders page."""

    name: str
    label: str
    kind: str
    state: FeederState
    observability: Observability
    #: When the current committed state began; ``None`` before the first poll.
    since_ms: int | None
    last_polled_ms: int | None
    last_success_ms: int | None
    last_data_sent_ms: int | None
    message: str | None
    mlat: MlatStatus | None
    adsb_out: AdsbOutStatus | None
    detail: Mapping[str, DetailValue]
    web_url: str | None
    #: Whether a stats link exists — never the link itself.
    stats_link: bool


@dataclass(frozen=True, slots=True)
class FeederSample:
    """One stored reading of one feeder (``docs/DATA_MODEL.md`` §6.6)."""

    feeder: str
    ts_ms: int
    state: FeederState
    metrics: Mapping[str, MetricValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeederEpisode:
    """A span of one committed state for one feeder.

    ``ended_ms`` is ``None`` while the episode is the feeder's current state.
    The transition listener sees every episode twice: once as it opens
    (``ended_ms is None``) and once as it closes, so a consumer reacting to
    "went down" and "came back" needs no memory of its own.
    """

    feeder: str
    started_ms: int
    state: FeederState
    ended_ms: int | None = None

    @property
    def open(self) -> bool:
        """True while this is the feeder's current state."""
        return self.ended_ms is None


__all__ = [
    "SOCKET_ONLY_KINDS",
    "AdsbOutStatus",
    "DetailValue",
    "FeederEpisode",
    "FeederKind",
    "FeederSample",
    "FeederState",
    "FeederStatus",
    "MetricValue",
    "MlatStatus",
    "Observability",
    "ProbeResult",
    "ReceiverUplink",
]
