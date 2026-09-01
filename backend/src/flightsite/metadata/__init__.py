"""Aircraft metadata: normalized schema, providers, import, precedence, cache.

The framework SPEC §25-§27 and ADR-0006 describe, with no concrete source of
its own — slices 022 (Mictronics) and 023 (FAA) register those against the
registry here.

Reading order:

* :mod:`~flightsite.metadata.records` — the normalized records that cross the
  provider boundary, and the normalization every one of them is held to.
* :mod:`~flightsite.metadata.provider` — the three-method ``MetadataProvider``
  seam.
* :mod:`~flightsite.metadata.precedence` — which source wins which field, and
  the provenance that falls out of deciding.
* :mod:`~flightsite.metadata.registry` — the sources this process knows, their
  declared precedence, and their in-flight run state.
* :mod:`~flightsite.metadata.repository` — every SQL statement, and the
  transaction boundaries that make a failed import harmless.
* :mod:`~flightsite.metadata.importer` — download → validate → stage → promote.
* :mod:`~flightsite.metadata.cache` — the in-memory lookup that keeps SQLite
  off the live path.
* :mod:`~flightsite.metadata.service` — the two of those the application wires.
"""

from __future__ import annotations

from flightsite.metadata.cache import AircraftMetadataView, MetadataCache
from flightsite.metadata.importer import (
    ImportFailure,
    ImportRun,
    MetadataImporter,
    SourceImportResult,
)
from flightsite.metadata.precedence import (
    DEFAULT_FIELD_PRIORITIES,
    RESOLVED_FIELDS,
    FieldPriority,
    PrecedenceModel,
    ResolvedMetadata,
    SourceClaim,
)
from flightsite.metadata.provider import MetadataProvider
from flightsite.metadata.records import (
    MetadataError,
    NormalizedAircraftRecord,
    RecordError,
    SourceArtifact,
    ValidationReport,
    normalize_record,
)
from flightsite.metadata.registry import (
    ImportPhase,
    RegisteredSource,
    RegistrationError,
    SourceRegistry,
    SourceRunState,
    SourceStatus,
    SourceStatusRecord,
)
from flightsite.metadata.repository import MetadataClearCounts, MetadataRepository
from flightsite.metadata.service import ImportListener, MetadataService

__all__ = [
    "DEFAULT_FIELD_PRIORITIES",
    "RESOLVED_FIELDS",
    "AircraftMetadataView",
    "FieldPriority",
    "ImportFailure",
    "ImportListener",
    "ImportPhase",
    "ImportRun",
    "MetadataCache",
    "MetadataClearCounts",
    "MetadataError",
    "MetadataImporter",
    "MetadataProvider",
    "MetadataRepository",
    "MetadataService",
    "NormalizedAircraftRecord",
    "PrecedenceModel",
    "RecordError",
    "RegisteredSource",
    "RegistrationError",
    "ResolvedMetadata",
    "SourceArtifact",
    "SourceClaim",
    "SourceImportResult",
    "SourceRegistry",
    "SourceRunState",
    "SourceStatus",
    "SourceStatusRecord",
    "ValidationReport",
    "normalize_record",
]
