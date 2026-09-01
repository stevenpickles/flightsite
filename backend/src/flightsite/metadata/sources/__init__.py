"""Concrete :class:`~flightsite.metadata.provider.MetadataProvider` implementations.

Slices 022 (Mictronics) and 023 (FAA) each contribute one module here. This
package is deliberately just an export point: *which* provider gets
registered under which name, and with what per-field priority, is decided at
application wiring time (``flightsite.app.create_app``,
:mod:`flightsite.metadata.registry`) — not here, so importing this package
alone has zero side effects (no network, no filesystem, no registration).
"""

from __future__ import annotations

from flightsite.metadata.sources.faa import FaaRegistryProvider

__all__ = ["FaaRegistryProvider"]
