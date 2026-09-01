"""Manifest parsing: it must reject a wrong shape with a readable complaint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from flightsite.backup import FORMAT_VERSION, ManifestError, parse_manifest
from flightsite.backup.manifest import (
    FileEntry,
    Manifest,
    MetadataSourceEntry,
    utc_iso,
    utc_iso_from_ms,
)


def valid_manifest_dict(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "flightsite_version": "0.0.1",
        "schema_revision": "0009",
        "created_utc": "2026-09-01T12:00:00Z",
        "includes_secrets": False,
        "files": {"flightsite.sqlite3": {"sha256": "a" * 64, "size_bytes": 4096}},
        "metadata_sources": [],
    }
    document.update(overrides)
    return document


def test_round_trip_preserves_every_field() -> None:
    manifest = Manifest(
        format_version=FORMAT_VERSION,
        flightsite_version="1.2.3",
        schema_revision="0007",
        created_utc="2026-09-01T12:00:00Z",
        includes_secrets=True,
        files=(FileEntry("config.yaml", "b" * 64, 12),),
        metadata_sources=(MetadataSourceEntry("opensky", "2026-08-01", "2026-08-01T00:00:00Z"),),
    )

    assert parse_manifest(manifest.to_json()) == manifest


def test_manifest_json_is_newline_terminated() -> None:
    manifest = parse_manifest(json.dumps(valid_manifest_dict()))

    assert manifest.to_json().endswith("}\n")


def test_file_lookup_and_names() -> None:
    manifest = parse_manifest(json.dumps(valid_manifest_dict()))

    assert manifest.file("flightsite.sqlite3") is not None
    assert manifest.file("secrets.yaml") is None
    assert manifest.file_names == frozenset({"flightsite.sqlite3"})


def test_unparseable_json_is_rejected() -> None:
    with pytest.raises(ManifestError, match="not valid JSON"):
        parse_manifest(b"{not json")


def test_a_non_object_manifest_is_rejected() -> None:
    with pytest.raises(ManifestError, match="must be a JSON object"):
        parse_manifest(b"[1, 2, 3]")


def test_an_unsupported_format_version_is_refused_with_advice() -> None:
    payload = json.dumps(valid_manifest_dict(format_version=FORMAT_VERSION + 1))

    with pytest.raises(ManifestError, match="is not supported by this FlightSite build"):
        parse_manifest(payload)


@pytest.mark.parametrize(
    "key",
    ["format_version", "flightsite_version", "created_utc", "includes_secrets", "files"],
)
def test_a_missing_required_key_is_named(key: str) -> None:
    document = valid_manifest_dict()
    del document[key]

    with pytest.raises(ManifestError, match=f"missing required key '{key}'"):
        parse_manifest(json.dumps(document))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"format_version": "1"}, "'format_version' must be an integer"),
        ({"flightsite_version": 1}, "'flightsite_version' must be a string"),
        ({"schema_revision": 9}, "'schema_revision' must be a string or null"),
        ({"includes_secrets": "yes"}, "'includes_secrets' must be a boolean"),
        ({"files": []}, "'files' must be an object"),
        ({"metadata_sources": {}}, "'metadata_sources' must be a list"),
    ],
)
def test_mistyped_keys_are_reported(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        parse_manifest(json.dumps(valid_manifest_dict(**overrides)))


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("not-an-object", "must be an object"),
        ({"sha256": "short", "size_bytes": 1}, "no valid 'sha256'"),
        ({"size_bytes": 1}, "no valid 'sha256'"),
        ({"sha256": "a" * 64}, "no valid 'size_bytes'"),
        ({"sha256": "a" * 64, "size_bytes": -1}, "no valid 'size_bytes'"),
        ({"sha256": "a" * 64, "size_bytes": True}, "no valid 'size_bytes'"),
    ],
)
def test_bad_file_entries_are_reported(entry: Any, message: str) -> None:
    document = valid_manifest_dict(files={"flightsite.sqlite3": entry})

    with pytest.raises(ManifestError, match=message):
        parse_manifest(json.dumps(document))


def test_metadata_source_items_must_be_objects() -> None:
    document = valid_manifest_dict(metadata_sources=["opensky"])

    with pytest.raises(ManifestError, match="must be an object"):
        parse_manifest(json.dumps(document))


def test_metadata_source_entries_allow_nulls() -> None:
    document = valid_manifest_dict(
        metadata_sources=[{"source": "opensky", "dataset_version": None, "last_success": None}]
    )

    manifest = parse_manifest(json.dumps(document))

    assert manifest.metadata_sources[0].dataset_version is None
    assert manifest.metadata_sources[0].last_success is None


def test_undecodable_bytes_are_reported_as_bad_json() -> None:
    with pytest.raises(ManifestError, match="not valid JSON"):
        parse_manifest(b"\xff\xfe\x00\x01")


def test_timestamps_are_rendered_as_utc_with_a_z_suffix() -> None:
    tokyo = datetime(2026, 9, 1, 21, 0, 0, tzinfo=timezone(timedelta(hours=9)))

    assert utc_iso(tokyo) == "2026-09-01T12:00:00Z"
    assert utc_iso(datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)) == "2026-09-01T12:00:00Z"


def test_epoch_millisecond_columns_render_or_stay_none() -> None:
    assert utc_iso_from_ms(None) is None
    assert utc_iso_from_ms(0) == "1970-01-01T00:00:00Z"
