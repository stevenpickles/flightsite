"""Secret-leak tests (SPEC §29).

Each test puts the sentinel secret into the configuration and then searches an
output channel — repr, serialization, the config file, log records — for it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import structlog

from flightsite.config import SECRET_MASK, ConfigStore, Settings, secret_field_paths
from flightsite.config.models import _set_masked
from flightsite.logging import configure_logging

from .conftest import SECRET_SENTINEL


@pytest.fixture
def configured(store: ConfigStore) -> Settings:
    """Settings with the sentinel secret stored in ``secrets.yaml``."""
    store.secrets_path.write_text(
        f"enrichment:\n  aerodatabox_api_key: {SECRET_SENTINEL}\n", encoding="utf-8"
    )
    return store.load()


def test_the_sentinel_secret_is_actually_loaded(configured: Settings) -> None:
    """Guard: every other test here is vacuous if the secret never arrives."""
    assert configured.enrichment.aerodatabox_api_key is not None
    assert configured.enrichment.aerodatabox_api_key.get_secret_value() == SECRET_SENTINEL


def test_secret_fields_are_discovered_by_type(configured: Settings) -> None:
    assert secret_field_paths(Settings) == (("enrichment", "aerodatabox_api_key"),)


def test_repr_and_str_do_not_reveal_the_secret(configured: Settings) -> None:
    assert SECRET_SENTINEL not in repr(configured)
    assert SECRET_SENTINEL not in str(configured)
    assert SECRET_SENTINEL not in repr(configured.enrichment)
    assert SECRET_SENTINEL not in str(configured.enrichment.aerodatabox_api_key)
    assert SECRET_SENTINEL not in f"{configured!r} {configured!s}"


def test_model_dump_does_not_reveal_the_secret(configured: Settings) -> None:
    assert SECRET_SENTINEL not in str(configured.model_dump())
    assert SECRET_SENTINEL not in str(configured.model_dump(mode="json"))
    assert SECRET_SENTINEL not in configured.model_dump_json()


def test_dump_public_masks_the_secret(configured: Settings) -> None:
    public = configured.dump_public()

    assert public["enrichment"]["aerodatabox_api_key"] == SECRET_MASK
    assert SECRET_SENTINEL not in json.dumps(public)


def test_dump_public_reports_an_unset_secret_as_null(store: ConfigStore) -> None:
    public = store.load().dump_public()

    assert public["enrichment"]["aerodatabox_api_key"] is None


def test_dump_for_file_omits_the_secret_key_entirely(configured: Settings) -> None:
    """A mask written to config.yaml would be reloaded as if it were the key."""
    for_file = configured.dump_for_file()

    assert "aerodatabox_api_key" not in for_file["enrichment"]
    assert SECRET_SENTINEL not in json.dumps(for_file)
    assert SECRET_MASK not in json.dumps(for_file)


def test_secrets_state_reports_set_and_unset_without_the_value(
    store: ConfigStore, configured: Settings
) -> None:
    assert configured.secrets_state() == {"enrichment.aerodatabox_api_key": True}

    store.secrets_path.unlink()
    assert store.load().secrets_state() == {"enrichment.aerodatabox_api_key": False}


def test_written_config_yaml_never_contains_the_secret(
    store: ConfigStore, configured: Settings
) -> None:
    store.save(configured)

    assert SECRET_SENTINEL not in store.config_path.read_text(encoding="utf-8")


def test_secret_does_not_reach_the_logs(
    store: ConfigStore, configured: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Structured logs render the whole settings object at DEBUG without leaking."""
    configure_logging(level="DEBUG")
    logger = structlog.get_logger("test")

    logger.debug("settings_loaded", settings=configured, public=configured.dump_public())
    logger.info("enrichment", enrichment=configured.enrichment)
    logging.getLogger("stdlib").warning("settings=%s", configured)

    captured = capsys.readouterr()
    assert SECRET_SENTINEL not in captured.out
    assert SECRET_SENTINEL not in captured.err
    # ...and the log really did contain the settings, so the search was meaningful.
    assert "settings_loaded" in captured.out + captured.err


def test_secret_survives_a_config_save_that_does_not_touch_it(
    store: ConfigStore, configured: Settings
) -> None:
    store.apply_update({"units": "metric"})

    reloaded = ConfigStore(store.data_dir).load()
    assert reloaded.enrichment.aerodatabox_api_key is not None
    assert reloaded.enrichment.aerodatabox_api_key.get_secret_value() == SECRET_SENTINEL


def test_masked_value_in_an_update_leaves_the_stored_secret_alone(
    store: ConfigStore, configured: Settings
) -> None:
    """A client can send back the masked document it was given."""
    document = configured.dump_public()
    document["units"] = "metric"

    updated = store.apply_update(document)

    assert updated.units == "metric"
    assert updated.enrichment.aerodatabox_api_key is not None
    assert updated.enrichment.aerodatabox_api_key.get_secret_value() == SECRET_SENTINEL


def test_secret_is_not_in_any_file_in_the_data_directory_after_a_public_save(
    store: ConfigStore, configured: Settings
) -> None:
    store.secrets_path.unlink()
    store.save(store.load(overrides={"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}}))

    for path in store.data_dir.rglob("*"):
        if path.is_file():
            assert SECRET_SENTINEL not in _read(path)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize(
    "document",
    [{}, {"enrichment": {}}, {"enrichment": None}],
    ids=["no-section", "empty-section", "section-not-a-mapping"],
)
def test_masking_tolerates_a_document_missing_the_secret_path(
    document: dict[str, object],
) -> None:
    """Masking is a no-op on a partial dump rather than raising or inventing keys."""
    before = json.dumps(document, sort_keys=True)

    _set_masked(document, ("enrichment", "aerodatabox_api_key"), mask=SECRET_MASK)
    _set_masked(document, ("enrichment", "aerodatabox_api_key"), mask=None)

    assert json.dumps(document, sort_keys=True) == before
