"""Load-order, data-directory resolution, and first-run tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.config import (
    DEFAULT_DATA_DIR,
    ConfigError,
    ConfigStore,
    Settings,
    load_settings,
    resolve_data_dir,
)


def write_yaml(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_resolve_data_dir_prefers_argument_then_env_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLIGHTSITE_DATA_DIR", "/from/env")
    assert resolve_data_dir("/explicit") == Path("/explicit")
    assert resolve_data_dir() == Path("/from/env")

    monkeypatch.delenv("FLIGHTSITE_DATA_DIR")
    assert resolve_data_dir() == DEFAULT_DATA_DIR


def test_missing_config_yields_defaults_and_first_run(store: ConfigStore) -> None:
    assert store.first_run is True

    settings = store.load()

    assert settings.units == "aviation"
    assert settings.timezone == "UTC"
    assert settings.display_radius_nm == 250.0
    assert settings.alert_radius_nm is None
    assert settings.receiver.port == 8080
    assert settings.receiver.poll_interval_s == 1.0
    assert (settings.sighting.stale_s, settings.sighting.remove_s, settings.sighting.close_s) == (
        15.0,
        60.0,
        600.0,
    )
    assert settings.retention.high_res_metric_days == 14
    assert settings.alerts.enabled_templates == []
    assert settings.location.is_configured is False
    assert settings.enrichment.aerodatabox_api_key is None


def test_first_run_clears_once_config_is_written(store: ConfigStore) -> None:
    assert store.first_run is True

    store.save(store.load())

    assert store.first_run is False
    assert store.config_path.exists()


def test_config_file_overrides_defaults(store: ConfigStore) -> None:
    write_yaml(
        store.config_path,
        "units: metric\ndisplay_radius_nm: 120\nreceiver:\n  host: readsb.lan\n  port: 8081\n",
    )

    settings = store.load()

    assert settings.units == "metric"
    assert settings.display_radius_nm == 120.0
    assert settings.receiver.host == "readsb.lan"
    assert settings.receiver.port == 8081
    # Unspecified keys keep their defaults rather than being reset.
    assert settings.receiver.path == "/data/aircraft.json"


def test_secrets_file_overrides_config_file(store: ConfigStore) -> None:
    write_yaml(store.config_path, "receiver:\n  port: 8081\n")
    write_yaml(
        store.secrets_path,
        "enrichment:\n  aerodatabox_api_key: from-secrets\n",
    )

    settings = store.load()

    assert settings.receiver.port == 8081
    assert settings.enrichment.aerodatabox_api_key is not None
    assert settings.enrichment.aerodatabox_api_key.get_secret_value() == "from-secrets"


def test_full_precedence_chain_defaults_config_secrets_env(
    store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defaults < config.yaml < secrets.yaml < FLIGHTSITE_* — all four layers."""
    write_yaml(
        store.config_path,
        "units: metric\ntimezone: Europe/London\nreceiver:\n  host: config-host\n  port: 8081\n",
    )
    write_yaml(
        store.secrets_path,
        "receiver:\n  port: 8082\nenrichment:\n  aerodatabox_api_key: from-secrets\n",
    )
    monkeypatch.setenv("FLIGHTSITE_RECEIVER__PORT", "8083")

    settings = store.load()

    # default layer: untouched by any file or variable
    assert settings.map.basemap == "dark-aviation"
    # config.yaml layer: beats the defaults
    assert settings.units == "metric"
    assert settings.timezone == "Europe/London"
    assert settings.receiver.host == "config-host"
    # secrets.yaml layer: beats config.yaml
    assert settings.enrichment.aerodatabox_api_key is not None
    # env layer: beats both files
    assert settings.receiver.port == 8083


