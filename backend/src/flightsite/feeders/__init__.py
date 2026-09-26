"""Feeder status: every network the receiver feeds, and how it is doing.

Slice 077 (issue #215, ADR-0017). The owner's receiver streams to several
networks — FlightAware, FlightRadar24, ADS-B Exchange, AeroDataBox, OpenSky —
each through its own software with its own idea of a status document. This
package reads each of them, reduces them to one vocabulary
(:mod:`~flightsite.feeders.model`), keeps a state machine and a short history
per feeder, and serves ``GET /api/v1/feeders`` (``docs/API.md`` §3.12).

Module map:

=========================================== ==================================================
Module                                      Responsibility
=========================================== ==================================================
:mod:`~flightsite.feeders.model`            domain types; absence as a value
:mod:`~flightsite.feeders.protocol`         the probe seam and the settings shape read
:mod:`~flightsite.feeders.fetch`            bounded JSON fetches, shared coercions
:mod:`~flightsite.feeders.docker`           read-only Docker Engine API client; ``docker_health``
:mod:`~flightsite.feeders.readsb`           the receiver's uplink (``readsb``)
:mod:`~flightsite.feeders.piaware`          FlightAware (``piaware``)
:mod:`~flightsite.feeders.fr24`             FlightRadar24 (``fr24``)
:mod:`~flightsite.feeders.ultrafeeder`      ultrafeeder connectors: MLAT + ADS-B out
:mod:`~flightsite.feeders.opensky`          OpenSky's logged statistics (``opensky_logs``)
:mod:`~flightsite.feeders.repository`       ``feeder_episodes`` / ``feeder_samples`` (§6.6)
:mod:`~flightsite.feeders.service`          poller, state machine, flush, retention, report
=========================================== ==================================================

Two boundaries, both enforced by ``tests/feeders/test_field_isolation.py``:
each vendor module is the only place that knows its vendor's field names, and
only :mod:`~flightsite.feeders.repository` contains SQL.

Secrets never leave through here: stats URLs are read only by
:meth:`FeederService.stats_url` for the internal redirect, and every vendor
module builds its ``detail`` from an allowlist, so an identity field (FR24's
sharing key, the receiver's coordinates, FlightAware's site URL) is never
copied in the first place.
"""

from __future__ import annotations

from flightsite.feeders.docker import ContainerState, DockerClient, DockerFactory, LogLine
from flightsite.feeders.model import (
    AdsbOutStatus,
    FeederEpisode,
    FeederKind,
    FeederSample,
    FeederState,
    FeederStatus,
    MlatStatus,
    Observability,
    ProbeResult,
    ReceiverUplink,
)
from flightsite.feeders.protocol import (
    FeederEntryLike,
    FeederProbe,
    FeederSettingsLike,
    LocalPageLike,
    ProbeContext,
    ProbeFactory,
)
from flightsite.feeders.repository import FeederRepository
from flightsite.feeders.service import (
    HISTORY_WINDOWS,
    POLL_FAILURES_COUNTER,
    DockerSocketStatus,
    FeederEntry,
    FeederService,
    HistoryWindow,
    LocalPage,
    TransitionListener,
    build_probe,
    empty_report,
)

__all__ = [
    "HISTORY_WINDOWS",
    "POLL_FAILURES_COUNTER",
    "AdsbOutStatus",
    "ContainerState",
    "DockerClient",
    "DockerFactory",
    "DockerSocketStatus",
    "FeederEntry",
    "FeederEntryLike",
    "FeederEpisode",
    "FeederKind",
    "FeederProbe",
    "FeederRepository",
    "FeederSample",
    "FeederService",
    "FeederSettingsLike",
    "FeederState",
    "FeederStatus",
    "HistoryWindow",
    "LocalPage",
    "LocalPageLike",
    "LogLine",
    "MlatStatus",
    "Observability",
    "ProbeContext",
    "ProbeFactory",
    "ProbeResult",
    "ReceiverUplink",
    "TransitionListener",
    "build_probe",
    "empty_report",
]
