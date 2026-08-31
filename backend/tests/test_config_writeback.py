"""Write-back tests: atomicity, stability, and secret separation on disk."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from flightsite.config import ConfigError, ConfigStore, atomic_write_text

from .conftest import SECRET_SENTINEL


def test_saved_config_is_valid_yaml_with_a_comment_header(store: ConfigStore) -> None:
    store.save(store.load())

    text = store.config_path.read_text(encoding="utf-8")
    assert text.startswith("# FlightSite configuration")

    parsed = yaml.safe_load(text)
    assert parsed["units"] == "aviation"
    assert parsed["receiver"]["port"] == 8080


def test_saved_config_round_trips_through_load(store: ConfigStore) -> None:
    settings = store.apply_update(
        {
            "units": "metric",
            "timezone": "Europe/London",
            "location": {"latitude": 51.5, "longitude": -0.12, "site_name": "London"},
            "alerts": {"enabled_templates": ["military", "emergency-squawk"]},
        }
    )

    reloaded = ConfigStore(store.data_dir).load()

    assert reloaded.model_dump() == settings.model_dump()
    assert reloaded.location.site_name == "London"
    assert reloaded.alerts.enabled_templates == ["military", "emergency-squawk"]


def test_write_back_output_is_stable_across_repeated_saves(store: ConfigStore) -> None:
    store.save(store.load())
    first = store.config_path.read_text(encoding="utf-8")

    for _ in range(3):
        store.save(ConfigStore(store.data_dir).load())

    assert store.config_path.read_text(encoding="utf-8") == first


def test_write_back_uses_lf_line_endings(store: ConfigStore) -> None:
    store.save(store.load())

    assert b"\r\n" not in store.config_path.read_bytes()


def test_write_back_creates_no_leftover_temp_files(store: ConfigStore) -> None:
    store.save(store.load())
    store.save(store.load())

    assert sorted(p.name for p in store.data_dir.iterdir()) == ["config.yaml"]


@pytest.mark.parametrize("failing_call", ["os.fsync", "os.replace"])
def test_atomic_write_leaves_the_original_intact_when_writing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_call: str
) -> None:
    """Injected failure before and after the content is on disk: the original survives."""
    directory = tmp_path / "atomic"
    directory.mkdir()
    target = directory / "config.yaml"
    original = "# original\nunits: aviation\n"
    target.write_text(original, encoding="utf-8")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected write failure")

    monkeypatch.setattr(f"flightsite.config.loader.{failing_call}", explode)

    with pytest.raises(OSError, match="injected write failure"):
        atomic_write_text(target, "units: metric\n")

    assert target.read_text(encoding="utf-8") == original
    assert sorted(p.name for p in directory.iterdir()) == ["config.yaml"]


def test_apply_update_leaves_files_intact_when_the_write_fails(
    store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.apply_update({"units": "metric"})
    before = store.config_path.read_text(encoding="utf-8")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected write failure")

    monkeypatch.setattr("flightsite.config.loader.os.replace", explode)

    with pytest.raises(OSError, match="injected write failure"):
        store.apply_update({"units": "aviation"})

    assert store.config_path.read_text(encoding="utf-8") == before
    assert ConfigStore(store.data_dir).load().units == "metric"


def test_failed_update_leaves_config_and_running_settings_untouched(store: ConfigStore) -> None:
    store.apply_update({"display_radius_nm": 300.0})
    before = store.config_path.read_text(encoding="utf-8")

    with pytest.raises(ValidationError):
        store.apply_update({"display_radius_nm": -1.0})

    assert store.config_path.read_text(encoding="utf-8") == before
    assert store.load().display_radius_nm == 300.0


def test_unknown_key_in_update_is_rejected_before_writing(store: ConfigStore) -> None:
    store.save(store.load())
    before = store.config_path.read_text(encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown configuration key"):
        store.apply_update({"displayradius": 100})

    assert store.config_path.read_text(encoding="utf-8") == before


def test_partial_update_preserves_unrelated_settings(store: ConfigStore) -> None:
    store.apply_update({"units": "metric", "receiver": {"host": "readsb.lan"}})

    settings = store.apply_update({"receiver": {"port": 8081}})

    assert settings.units == "metric"
    assert settings.receiver.host == "readsb.lan"
    assert settings.receiver.port == 8081


def test_secrets_are_never_written_to_config_yaml(store: ConfigStore) -> None:
    store.apply_update({"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}})

    config_text = store.config_path.read_text(encoding="utf-8")
    assert SECRET_SENTINEL not in config_text
    assert "aerodatabox_api_key" not in config_text
    assert yaml.safe_load(config_text)["enrichment"] == {"aerodatabox_enabled": False}


def test_secrets_are_written_only_to_secrets_yaml(store: ConfigStore) -> None:
    store.apply_update({"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}})

    stored = yaml.safe_load(store.secrets_path.read_text(encoding="utf-8"))
    assert stored == {"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}}

    reloaded = ConfigStore(store.data_dir).load().enrichment.aerodatabox_api_key
    assert reloaded is not None
    assert reloaded.get_secret_value() == SECRET_SENTINEL


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file modes are not meaningful on Windows"
)
def test_secrets_file_is_owner_only(store: ConfigStore) -> None:
    store.apply_update({"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}})

    mode = stat.S_IMODE(os.stat(store.secrets_path).st_mode)
    assert mode == 0o600


def test_clearing_the_last_secret_removes_the_secrets_file(store: ConfigStore) -> None:
    store.apply_update({"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}})
    assert store.secrets_path.exists()

    store.apply_update({"enrichment": {"aerodatabox_api_key": None}})

    assert not store.secrets_path.exists()
    assert ConfigStore(store.data_dir).load().enrichment.aerodatabox_api_key is None


def test_saving_without_any_secret_writes_no_secrets_file(store: ConfigStore) -> None:
    store.apply_update({"units": "metric"})

    assert not store.secrets_path.exists()


def test_environment_still_outranks_a_written_value(
    store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLIGHTSITE_RECEIVER__PORT", "9999")

    settings = store.apply_update({"receiver": {"port": 8081}})

    assert settings.receiver.port == 9999
    assert ConfigStore(store.data_dir).load().receiver.port == 9999


def test_save_creates_a_missing_data_directory(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "nested" / "data")

    store.save(store.load())

    assert store.config_path.exists()