def test_env_overrides_scalar_and_nested_file_values(
    store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_yaml(store.config_path, "display_radius_nm: 300\nreceiver:\n  host: config-host\n")
    monkeypatch.setenv("FLIGHTSITE_DISPLAY_RADIUS_NM", "175.5")
    monkeypatch.setenv("FLIGHTSITE_RECEIVER__HOST", "env-host")

    settings = store.load()

    assert settings.display_radius_nm == 175.5
    assert settings.receiver.host == "env-host"


def test_secret_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLIGHTSITE_ENRICHMENT__AERODATABOX_API_KEY", "from-env")

    settings = load_settings()

    assert settings.enrichment.aerodatabox_api_key is not None
    assert settings.enrichment.aerodatabox_api_key.get_secret_value() == "from-env"


def test_env_secret_beats_secrets_file(store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
    write_yaml(store.secrets_path, "enrichment:\n  aerodatabox_api_key: from-secrets\n")
    monkeypatch.setenv("FLIGHTSITE_ENRICHMENT__AERODATABOX_API_KEY", "from-env")

    settings = store.load()

    assert settings.enrichment.aerodatabox_api_key is not None
    assert settings.enrichment.aerodatabox_api_key.get_secret_value() == "from-env"


def test_unrelated_flightsite_env_vars_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLIGHTSITE_HOST/PORT bind uvicorn; they must not break settings loading."""
    monkeypatch.setenv("FLIGHTSITE_HOST", "0.0.0.0")
    monkeypatch.setenv("FLIGHTSITE_PORT", "9000")
    monkeypatch.setenv("FLIGHTSITE_LOG_DIR", "/var/log/flightsite")

    settings = load_settings()

    assert settings.receiver.port == 8080


def test_data_dir_is_recorded_but_never_serialized(store: ConfigStore) -> None:
    settings = store.load()

    assert settings.data_dir == store.data_dir
    assert "data_dir" not in settings.dump_public()
    assert "data_dir" not in settings.dump_for_file()


def test_data_dir_key_in_config_file_is_not_applied(store: ConfigStore) -> None:
    """The data directory is resolved from the environment, not from the file it contains."""
    write_yaml(store.config_path, "data_dir: /somewhere/else\n")

    settings = store.load()

    assert settings.data_dir == store.data_dir


def test_empty_config_file_is_treated_as_no_configuration(store: ConfigStore) -> None:
    write_yaml(store.config_path, "\n")

    settings = store.load()

    assert settings.units == "aviation"
    assert store.first_run is False


def test_unreadable_config_path_raises_config_error(store: ConfigStore) -> None:
    """A directory where config.yaml should be is a clear error, not a silent default."""
    store.config_path.mkdir(parents=True)

    with pytest.raises(ConfigError, match="could not read"):
        store.load()


def test_malformed_yaml_raises_config_error(store: ConfigStore) -> None:
    write_yaml(store.config_path, "receiver: [unclosed\n")

    with pytest.raises(ConfigError, match="not valid YAML"):
        store.load()


def test_non_mapping_config_raises_config_error(store: ConfigStore) -> None:
    write_yaml(store.config_path, "- just\n- a\n- list\n")

    with pytest.raises(ConfigError, match="mapping at the top level"):
        store.load()


def test_unknown_config_key_is_rejected_with_known_keys_listed(store: ConfigStore) -> None:
    write_yaml(store.config_path, "displayradius: 100\n")

    with pytest.raises(ConfigError) as excinfo:
        store.load()

    message = str(excinfo.value)
    assert "unknown configuration key 'displayradius'" in message
    assert "display_radius_nm" in message


def test_unknown_nested_config_key_is_rejected(store: ConfigStore) -> None:
    write_yaml(store.config_path, "receiver:\n  prt: 8080\n")

    with pytest.raises(ConfigError, match=r"receiver\.prt"):
        store.load()


EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config.example.yaml"


def test_repo_example_config_is_valid_and_matches_the_defaults(store: ConfigStore) -> None:
    """config.example.yaml documents the real defaults — it must load and agree."""
    write_yaml(store.config_path, EXAMPLE_CONFIG.read_text(encoding="utf-8"))

    from_example = store.load()

    store.config_path.unlink()
    defaults = store.load()

    assert from_example.dump_for_file() == defaults.dump_for_file()


def test_settings_can_be_constructed_without_any_files() -> None:
    """The model alone is usable — no filesystem access required."""
    settings = Settings()

    assert settings.units == "aviation"
    assert settings.notifications.critical is True
