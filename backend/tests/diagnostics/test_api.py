"""``GET /api/v1/diagnostics`` against a real application (``docs/API.md`` §3.10).

The centrepiece is :func:`test_every_spec_67_item_is_present`, which walks the
SPEC §67 sentence item by item. The roadmap's acceptance criterion is "every
§67 item present with sensible degraded-state rendering", and a checklist the
spec can be diffed against is the only version of that assertion which stays
honest as the payload grows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flightsite import __version__
from flightsite.app import create_app
from flightsite.counters import KNOWN_COUNTERS


@pytest.fixture
def client(isolated_data_dir: Path) -> TestClient:
    return TestClient(create_app(isolated_data_dir))


@pytest.fixture
def payload(client: TestClient) -> dict[str, Any]:
    with client as opened:
        response = opened.get("/api/v1/diagnostics")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _at(payload: dict[str, Any], path: str) -> Any:
    """Read a dotted path, failing with the path that was missing."""
    node: Any = payload
    for part in path.split("."):
        assert isinstance(node, dict), f"{path}: {part} is not an object"
        assert part in node, f"{path}: missing {part!r}"
        node = node[part]
    return node


#: SPEC §67, sentence by sentence, mapped to where the payload answers it.
SPEC_67_ITEMS: tuple[tuple[str, str], ...] = (
    ("decoder connection state", "decoder.state"),
    ("last successful aircraft update", "live.last_aircraft_update"),
    ("database health", "database.quick_check.healthy"),
    ("database size", "database.storage.database_bytes"),
    ("useful row counts", "database.row_counts.aircraft"),
    ("free disk space", "database.storage.disk_free_bytes"),
    ("backend uptime", "uptime.backend_s"),
    ("backend version", "versions.backend"),
    ("frontend version", "versions.frontend"),
    ("metadata database age", "metadata.age_s"),
    ("notification permission/status", "notifications.configured_enabled"),
    ("recent ingestion errors", "recent_errors.ingestion"),
    ("recent database errors", "recent_errors.database"),
    ("enrichment failures", "enrichment.failures"),
    ("WebSocket issues", "websocket.disconnects"),
)


@pytest.mark.parametrize(("item", "path"), SPEC_67_ITEMS, ids=[i for i, _ in SPEC_67_ITEMS])
def test_every_spec_67_item_is_present(payload: dict[str, Any], item: str, path: str) -> None:
    """Each SPEC §67 item has a home in the payload, even on a bare install."""
    _at(payload, path)


class TestPayloadShape:
    def test_the_response_validates_against_the_published_schema(
        self, payload: dict[str, Any]
    ) -> None:
        """``extra="forbid"`` means a serializer that drifted would 500, not pass."""
        assert payload["status"] in {"ok", "degraded", "down"}
        assert payload["generated_at"].endswith("Z")

    def test_versions_report_the_running_build(self, payload: dict[str, Any]) -> None:
        assert payload["versions"]["backend"] == __version__
        assert payload["versions"]["api"] == "v1"

    def test_the_schema_revision_is_reported(self, payload: dict[str, Any]) -> None:
        """A migrated database knows which revision it is on."""
        assert payload["versions"]["schema_revision"]

    def test_every_known_counter_is_exposed(self, payload: dict[str, Any]) -> None:
        assert set(payload["counters"]) == set(KNOWN_COUNTERS)

    def test_row_counts_cover_the_curated_tables(self, payload: dict[str, Any]) -> None:
        counts = payload["database"]["row_counts"]
        assert set(counts) >= {"aircraft", "sightings", "sighting_tracks", "airports"}
        assert all(value == 0 for value in counts.values())

    def test_storage_is_measured_from_the_real_database(self, payload: dict[str, Any]) -> None:
        storage = payload["database"]["storage"]
        assert storage["page_size"] > 0
        assert storage["disk_free_bytes"] > 0
        assert storage["database_bytes"] >= 0

    def test_recent_errors_carry_every_category(self, payload: dict[str, Any]) -> None:
        assert set(payload["recent_errors"]) == {
            "ingestion",
            "database",
            "enrichment",
            "websocket",
            "other",
        }

    def test_readiness_is_reported_alongside_the_rest(self, payload: dict[str, Any]) -> None:
        """So the health page does not have to call ``/ready`` separately."""
        assert payload["ready"] is True
        assert payload["subsystems"]["database"] is True

    def test_no_filesystem_path_is_exposed(self, client: TestClient) -> None:
        """``docs/SECURITY.md`` §9: the read-only API exposes no paths."""
        with client as opened:
            text = opened.get("/api/v1/diagnostics").text

        assert "/opt/flightsite" not in text
        assert ".sqlite3" not in text


class TestFirstRunInstall:
    def test_a_bare_install_reports_degraded_rather_than_failing(
        self, payload: dict[str, Any]
    ) -> None:
        """No receiver configured yet — the page must still render everything."""
        assert payload["status"] == "degraded"
        assert payload["decoder"]["state"] == "unconfigured"
        assert payload["metadata"]["age_s"] is None
        assert payload["live"]["last_aircraft_update"] is None

    def test_metadata_sources_are_listed_before_any_import(self, payload: dict[str, Any]) -> None:
        names = {source["source"] for source in payload["metadata"]["sources"]}
        assert {"mictronics", "faa", "airports"} <= names
        assert all(source["status"] == "never_run" for source in payload["metadata"]["sources"])


class TestErrorCapture:
    def test_a_logged_warning_appears_in_the_matching_category(self, client: TestClient) -> None:
        """End-to-end: the app wires the ring handler onto the root logger."""
        with client as opened:
            logging.getLogger("flightsite.ingest.readsb").warning(
                "decoder_poll_failed", extra={"url": "http://decoder.invalid"}
            )
            body = opened.get("/api/v1/diagnostics").json()

        captured = body["recent_errors"]["ingestion"]
        assert captured
        assert captured[0]["event"] == "decoder_poll_failed"
        assert captured[0]["level"] == "WARNING"
        assert "url=http://decoder.invalid" in (captured[0]["detail"] or "")

    def test_errors_from_unrelated_loggers_land_in_other(self, client: TestClient) -> None:
        """A novel failure stays visible rather than being dropped."""
        with client as opened:
            logging.getLogger("uvicorn.error").warning("something_unexpected")
            body = opened.get("/api/v1/diagnostics").json()

        assert any(e["event"] == "something_unexpected" for e in body["recent_errors"]["other"])

    def test_info_logging_does_not_fill_the_ring(self, client: TestClient) -> None:
        with client as opened:
            logging.getLogger("flightsite.ingest.readsb").info("routine_poll")
            body = opened.get("/api/v1/diagnostics").json()

        assert body["recent_errors"]["ingestion"] == []


class TestHealthEndpointStillWorks:
    def test_the_liveness_endpoint_is_unchanged(self, client: TestClient) -> None:
        """Diagnostics is additive: ``/health`` stays a cheap liveness probe."""
        with client as opened:
            body = opened.get("/api/v1/health").json()

        assert body["status"] == "ok"
        assert "recent_errors" not in body
