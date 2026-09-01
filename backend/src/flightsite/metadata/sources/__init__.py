"""Concrete :class:`~flightsite.metadata.provider.MetadataProvider` sources.

One module per upstream source (ADR-0006): each source's field names, quirks
and download mechanics are isolated to its own module here, and the rest of
the application only ever sees what it yields through the
:mod:`flightsite.metadata.provider` seam.

* :mod:`~flightsite.metadata.sources.mictronics` — the Mictronics/tar1090
  aircraft database (slice 022).
"""

from __future__ import annotations

from flightsite.metadata.sources.mictronics import MictronicsProvider

__all__ = ["MictronicsProvider"]
