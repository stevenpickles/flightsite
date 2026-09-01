"""Loading and validating the user-supplied airspace overlay (roadmap slice 028).

FlightSite ships no default airspace data — see ``docs/adr/0012-airspace-data-
source.md`` for why openAIP (CC BY-NC) is rejected as a shipped default and FAA
NASR parsing is a documented follow-up rather than this slice's work. A user who
wants airspace boundaries drops their own GeoJSON ``FeatureCollection`` at
``<data_dir>/airspace.geojson``; this module is the only place that reads it, and
the only two shapes any caller can observe are "empty" and "a validated
``FeatureCollection``" — never a half-parsed file, never an exception reaching a
request handler.

Validated on every read rather than trusted blindly, because the file is
arbitrary user input: it must parse as JSON, be a top-level ``FeatureCollection``,
stay under :data:`MAX_AIRSPACE_BYTES`, and every feature's geometry must carry
plausible WGS-84 coordinates. Anything that fails any check — missing file,
oversized file, invalid JSON, wrong shape, an unusable coordinate on one feature
— is logged once and answered with the same empty collection an install that
never supplied the file gets, per this slice's "degraded gracefully with no UI
noise" acceptance criterion: a client can never tell "no file" apart from "a file
that failed validation" from the response alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)

#: Filename the loader reads, relative to the configured data directory
#: (``flightsite.config.Settings.data_dir``).
AIRSPACE_FILENAME: Final = "airspace.geojson"

#: Above this many bytes the file is refused without being parsed at all.
#: Large enough for a serious personal or regional airspace extract; small
#: enough that a mistakenly-pointed-at planet-scale export cannot make one
#: request hold multiple megabytes of JSON parsing and coordinate-walking.
MAX_AIRSPACE_BYTES: Final = 10 * 1024 * 1024

#: Geometry types a feature's ``geometry.type`` may carry. Airspace is
#: normally polygons, but a boundary or centerline supplied as a line (or a
#: single reporting point) is still a usable overlay feature, so all of
#: GeoJSON's non-collection geometry types are accepted rather than only
#: (Multi)Polygon.
_ACCEPTED_GEOMETRY_TYPES: Final = frozenset(
    {"Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"}
)

#: The *shape* every "no file" and "a file that failed validation" answer
#: shares — see the module docstring on why those two must be
#: indistinguishable. Read-only: compare against this, never return it or a
#: shallow copy of it. ``dict(EMPTY_FEATURE_COLLECTION)`` would still share
#: *this* list as its ``"features"`` value, so a caller that mutated its
#: result in place (a real bug this module's own test suite caught) would
#: corrupt every future "empty" answer for the life of the process.
#: :func:`_empty_feature_collection` is what callers actually return.
EMPTY_FEATURE_COLLECTION: Final[dict[str, Any]] = {"type": "FeatureCollection", "features": []}


def _empty_feature_collection() -> dict[str, Any]:
    """A fresh, independently-mutable empty ``FeatureCollection``."""
    return {"type": "FeatureCollection", "features": []}


def airspace_path(data_dir: Path) -> Path:
    """Where the user-supplied airspace file lives for this install."""
    return data_dir / AIRSPACE_FILENAME


def load_airspace(data_dir: Path) -> dict[str, Any]:
    """The validated airspace ``FeatureCollection``, or an empty one.

    Never raises — every rejection path returns a fresh empty collection
    (:func:`_empty_feature_collection`), equal to but never sharing state
    with :data:`EMPTY_FEATURE_COLLECTION` or any previous call's result.
    """
    path = airspace_path(data_dir)
    try:
        size = path.stat().st_size
    except OSError:
        # The overwhelmingly common case on a stock install: no file has ever
        # been placed. Not logged — that would be a warning on every request
        # to `/api/v1/airspace` for the entire life of an install that never
        # opts into this feature.
        return _empty_feature_collection()

    if size > MAX_AIRSPACE_BYTES:
        logger.warning(
            "airspace_file_too_large",
            path=str(path),
            size_bytes=size,
            limit_bytes=MAX_AIRSPACE_BYTES,
        )
        return _empty_feature_collection()

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("airspace_file_unreadable", path=str(path), error=str(exc))
        return _empty_feature_collection()

    try:
        document = json.loads(raw)
    except ValueError as exc:
        logger.warning("airspace_file_invalid_json", path=str(path), error=str(exc))
        return _empty_feature_collection()

    features = _validate_feature_collection(document)
    if features is None:
        logger.warning("airspace_file_invalid_shape", path=str(path))
        return _empty_feature_collection()

    return {"type": "FeatureCollection", "features": features}


def _validate_feature_collection(document: Any) -> list[dict[str, Any]] | None:
    """The document's ``features`` list with every unusable entry dropped, or
    ``None`` if the document itself is not a ``FeatureCollection`` at all.

    A single bad feature does not fail the whole file — the same
    reject-and-carry-on posture :mod:`flightsite.airports.records` takes for
    one bad row in an import — since a user's hand-edited or hand-assembled
    file is exactly the case one malformed geometry should not sink entirely.
    """
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        return None
    raw_features = document.get("features")
    if not isinstance(raw_features, list):
        return None
    features: list[dict[str, Any]] = []
    for raw_feature in raw_features:
        feature = _validate_feature(raw_feature)
        if feature is not None:
            features.append(feature)
    return features


def _validate_feature(raw: Any) -> dict[str, Any] | None:
    """One feature, normalized to exactly ``type``/``geometry``/``properties``,
    or ``None`` if its geometry is missing or its coordinates are not sane."""
    if not isinstance(raw, dict) or raw.get("type") != "Feature":
        return None
    geometry = raw.get("geometry")
    if not isinstance(geometry, dict) or not _sane_geometry(geometry):
        return None
    properties = raw.get("properties")
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties if isinstance(properties, dict) else {},
    }


def _sane_geometry(geometry: dict[str, Any]) -> bool:
    if geometry.get("type") not in _ACCEPTED_GEOMETRY_TYPES:
        return False
    coordinates = geometry.get("coordinates")
    return coordinates is not None and _sane_coordinates(coordinates)


#: Coordinates nest one level per GeoJSON geometry type (0 for a bare pair —
#: never valid on its own — up to 3 for a MultiPolygon); anything past that
#: cannot be a real geometry and stops the recursion rather than walking a
#: pathologically deep structure a malformed file might contain.
_MAX_COORDINATE_DEPTH: Final = 4


def _sane_coordinates(node: Any, depth: int = 0) -> bool:
    """Recursively checks that every coordinate pair is a plausible lon/lat.

    Depth-agnostic by design: a Polygon's coordinates nest three deep, a
    LineString's two, a Point's one. Rather than assume a fixed nesting per
    geometry type, this walks down until it finds a ``[lon, lat, ...]`` leaf
    and validates that, so one function serves every accepted geometry type.
    """
    if depth > _MAX_COORDINATE_DEPTH or not isinstance(node, list) or not node:
        return False
    first = node[0]
    if isinstance(first, int | float):
        if len(node) < 2:
            return False
        lon, lat = node[0], node[1]
        return (
            isinstance(lon, int | float)
            and isinstance(lat, int | float)
            and -180.0 <= lon <= 180.0
            and -90.0 <= lat <= 90.0
        )
    return all(_sane_coordinates(child, depth + 1) for child in node)


__all__ = [
    "AIRSPACE_FILENAME",
    "EMPTY_FEATURE_COLLECTION",
    "MAX_AIRSPACE_BYTES",
    "airspace_path",
    "load_airspace",
]
