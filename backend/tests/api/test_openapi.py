"""The published schema — ``docs/API.md`` §2.10.

A schema is only worth serving if it is accurate and if it covers exactly the
supported surface: the documented read-only endpoints, never the unsupported
internal one (ADR-0007, SPEC §74).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from flightsite.app import create_app


def schema() -> dict[str, Any]:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/openapi.json")
        assert response.status_code == 200
        document: dict[str, Any] = response.json()
        return document


def test_the_schema_is_served_under_the_versioned_prefix() -> None:
    # §2.10 puts the document beside what it describes, not at the server root.
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/openapi.json").status_code == 200
        assert client.get("/openapi.json").status_code == 404


def test_the_interactive_docs_are_served_under_the_versioned_prefix() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/docs").status_code == 200


def test_the_live_endpoints_are_documented() -> None:
    paths = schema()["paths"]

    assert "/api/v1/aircraft/current" in paths
    assert "/api/v1/receiver" in paths
    assert "/api/v1/health" in paths
    assert "/api/v1/ready" in paths


def test_the_history_endpoints_are_documented() -> None:
    paths = schema()["paths"]

    assert "/api/v1/aircraft" in paths
    assert "/api/v1/aircraft/{icao}" in paths


def test_the_history_row_and_detail_objects_are_described_by_components() -> None:
    components = schema()["components"]["schemas"]

    assert "AircraftHistoryRow" in components
    assert "AircraftDetail" in components
    assert "lifetime" in components["AircraftDetail"]["properties"]


def test_the_history_sort_keys_are_published() -> None:
    # §3.5's documented sort keys, in the schema rather than only in prose.
    operation = schema()["paths"]["/api/v1/aircraft"]["get"]
    sort_param = next(param for param in operation["parameters"] if param["name"] == "sort")

    assert set(sort_param["schema"]["enum"]) == {
        "registration",
        "icao",
        "type",
        "operator",
        "classification",
        "first_seen",
        "last_seen",
        "sighting_count",
        "closest_approach_nm",
        "max_range_nm",
    }


def test_the_internal_surface_is_absent() -> None:
    paths = schema()["paths"]

    assert not any(path.startswith("/api/internal") for path in paths)


def test_the_websocket_is_not_in_the_schema() -> None:
    # OpenAPI 3.1 has no vocabulary for WebSockets; the protocol lives in the
    # flightsite.api.ws module docstring instead.
    paths = schema()["paths"]

    assert not any("ws/live" in path for path in paths)


def test_the_aircraft_object_is_described_by_a_component() -> None:
    components = schema()["components"]["schemas"]

    assert "AircraftView" in components
    properties = components["AircraftView"]["properties"]
    for field in ("icao", "position_source", "state", "sighting_id", "provenance"):
        assert field in properties, field


def test_the_receiver_block_is_described_by_a_component() -> None:
    components = schema()["components"]["schemas"]

    assert "ReceiverInfo" in components
    assert "t0" in components["ReceiverInfo"]["properties"]


def test_the_position_source_vocabulary_is_published() -> None:
    # §2.8's canonical vocabulary, in the schema rather than only in prose.
    properties = schema()["components"]["schemas"]["AircraftView"]["properties"]

    assert set(properties["position_source"]["enum"]) == {"adsb", "mlat", "none", "other"}


def test_the_positioned_filter_is_documented() -> None:
    operation = schema()["paths"]["/api/v1/aircraft/current"]["get"]

    assert [parameter["name"] for parameter in operation["parameters"]] == ["positioned"]
