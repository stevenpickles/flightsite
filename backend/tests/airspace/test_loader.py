"""``flightsite.airspace.loader`` — validating the user-supplied airspace file
(roadmap slice 028, ``docs/adr/0012-airspace-data-source.md``).

Every rejection path must land on the *same* empty collection an absent file
gets — that indistinguishability is the "degraded gracefully with no UI noise"
acceptance criterion, and it is asserted here directly rather than only through
the API layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flightsite.airspace.loader import (
    AIRSPACE_FILENAME,
    EMPTY_FEATURE_COLLECTION,
    MAX_AIRSPACE_BYTES,
    airspace_path,
    load_airspace,
)


def write(data_dir: Path, document: object) -> None:
    (data_dir / AIRSPACE_FILENAME).write_text(json.dumps(document), encoding="utf-8")


def test_airspace_path_is_the_data_dir_joined_with_the_filename(tmp_path: Path) -> None:
    assert airspace_path(tmp_path) == tmp_path / "airspace.geojson"


# ------------------------------------------------------------------------ absence


def test_no_file_is_an_empty_collection(tmp_path: Path) -> None:
    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


def test_the_empty_result_is_a_fresh_object_each_call(tmp_path: Path) -> None:
    """A caller mutating one result must never poison the next call's answer."""
    first = load_airspace(tmp_path)
    first["features"].append({"type": "Feature"})

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


# --------------------------------------------------------------------- validity


def test_a_valid_polygon_feature_collection_round_trips(tmp_path: Path) -> None:
    document: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"class": "D", "name": "Test Class D"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-1.0, 50.0], [-1.0, 51.0], [1.0, 51.0], [1.0, 50.0], [-1.0, 50.0]]
                    ],
                },
            }
        ],
    }
    write(tmp_path, document)

    assert load_airspace(tmp_path) == document


def test_a_multipolygon_with_sane_coordinates_is_kept(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[-1.0, 50.0], [-1.0, 51.0], [1.0, 51.0], [-1.0, 50.0]]]],
                },
            }
        ],
    }
    write(tmp_path, document)

    result = load_airspace(tmp_path)

    assert len(result["features"]) == 1


def test_a_feature_missing_properties_gets_an_empty_object(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}}],
    }
    write(tmp_path, document)

    result = load_airspace(tmp_path)

    assert result["features"][0]["properties"] == {}


# ---------------------------------------------------------------- invalid shape


def test_invalid_json_is_empty(tmp_path: Path) -> None:
    (tmp_path / AIRSPACE_FILENAME).write_text("{not valid json", encoding="utf-8")

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


def test_a_json_array_at_the_top_level_is_not_a_feature_collection(tmp_path: Path) -> None:
    write(tmp_path, [1, 2, 3])

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


def test_wrong_top_level_type_is_empty(tmp_path: Path) -> None:
    write(tmp_path, {"type": "Feature", "features": []})

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


def test_features_not_a_list_is_empty(tmp_path: Path) -> None:
    write(tmp_path, {"type": "FeatureCollection", "features": "nope"})

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


def test_an_unrecognized_geometry_type_is_dropped(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "GeometryCollection", "coordinates": []},
            }
        ],
    }
    write(tmp_path, document)

    assert load_airspace(tmp_path) == {"type": "FeatureCollection", "features": []}


def test_a_feature_with_no_geometry_is_dropped(tmp_path: Path) -> None:
    document = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}}]}
    write(tmp_path, document)

    assert load_airspace(tmp_path) == {"type": "FeatureCollection", "features": []}


def test_a_list_entry_that_is_not_a_feature_object_is_dropped(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            "not a feature",
            {"type": "NotAFeature", "properties": {}},
            {
                "type": "Feature",
                "properties": {"name": "good"},
                "geometry": {"type": "Point", "coordinates": [-122.3, 47.5]},
            },
        ],
    }
    write(tmp_path, document)

    result = load_airspace(tmp_path)

    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["name"] == "good"


def test_coordinates_that_are_not_a_list_are_dropped(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": "not-a-list"},
            }
        ],
    }
    write(tmp_path, document)

    assert load_airspace(tmp_path) == {"type": "FeatureCollection", "features": []}


def test_a_lone_number_with_no_second_coordinate_is_dropped(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [1.0]},
            }
        ],
    }
    write(tmp_path, document)

    assert load_airspace(tmp_path) == {"type": "FeatureCollection", "features": []}


def test_an_unreadable_file_degrades_to_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that exists at ``stat()`` time but fails to read (permissions,
    a race with deletion) degrades exactly like every other rejection path."""
    write(tmp_path, {"type": "FeatureCollection", "features": []})

    def _raise(self: Path, encoding: str | None = None) -> str:
        raise OSError("simulated read failure")

    monkeypatch.setattr(Path, "read_text", _raise)

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION


def test_a_feature_with_out_of_range_coordinates_is_dropped(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [200.0, 0.0]},
            }
        ],
    }
    write(tmp_path, document)

    assert load_airspace(tmp_path) == {"type": "FeatureCollection", "features": []}


def test_one_bad_feature_does_not_sink_the_whole_file(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "bad"},
                "geometry": {"type": "Point", "coordinates": [999.0, 999.0]},
            },
            {
                "type": "Feature",
                "properties": {"name": "good"},
                "geometry": {"type": "Point", "coordinates": [-122.3, 47.5]},
            },
        ],
    }
    write(tmp_path, document)

    result = load_airspace(tmp_path)

    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["name"] == "good"


# ------------------------------------------------------------------------- size


def test_oversized_file_is_refused_without_being_parsed(tmp_path: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"padding": "x" * (MAX_AIRSPACE_BYTES + 1)},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            }
        ],
    }
    write(tmp_path, document)

    assert load_airspace(tmp_path) == EMPTY_FEATURE_COLLECTION
