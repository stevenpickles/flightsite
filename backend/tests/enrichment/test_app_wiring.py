"""Enrichment's place in the application lifespan.

The claim being tested is a negative one, and it is the slice's most important:
a FlightSite with no AeroDataBox key must make **zero external calls**. So
these tests build the real app and assert on what it constructed and started,
rather than on what a service would do if asked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.enrichment import AeroDataBoxProvider, EnrichmentService
from tests.conftest import SECRET_SENTINEL


def write_config(data_dir: Path, **enrichment: object) -> None:
    """Write a ``config.yaml`` and ``secrets.yaml`` the loader will pick up."""
    (data_dir / "config.yaml").write_text(
        yaml.safe_dump({"enrichment": {"aerodatabox_enabled": enrichment["enabled"]}}),
        encoding="utf-8",
    )
    key = enrichment.get("key")
    if key is not None:
        (data_dir / "secrets.yaml").write_text(
            yaml.safe_dump({"enrichment": {"aerodatabox_api_key": key}}), encoding="utf-8"
        )


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app subscribes to nothing and opens no socket."""
    app = create_app(isolated_data_dir)

    service: EnrichmentService = app.state.enrichment
    assert isinstance(service, EnrichmentService)
    assert service.running is False
    assert service.lookups == 0


def test_a_stock_install_has_no_provider_at_all(isolated_data_dir: Path) -> None:
    """Zero external calls as a property of the object graph, not of luck."""
    app = create_app(isolated_data_dir)

    assert app.state.enrichment.enabled is False


def test_a_key_with_the_flag_unset_still_has_no_provider(isolated_data_dir: Path) -> None:
    """Holding a key is not consent to use it; SPEC §28 makes it opt-in."""
    write_config(isolated_data_dir, enabled=False, key=SECRET_SENTINEL)

    app = create_app(isolated_data_dir)

    assert app.state.enrichment.enabled is False


def test_the_flag_and_a_key_together_build_the_aerodatabox_provider(
    isolated_data_dir: Path,
) -> None:
    write_config(isolated_data_dir, enabled=True, key=SECRET_SENTINEL)

    app = create_app(isolated_data_dir)

    assert app.state.enrichment.enabled is True
    # Reaching for the provider itself rather than trusting `enabled`: the
    # point is *which* provider a key builds (ADR-0006 ships exactly one).
    provider = app.state.enrichment._provider
    assert isinstance(provider, AeroDataBoxProvider)


def test_the_flag_without_a_key_is_rejected_by_configuration(
    isolated_data_dir: Path,
) -> None:
    """The config model refuses the state, so the service never sees it."""
    write_config(isolated_data_dir, enabled=True)

    with pytest.raises(Exception, match="API key"):
        ConfigStore(isolated_data_dir).load()


def test_a_disabled_install_starts_and_stops_the_app_cleanly(
    isolated_data_dir: Path,
) -> None:
    """The lifespan runs the start/stop calls even with nothing to start."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert app.state.enrichment.running is False


def test_the_published_schema_documents_the_route_block(isolated_data_dir: Path) -> None:
    """``docs/API.md`` §2.6's shape, in the OpenAPI document it is served with.

    A stock install with enrichment off still publishes the key: §2.7 makes
    ``null`` the answer to "unknown", and §6 lets v1 add fields but never
    remove them, so the shape a client codes against does not depend on
    whether the user bought an API key.
    """
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]

    assert "route" in schemas["AircraftView"]["properties"]
    assert set(schemas["RouteView"]["properties"]) == {"origin", "destination"}
