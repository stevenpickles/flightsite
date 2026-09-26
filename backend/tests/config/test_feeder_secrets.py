"""``feeders.stats_urls`` — the first mapping of secrets (slice 077, SPEC §29).

Each stats URL usually embeds a feeder identity, so every channel that is
secret-safe for the scalar AeroDataBox key must be secret-safe for each value
of this mapping too: masking, ``config.yaml`` write-back, ``secrets.yaml``
round-trip, the mask-means-unchanged rule on ``PUT``, and the diagnostics
redaction list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import (
    SECRET_MASK,
    ConfigStore,
    Settings,
    iter_secret_values,
    secret_field_paths,
    strip_masked_secrets,
)
from flightsite.diagnostics.errors import secrets_from_settings

FA_URL = "https://flightaware.com/adsb/stats/user/sentinel-fa-user-5d1e#stats-99999"
FR24_URL = "https://www.flightradar24.com/account/feed-stats/?id=sentinel-fr24-7a3c"

SECRETS_YAML = f"""feeders:
  stats_urls:
    flightaware: "{FA_URL}"
    fr24: "{FR24_URL}"
"""


@pytest.fixture
def configured(store: ConfigStore) -> Settings:
    store.secrets_path.write_text(SECRETS_YAML, encoding="utf-8")
    return store.load()


def test_the_sentinel_urls_are_actually_loaded(configured: Settings) -> None:
    urls = configured.feeders.stats_urls
    assert urls["flightaware"].get_secret_value() == FA_URL
    assert urls["fr24"].get_secret_value() == FR24_URL


def test_the_mapping_is_discovered_by_type() -> None:
    assert ("feeders", "stats_urls") in secret_field_paths(Settings)


def test_iter_secret_values_yields_each_mapping_value_by_key(configured: Settings) -> None:
    found = {path: secret.get_secret_value() for path, secret in iter_secret_values(configured)}
    assert found == {
        ("feeders", "stats_urls", "flightaware"): FA_URL,
        ("feeders", "stats_urls", "fr24"): FR24_URL,
    }


def test_repr_and_dumps_do_not_reveal_the_urls(configured: Settings) -> None:
    for text in (
        repr(configured),
        str(configured.model_dump()),
        configured.model_dump_json(),
    ):
        assert FA_URL not in text
        assert FR24_URL not in text


def test_dump_public_masks_each_value_and_keeps_the_keys(configured: Settings) -> None:
    public = configured.dump_public()

    assert public["feeders"]["stats_urls"] == {"flightaware": SECRET_MASK, "fr24": SECRET_MASK}
    rendered = json.dumps(public)
    assert FA_URL not in rendered
    assert FR24_URL not in rendered


def test_dump_for_file_omits_the_mapping(configured: Settings) -> None:
    for_file = configured.dump_for_file()

    assert "stats_urls" not in for_file["feeders"]
    assert SECRET_MASK not in json.dumps(for_file)


def test_secrets_state_reports_each_stored_key(configured: Settings) -> None:
    assert configured.secrets_state() == {
        "enrichment.aerodatabox_api_key": False,
        "feeders.stats_urls.flightaware": True,
        "feeders.stats_urls.fr24": True,
    }


def test_diagnostics_redaction_collects_every_url(configured: Settings) -> None:
    collected = secrets_from_settings(configured)
    assert FA_URL in collected
    assert FR24_URL in collected


def test_strip_masked_secrets_drops_masked_values_per_key() -> None:
    patch = {
        "feeders": {
            "stats_urls": {"flightaware": SECRET_MASK, "fr24": "https://new.example/"},
            "poll_interval_s": 30,
        }
    }
    stripped = strip_masked_secrets(patch)

    assert stripped["feeders"]["stats_urls"] == {"fr24": "https://new.example/"}
    assert stripped["feeders"]["poll_interval_s"] == 30
    # The caller's payload is never mutated.
    assert patch["feeders"]["stats_urls"]["flightaware"] == SECRET_MASK  # type: ignore[index]


def test_round_trip_keeps_masked_replaces_new_and_clears_null(
    store: ConfigStore, configured: Settings
) -> None:
    public = configured.dump_public()
    public["feeders"]["stats_urls"] = {
        "flightaware": SECRET_MASK,  # sent back as given: unchanged
        "fr24": None,  # cleared
        "opensky": "https://opensky-network.org/receiver-profile?s=sentinel-os",  # new
    }
    saved = store.apply_update({"feeders": public["feeders"]})

    assert saved.feeders.stats_urls["flightaware"].get_secret_value() == FA_URL
    assert "fr24" not in saved.feeders.stats_urls
    assert "opensky" in saved.feeders.stats_urls

    on_disk = yaml.safe_load(store.secrets_path.read_text(encoding="utf-8"))
    assert on_disk["feeders"]["stats_urls"] == {
        "flightaware": FA_URL,
        "opensky": "https://opensky-network.org/receiver-profile?s=sentinel-os",
    }
    config_text = store.config_path.read_text(encoding="utf-8")
    assert "stats_urls" not in config_text
    assert FA_URL not in config_text
    assert SECRET_MASK not in config_text

    # And a reload sees exactly what was written.
    reloaded = store.load()
    assert set(reloaded.feeders.stats_urls) == {"flightaware", "opensky"}


def test_the_config_api_masks_and_round_trips_stats_urls(
    isolated_data_dir: Path, store: ConfigStore
) -> None:
    store.secrets_path.write_text(SECRETS_YAML, encoding="utf-8")
    with TestClient(create_app(isolated_data_dir)) as client:
        got = client.get("/api/internal/config").json()
        assert got["config"]["feeders"]["stats_urls"] == {
            "flightaware": SECRET_MASK,
            "fr24": SECRET_MASK,
        }
        assert got["secrets_set"]["feeders.stats_urls.fr24"] is True

        put = client.put("/api/internal/config", json={"feeders": got["config"]["feeders"]})
        assert put.status_code == 200
        assert FA_URL not in put.text
        assert FR24_URL not in put.text

    reloaded = store.load()
    assert reloaded.feeders.stats_urls["fr24"].get_secret_value() == FR24_URL


def test_a_rejected_stats_url_is_not_echoed_by_the_api(isolated_data_dir: Path) -> None:
    bad = "javascript:alert('sentinel-bad-url-3f9a')"
    with TestClient(create_app(isolated_data_dir)) as client:
        response = client.put(
            "/api/internal/config", json={"feeders": {"stats_urls": {"fr24": bad}}}
        )
    assert response.status_code == 422
    assert "sentinel-bad-url-3f9a" not in response.text
