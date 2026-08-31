"""Decoder ingestion: the boundary between ADS-B decoders and FlightSite.

Module map:

============================ ==============================================
Module                       Responsibility
============================ ==============================================
:mod:`~flightsite.ingest.types`            decoder-agnostic domain types
:mod:`~flightsite.ingest.protocol`         the ``DecoderAdapter`` seam
:mod:`~flightsite.ingest.health`           connected/degraded/down + backoff
:mod:`~flightsite.ingest.bounds`           plausibility bounds and coercion
:mod:`~flightsite.ingest.readsb`           readsb / dump1090-fa adapter
:mod:`~flightsite.ingest.connection_test`  one-shot endpoint probe
:mod:`~flightsite.ingest.service`          the ingestion loop and its sinks
============================ ==============================================

Only :mod:`~flightsite.ingest.readsb` knows a decoder's field names
(SPEC §11, ADR-0003).
"""

from __future__ import annotations

from flightsite.ingest.connection_test import (
    ConnectionTestError,
    ConnectionTestResult,
    check_connection,
)
from flightsite.ingest.health import AdapterHealth, HealthState, HealthTracker
from flightsite.ingest.protocol import (
    DecoderAdapter,
    DecoderError,
    DecoderParseError,
    DecoderUnavailableError,
)
from flightsite.ingest.readsb import ReadsbJsonAdapter
from flightsite.ingest.service import (
    BatchConsumer,
    IngestionService,
    build_ingestion_service,
    null_sink,
)
from flightsite.ingest.types import (
    AircraftStateBatch,
    AircraftStateUpdate,
    DecoderEndpoint,
    DecoderFlavor,
    DecoderProbe,
    Position,
    PositionSource,
)

__all__ = [
    "AdapterHealth",
    "AircraftStateBatch",
    "AircraftStateUpdate",
    "BatchConsumer",
    "ConnectionTestError",
    "ConnectionTestResult",
    "DecoderAdapter",
    "DecoderEndpoint",
    "DecoderError",
    "DecoderFlavor",
    "DecoderParseError",
    "DecoderProbe",
    "DecoderUnavailableError",
    "HealthState",
    "HealthTracker",
    "IngestionService",
    "Position",
    "PositionSource",
    "ReadsbJsonAdapter",
    "build_ingestion_service",
    "check_connection",
    "null_sink",
]
