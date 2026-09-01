"""Diagnostics output provably contains no secrets (``docs/SECURITY.md`` §3).

``docs/SECURITY.md`` §3 lists this as an *enforced, tested* rule rather than an
aspiration, and ``docs/API.md`` §3.10 repeats it for this endpoint. The tests
here are deliberately adversarial: instead of checking that nothing happened to
put a secret into the payload, they push the sentinel key into the places a
leak would realistically come from — configuration, and a log record — and then
require that it cannot come back out of ``GET /api/v1/diagnostics``.

The first test is a guard. Every other assertion in this module would pass
vacuously if the sentinel never reached the running application, so that
possibility is checked explicitly rather than assumed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import Settings, secret_field_paths
from flightsite.diagnostics.errors import REDACTED, secrets_from_settings

from ..conftest import SECRET_SENTINEL


@pytest.fixture
def secret_app(isolated_data_dir: Path) -> FastAPI:
    """An application whose configured AeroDataBox key is the sentinel."""
    (isolated_data_dir / "secrets.yaml").write_text(
        f"enrichment:\n  aerodatabox_api_key: {SECRET_SENTINEL}\n", encoding="utf-8"
    )
    return create_app(isolated_data_dir)


def test_the_sentinel_secret_is_actually_loaded(secret_app: FastAPI) -> None:
    """Guard: every other test here proves nothing if the key never arrives."""
    settings: Settings = secret_app.state.settings

    key = settings.enrichment.aerodatabox_api_key
    assert key is not None
    assert key.get_secret_value() == SECRET_SENTINEL
    # And the collector can see it, which is what makes redaction possible.
    assert SECRET_SENTINEL in secrets_from_settings(settings)


def test_diagnostics_response_does_not_contain_the_secret(secret_app: FastAPI) -> None:
    """The whole serialized payload is searched, not a hand-picked subset."""
    with TestClient(secret_app) as client:
        response = client.get("/api/v1/diagnostics")

    assert response.status_code == 200
    assert SECRET_SENTINEL not in response.text


def test_a_secret_logged_by_mistake_cannot_reach_diagnostics(secret_app: FastAPI) -> None:
    """The adversarial case: something logs the key, and the ring captures it.

    This is what makes the guarantee *this slice's own* rather than one
    inherited from "secrets never reach logs". Redaction happens on the way
    into the ring, so even a record genuinely carrying the key is stored — and
    served — with the value replaced.
    """
    with TestClient(secret_app) as client:
        logging.getLogger("flightsite.enrichment.service").warning(
            "route_lookup_failed url=https://example.invalid/x?key=%s", SECRET_SENTINEL
        )
        response = client.get("/api/v1/diagnostics")

    captured = response.json()["recent_errors"]["enrichment"]
    # The record really was captured — otherwise the absence below is vacuous.
    assert any("route_lookup_failed" in entry["event"] for entry in captured)
    assert SECRET_SENTINEL not in response.text
    assert REDACTED in response.text


def test_a_secret_in_a_structured_log_field_is_redacted(secret_app: FastAPI) -> None:
    """Bound key/values are rendered into ``detail`` — and redacted there too."""
    with TestClient(secret_app) as client:
        logging.getLogger("flightsite.ingest.readsb").warning(
            "decoder_poll_failed", extra={"api_key": SECRET_SENTINEL}
        )
        response = client.get("/api/v1/diagnostics")

    captured = response.json()["recent_errors"]["ingestion"]
    details = " ".join(entry["detail"] or "" for entry in captured)
    assert "api_key=" in details
    assert SECRET_SENTINEL not in response.text
    assert REDACTED in details


def test_redaction_covers_every_secret_field_the_model_declares() -> None:
    """Secrets are found by type, so a future secret is covered automatically.

    :func:`secrets_from_settings` walks :func:`secret_field_paths` rather than a
    hand-maintained list, which is what makes the guarantee survive a slice
    that adds a second ``SecretStr``. This test fails loudly if that discovery
    ever stops working.
    """
    paths = secret_field_paths(Settings)
    assert ("enrichment", "aerodatabox_api_key") in paths

    settings = Settings()
    markers = []
    for index, path in enumerate(paths):
        node: object = settings
        for part in path[:-1]:
            node = getattr(node, part)
        marker = f"secret-{index}-b7f2e1"
        setattr(node, path[-1], marker)
        markers.append(marker)

    discovered = secrets_from_settings(settings)
    for marker in markers:
        assert marker in discovered


def test_the_endpoint_is_read_only(secret_app: FastAPI) -> None:
    """Diagnostics never mutates: only GET is routed."""
    with TestClient(secret_app) as client:
        assert client.post("/api/v1/diagnostics").status_code == 405
        assert client.delete("/api/v1/diagnostics").status_code == 405
