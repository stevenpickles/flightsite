"""Internal config API tests: ``GET`` / ``PUT /api/internal/config``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import SECRET_MASK, ConfigStore

from .conftest import SECRET_SENTINEL


@pytest.fixture
def client(isolated_data_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(isolated_data_dir)) as test_client:
        yield test_client


def test_get_config_reports_first_run_and_defaults(client: TestClient) -> None:
    response = client.get("/api/internal/config")

    assert response.status_code == 200
    body = response.json()
    assert body["first_run"] is True
    assert body["config"]["units"] == "aviation"
    assert body["config"]["display_radius_nm"] == 250.0
    assert body["config"]["alert_radius_nm"] is None
    assert body["config"]["receiver"]["port"] == 8080
    assert body["secrets_set"] == {"enrichment.aerodatabox_api_key": False}


def test_put_config_persists_and_clears_first_run(
    client: TestClient, isolated_data_dir: Path
) -> None:
    response = client.put(
        "/api/internal/config",
        json={
            "units": "metric",
            "timezone": "Europe/London",
            "location": {"latitude": 51.5, "longitude": -0.12, "site_name": "London"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_run"] is False
    assert body["config"]["units"] == "metric"
    assert body["config"]["location"]["site_name"] == "London"

    on_disk = yaml.safe_load((isolated_data_dir / "config.yaml").read_text(encoding="utf-8"))
    assert on_disk["units"] == "metric"
    assert on_disk["location"]["latitude"] == 51.5

    assert client.get("/api/internal/config").json()["first_run"] is False


def test_put_config_applies_to_the_running_app(client: TestClient) -> None:
    assert client.app.state.settings.display_radius_nm == 250.0  # type: ignore[attr-defined]

    client.put("/api/internal/config", json={"display_radius_nm": 90.0})

    assert client.app.state.settings.display_radius_nm == 90.0  # type: ignore[attr-defined]


def test_put_config_round_trips_the_document_it_returned(client: TestClient) -> None:
    document = client.get("/api/internal/config").json()["config"]
    document["retention"]["high_res_metric_days"] = 21

    response = client.put("/api/internal/config", json=document)

    assert response.status_code == 200
    assert response.json()["config"] == document


def test_partial_put_preserves_unrelated_values(client: TestClient) -> None:
    client.put("/api/internal/config", json={"units": "metric", "display_radius_nm": 120.0})

    body = client.put("/api/internal/config", json={"display_radius_nm": 130.0}).json()

    assert body["config"]["units"] == "metric"
    assert body["config"]["display_radius_nm"] == 130.0


def test_empty_put_is_a_no_op_that_still_writes_the_file(client: TestClient) -> None:
    response = client.put("/api/internal/config", json={})

    assert response.status_code == 200
    assert response.json()["first_run"] is False


def test_secret_is_write_only_and_masked_on_read(
    client: TestClient, isolated_data_dir: Path
) -> None:
    put_body = client.put(
        "/api/internal/config",
        json={"enrichment": {"aerodatabox_enabled": True, "aerodatabox_api_key": SECRET_SENTINEL}},
    ).json()

    # The response that just accepted the secret must not echo it back.
    assert put_body["config"]["enrichment"]["aerodatabox_api_key"] == SECRET_MASK
    assert put_body["secrets_set"] == {"enrichment.aerodatabox_api_key": True}
    assert SECRET_SENTINEL not in json.dumps(put_body)

    get_response = client.get("/api/internal/config")
    assert SECRET_SENTINEL not in get_response.text
    assert get_response.json()["config"]["enrichment"]["aerodatabox_api_key"] == SECRET_MASK

    # The secret reached secrets.yaml and only secrets.yaml.
    assert SECRET_SENTINEL not in (isolated_data_dir / "config.yaml").read_text(encoding="utf-8")
    secrets = yaml.safe_load((isolated_data_dir / "secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["enrichment"]["aerodatabox_api_key"] == SECRET_SENTINEL


def test_resending_the_masked_secret_does_not_overwrite_it(
    client: TestClient, isolated_data_dir: Path
) -> None:
    client.put(
        "/api/internal/config",
        json={"enrichment": {"aerodatabox_enabled": True, "aerodatabox_api_key": SECRET_SENTINEL}},
    )

    document = client.get("/api/internal/config").json()["config"]
    document["units"] = "metric"
    response = client.put("/api/internal/config", json=document)

    assert response.status_code == 200
    assert response.json()["secrets_set"]["enrichment.aerodatabox_api_key"] is True
    secrets = yaml.safe_load((isolated_data_dir / "secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["enrichment"]["aerodatabox_api_key"] == SECRET_SENTINEL


def test_null_secret_clears_it(client: TestClient, isolated_data_dir: Path) -> None:
    client.put(
        "/api/internal/config",
        json={"enrichment": {"aerodatabox_enabled": True, "aerodatabox_api_key": SECRET_SENTINEL}},
    )

    body = client.put(
        "/api/internal/config",
        json={"enrichment": {"aerodatabox_enabled": False, "aerodatabox_api_key": None}},
    ).json()

    assert body["secrets_set"]["enrichment.aerodatabox_api_key"] is False
    assert not (isolated_data_dir / "secrets.yaml").exists()


def test_invalid_value_is_rejected_with_a_helpful_error(client: TestClient) -> None:
    response = client.put("/api/internal/config", json={"location": {"latitude": 120.0}})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("latitude" in str(error["loc"]) for error in detail)


def test_invalid_timezone_message_is_helpful(client: TestClient) -> None:
    response = client.put("/api/internal/config", json={"timezone": "Mars/Olympus_Mons"})

    assert response.status_code == 422
    assert "unknown IANA timezone" in json.dumps(response.json()["detail"])


def test_unknown_key_is_rejected(client: TestClient) -> None:
    response = client.put("/api/internal/config", json={"displayradius": 100})

    assert response.status_code == 422
    assert "unknown configuration key" in response.json()["detail"]


def test_rejected_update_does_not_change_stored_config(client: TestClient) -> None:
    client.put("/api/internal/config", json={"display_radius_nm": 120.0})

    client.put("/api/internal/config", json={"display_radius_nm": -5.0})

    assert client.get("/api/internal/config").json()["config"]["display_radius_nm"] == 120.0


def test_validation_errors_do_not_echo_the_rejected_secret(client: TestClient) -> None:
    """A bad payload must not hand the submitted secret back to the caller."""
    response = client.put(
        "/api/internal/config",
        json={
            "timezone": "Mars/Olympus_Mons",
            "enrichment": {"aerodatabox_api_key": SECRET_SENTINEL},
        },
    )

    assert response.status_code == 422
    assert SECRET_SENTINEL not in response.text


def test_internal_api_is_excluded_from_the_openapi_schema(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()

    assert "/api/v1/health" in schema["paths"]
    assert not any(path.startswith("/api/internal") for path in schema["paths"])


def test_saving_enabled_templates_creates_the_alert_rules(client: TestClient) -> None:
    """Issue #110, from the wizard's end of the wire.

    The install this simulates is the one that broke: the app started with no
    configuration, so ``AlertService.start`` instantiated nothing, and the user
    then chose their templates. Before slice 055 this assertion failed with an
    empty list — the rules appeared only after a backend restart.
    """
    assert client.get("/api/internal/alert-rules").json()["rules"] == []

    response = client.put(
        "/api/internal/config",
        json={"alerts": {"enabled_templates": ["military", "police"]}},
    )

    assert response.status_code == 200
    assert response.json()["config"]["alerts"]["enabled_templates"] == ["military", "police"]
    rules = client.get("/api/internal/alert-rules").json()["rules"]
    assert [rule["template_key"] for rule in rules] == ["military", "police"]


def test_a_save_that_does_not_mention_alerts_creates_no_rules(client: TestClient) -> None:
    """The apply step must be inert for the settings it is not about."""
    client.put("/api/internal/config", json={"units": "metric"})

    assert client.get("/api/internal/alert-rules").json()["rules"] == []


def test_a_deleted_shipped_rule_survives_a_later_config_save(client: TestClient) -> None:
    """The property the startup guard exists for, held across the new edge: a
    save that enables something else does not bring back what the user
    deleted."""
    client.put(
        "/api/internal/config",
        json={"alerts": {"enabled_templates": ["military", "watchlist"]}},
    )
    rules = client.get("/api/internal/alert-rules").json()["rules"]
    military = next(rule for rule in rules if rule["template_key"] == "military")
    assert client.delete(f"/api/internal/alert-rules/{military['id']}").status_code == 204

    client.put(
        "/api/internal/config",
        json={"alerts": {"enabled_templates": ["military", "watchlist", "government"]}},
    )

    remaining = client.get("/api/internal/alert-rules").json()["rules"]
    assert [rule["template_key"] for rule in remaining] == ["watchlist", "government"]


def test_saving_the_law_enforcement_alias_creates_the_police_rule(client: TestClient) -> None:
    """The upgrade path for an install whose ``config.yaml`` already carries the
    spelling the wizard used to send (issue #111)."""
    client.put(
        "/api/internal/config",
        json={"alerts": {"enabled_templates": ["law_enforcement"]}},
    )

    rules = client.get("/api/internal/alert-rules").json()["rules"]
    assert [rule["template_key"] for rule in rules] == ["police"]


def test_the_alias_is_stored_as_written_and_not_rewritten(
    client: TestClient, isolated_data_dir: Path
) -> None:
    """The alias is a read-time mapping, not a migration: nothing edits the
    user's file behind their back, and the corrected wizard fixes the spelling
    on the next save the user makes themselves."""
    client.put(
        "/api/internal/config",
        json={"alerts": {"enabled_templates": ["law_enforcement"]}},
    )

    on_disk = yaml.safe_load((isolated_data_dir / "config.yaml").read_text(encoding="utf-8"))
    assert on_disk["alerts"]["enabled_templates"] == ["law_enforcement"]


def test_an_unknown_template_key_does_not_fail_the_save(client: TestClient) -> None:
    """The rest of the configuration is already written and already live, so a
    key from another build cannot be allowed to turn the save into a 500."""
    response = client.put(
        "/api/internal/config",
        json={"alerts": {"enabled_templates": ["military", "no_such_template"]}},
    )

    assert response.status_code == 200
    rules = client.get("/api/internal/alert-rules").json()["rules"]
    assert [rule["template_key"] for rule in rules] == ["military"]


def test_app_state_carries_the_settings_and_store(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    assert isinstance(app.state.config_store, ConfigStore)
    assert app.state.config_store.data_dir == isolated_data_dir
    assert app.state.settings.data_dir == isolated_data_dir


def test_log_level_comes_from_config_with_env_override_winning(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_data_dir / "config.yaml").write_text("log_level: WARNING\n", encoding="utf-8")

    app = create_app(isolated_data_dir)
    assert app.state.settings.log_level == "WARNING"

    monkeypatch.setenv("FLIGHTSITE_LOG_LEVEL", "DEBUG")
    app = create_app(isolated_data_dir)
    assert app.state.settings.log_level == "DEBUG"


def test_metadata_section_defaults_opensky_to_off(client: TestClient) -> None:
    """ADR-0013: the licensing ambiguity makes this the operator's call.

    A fresh install must report the source disabled, so the Settings UI renders
    the toggle unchecked without needing to know a default of its own.
    """
    body = client.get("/api/internal/config").json()

    assert body["config"]["metadata"] == {"opensky_enabled": False}


def test_the_opensky_toggle_round_trips_through_the_config_api(
    client: TestClient, isolated_data_dir: Path
) -> None:
    response = client.put("/api/internal/config", json={"metadata": {"opensky_enabled": True}})

    assert response.status_code == 200
    assert response.json()["config"]["metadata"]["opensky_enabled"] is True
    assert (
        client.get("/api/internal/config").json()["config"]["metadata"]["opensky_enabled"] is True
    )

    on_disk = yaml.safe_load((isolated_data_dir / "config.yaml").read_text(encoding="utf-8"))
    assert on_disk["metadata"]["opensky_enabled"] is True

    client.put("/api/internal/config", json={"metadata": {"opensky_enabled": False}})
    assert (
        client.get("/api/internal/config").json()["config"]["metadata"]["opensky_enabled"] is False
    )


def test_the_opensky_toggle_survives_a_restart(isolated_data_dir: Path) -> None:
    """The setting is read at startup, so persistence is what makes it work."""
    with TestClient(create_app(isolated_data_dir)) as client:
        client.put("/api/internal/config", json={"metadata": {"opensky_enabled": True}})

    restarted = create_app(isolated_data_dir)

    assert restarted.state.settings.metadata.opensky_enabled is True
    assert "opensky" in restarted.state.metadata.registry


def test_the_opensky_toggle_introduces_no_secret(client: TestClient) -> None:
    """Unlike the enrichment toggle, this one gates no API key (SPEC §29)."""
    body = client.get("/api/internal/config").json()

    assert body["secrets_set"] == {"enrichment.aerodatabox_api_key": False}
