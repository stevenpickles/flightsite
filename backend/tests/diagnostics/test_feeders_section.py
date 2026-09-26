"""The diagnostics ``feeders`` section and its place in the roll-up (slice 077).

Driven with a stub ``app.state`` like :mod:`tests.diagnostics.test_service`:
the report object is duck-typed (an object or a mapping with ``feeders`` and
``docker_socket``), so these tests describe the states rather than building a
real feeder service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from flightsite.api.schemas import DiagnosticsResponse
from flightsite.app import create_app
from flightsite.config import Settings
from flightsite.counters import KNOWN_COUNTERS, CounterRegistry
from flightsite.diagnostics import STATUS_DEGRADED, STATUS_OK
from flightsite.diagnostics.errors import FEEDERS, ErrorRing, category_for_logger
from flightsite.diagnostics.service import collect_diagnostics
from flightsite.ingest.health import AdapterHealth, HealthState

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)


class _State(StrEnum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class _Feeder:
    name: str
    state: _State


@dataclass
class _Report:
    feeders: list[_Feeder] = field(default_factory=list)
    docker_socket: str = "unset"


class _Service:
    def __init__(self, report: Any) -> None:
        self._report = report

    def report(self) -> Any:
        return self._report


@dataclass
class _Ingestion:
    def health(self) -> AdapterHealth:
        return AdapterHealth(state=HealthState.CONNECTED)


def _settings(names: list[str], *, socket: str | None = None) -> Settings:
    return Settings.model_validate(
        {
            "feeders": {
                "docker_socket": socket,
                "entries": [{"name": name, "label": name, "kind": "link_only"} for name in names],
            }
        }
    )


async def _collect(**state: Any) -> dict[str, Any]:
    state.setdefault("ingestion", _Ingestion())
    app = SimpleNamespace(state=SimpleNamespace(**state))
    return await collect_diagnostics(app, counters=CounterRegistry(), ring=ErrorRing(), now=NOW)  # type: ignore[arg-type]


async def test_no_feeders_configured_is_all_zeros_and_ok() -> None:
    payload = await _collect(settings=Settings())

    assert payload["feeders"] == {
        "configured": 0,
        "up": 0,
        "degraded": 0,
        "down": 0,
        "unknown": 0,
        "docker_socket": "unset",
    }
    assert payload["status"] == STATUS_OK


async def test_states_are_counted_from_the_report() -> None:
    report = _Report(
        feeders=[
            _Feeder("receiver", _State.UP),
            _Feeder("flightaware", _State.UP),
            _Feeder("fr24", _State.DEGRADED),
            _Feeder("opensky", _State.UNKNOWN),
        ],
        docker_socket="available",
    )
    payload = await _collect(
        settings=_settings(
            ["receiver", "flightaware", "fr24", "opensky"], socket="/var/run/d.sock"
        ),
        feeders=_Service(report),
    )

    assert payload["feeders"] == {
        "configured": 4,
        "up": 2,
        "degraded": 1,
        "down": 0,
        "unknown": 1,
        "docker_socket": "available",
    }
    # Degraded and unknown feeders inform; they do not move the banner.
    assert payload["status"] == STATUS_OK


async def test_a_down_feeder_degrades_the_install_but_never_takes_it_down() -> None:
    report = _Report(feeders=[_Feeder("fr24", _State.DOWN), _Feeder("adsbx", _State.DOWN)])
    payload = await _collect(settings=_settings(["fr24", "adsbx"]), feeders=_Service(report))

    assert payload["feeders"]["down"] == 2
    assert payload["status"] == STATUS_DEGRADED


async def test_a_mapping_report_and_plain_string_states_are_read_too() -> None:
    report = {"feeders": [{"name": "fr24", "state": "down"}], "docker_socket": "unreachable"}
    payload = await _collect(
        settings=_settings(["fr24"], socket="/var/run/docker.sock"), feeders=_Service(report)
    )

    assert payload["feeders"]["down"] == 1
    assert payload["feeders"]["docker_socket"] == "unreachable"


async def test_a_report_property_is_read_as_well_as_a_method() -> None:
    service = SimpleNamespace(report=_Report(feeders=[_Feeder("fr24", _State.UP)]))
    payload = await _collect(settings=_settings(["fr24"]), feeders=service)

    assert payload["feeders"]["up"] == 1


async def test_an_unpolled_service_reports_every_entry_unknown() -> None:
    payload = await _collect(settings=_settings(["a", "b", "c"]), feeders=_Service(None))

    assert payload["feeders"]["configured"] == 3
    assert payload["feeders"]["unknown"] == 3
    assert payload["status"] == STATUS_OK


async def test_no_feeder_service_at_all_still_answers() -> None:
    payload = await _collect(settings=_settings(["a"]))

    assert payload["feeders"]["unknown"] == 1


async def test_an_unset_socket_is_unset_whatever_the_report_says() -> None:
    report = _Report(docker_socket="available")
    payload = await _collect(settings=_settings([]), feeders=_Service(report))

    assert payload["feeders"]["docker_socket"] == "unset"


async def test_a_set_socket_is_available_until_the_service_says_otherwise() -> None:
    payload = await _collect(settings=_settings([], socket="/var/run/docker.sock"))

    assert payload["feeders"]["docker_socket"] == "available"


async def test_the_socket_path_is_never_published() -> None:
    payload = await _collect(settings=_settings([], socket="/srv/secret-place/docker.sock"))

    assert "secret-place" not in str(payload)


def test_feeder_loggers_have_their_own_error_category() -> None:
    assert category_for_logger("flightsite.feeders") == FEEDERS
    assert category_for_logger("flightsite.feeders.service") == FEEDERS
    assert category_for_logger("flightsite.feedersx") != FEEDERS


def test_the_poll_failure_counter_is_predeclared() -> None:
    assert "feeder_poll_failures" in KNOWN_COUNTERS
    CounterRegistry().increment("feeder_poll_failures")


def test_the_served_payload_validates_and_carries_the_section(isolated_data_dir: Path) -> None:
    (isolated_data_dir / "config.yaml").write_text(
        "feeders:\n  entries:\n    - {name: fr24, label: FR24, kind: link_only}\n",
        encoding="utf-8",
    )
    with TestClient(create_app(isolated_data_dir)) as client:
        body = client.get("/api/v1/diagnostics").json()

    DiagnosticsResponse.model_validate(body)
    assert body["feeders"]["configured"] == 1
    assert set(body["feeders"]) == {
        "configured",
        "up",
        "degraded",
        "down",
        "unknown",
        "docker_socket",
    }
    assert "feeders" in body["recent_errors"]


def test_stats_urls_never_reach_diagnostics(isolated_data_dir: Path) -> None:
    """``docs/SECURITY.md`` §3 for the new secret: neither config nor a log leaks it."""
    sentinel = "https://flightaware.com/adsb/stats/user/sentinel-stats-url-8e2b"
    (isolated_data_dir / "secrets.yaml").write_text(
        f'feeders:\n  stats_urls:\n    flightaware: "{sentinel}"\n', encoding="utf-8"
    )
    app = create_app(isolated_data_dir)
    with TestClient(app) as client:
        # A careless log line in the feeder package must be redacted on capture.
        logging.getLogger("flightsite.feeders.test").error("oops %s", sentinel)
        response = client.get("/api/v1/diagnostics")

    assert response.status_code == 200
    assert sentinel not in response.text
    assert "sentinel-stats-url-8e2b" not in response.text
    captured = response.json()["recent_errors"]["feeders"]
    assert captured, "the log record should have been captured under 'feeders'"
