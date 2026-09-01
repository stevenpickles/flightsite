"""FlightSite backend package.

The application version is defined once in ``pyproject.toml`` and exposed at
runtime via package metadata so no other module needs to hardcode it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("flightsite")
except PackageNotFoundError:  # pragma: no cover - package is always installed in dev/test
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
