"""Health and diagnostics aggregation (SPEC §67, roadmap slice 042).

Two pieces: :mod:`flightsite.diagnostics.errors` captures recent errors into a
bounded, secret-redacted ring buffer fed passively by the logging system, and
:mod:`flightsite.diagnostics.service` aggregates every SPEC §67 item into the
payload ``GET /api/v1/diagnostics`` serves.
"""

from __future__ import annotations

from flightsite.diagnostics.errors import (
    CATEGORIES,
    DATABASE,
    DEFAULT_CAPACITY,
    ENRICHMENT,
    INGESTION,
    OTHER,
    REDACTED,
    WEBSOCKET,
    ErrorRing,
    ErrorRingHandler,
    RecentError,
    category_for_logger,
    error_ring,
    redact,
    redact_value,
    secrets_from_settings,
)
from flightsite.diagnostics.service import (
    RECENT_ERROR_LIMIT,
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_OK,
    collect_diagnostics,
)

__all__ = [
    "CATEGORIES",
    "DATABASE",
    "DEFAULT_CAPACITY",
    "ENRICHMENT",
    "INGESTION",
    "OTHER",
    "RECENT_ERROR_LIMIT",
    "REDACTED",
    "STATUS_DEGRADED",
    "STATUS_DOWN",
    "STATUS_OK",
    "WEBSOCKET",
    "ErrorRing",
    "ErrorRingHandler",
    "RecentError",
    "category_for_logger",
    "collect_diagnostics",
    "error_ring",
    "redact",
    "redact_value",
    "secrets_from_settings",
]
