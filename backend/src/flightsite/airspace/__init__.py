"""The user-supplied airspace overlay (SPEC-adjacent, roadmap slice 028).

One module, one job: :mod:`flightsite.airspace.loader` reads and validates
``<data_dir>/airspace.geojson`` for ``GET /api/v1/airspace``. See
``docs/adr/0012-airspace-data-source.md`` for why FlightSite ships no default
airspace dataset at all.
"""

from __future__ import annotations

from flightsite.airspace.loader import (
    AIRSPACE_FILENAME,
    EMPTY_FEATURE_COLLECTION,
    MAX_AIRSPACE_BYTES,
    airspace_path,
    load_airspace,
)

__all__ = [
    "AIRSPACE_FILENAME",
    "EMPTY_FEATURE_COLLECTION",
    "MAX_AIRSPACE_BYTES",
    "airspace_path",
    "load_airspace",
]
