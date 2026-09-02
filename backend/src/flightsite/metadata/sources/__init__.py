"""Concrete :class:`~flightsite.metadata.provider.MetadataProvider` sources.

One module per upstream source (ADR-0006): each source's field names, quirks
and download mechanics are isolated to its own module here, and the rest of
the application only ever sees what it yields through the
:mod:`flightsite.metadata.provider` seam.

* :mod:`~flightsite.metadata.sources.mictronics` — the Mictronics/tar1090
  aircraft database (slice 022).
* :mod:`~flightsite.metadata.sources.faa` — the FAA releasable registry
  (slice 023).
* :mod:`~flightsite.metadata.sources.opensky` — the OpenSky aircraft database
  (slice 059). Opt-in and off by default; unlike the two above it is registered
  only when ``metadata.opensky_enabled`` is set (ADR-0013).

This package is deliberately just an export point: *which* provider gets
registered under which name, and with what per-field priority, is decided at
application wiring time (``flightsite.app.create_app``,
:mod:`flightsite.metadata.registry`) — not here, so importing this package
alone has zero side effects (no network, no filesystem, no registration).
"""

from __future__ import annotations

from flightsite.metadata.sources.faa import FaaRegistryProvider
from flightsite.metadata.sources.mictronics import MictronicsProvider
from flightsite.metadata.sources.opensky import OpenSkyProvider

__all__ = ["FaaRegistryProvider", "MictronicsProvider", "OpenSkyProvider"]
