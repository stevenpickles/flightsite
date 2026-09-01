"""FlightSite persistence: engine, session discipline, migrations, ``meta``/T0.

The single-writer rule and the connection pragmas are documented in
:mod:`flightsite.db.engine`; T0's write-once semantics in
:mod:`flightsite.db.meta`; the startup migrate/integrity/readiness sequence in
:mod:`flightsite.db.startup`.
"""

from __future__ import annotations

from flightsite.db.clock import from_epoch_ms, to_epoch_ms, utc_now_ms
from flightsite.db.engine import (
    BUSY_TIMEOUT_MS,
    DB_FILENAME,
    QUICK_CHECK_OK,
    Database,
    create_sqlite_engine,
    database_path,
    sqlite_url,
)
from flightsite.db.meta import MetaError, MetaRepository
from flightsite.db.models import (
    META_KEY_T0,
    Aircraft,
    Base,
    Meta,
    Sighting,
    SightingEvent,
    SightingTrack,
    SightingTrackCheckpoint,
)
from flightsite.db.startup import DATABASE_SUBSYSTEM, initialize_database

__all__ = [
    "BUSY_TIMEOUT_MS",
    "DATABASE_SUBSYSTEM",
    "DB_FILENAME",
    "META_KEY_T0",
    "QUICK_CHECK_OK",
    "Aircraft",
    "Base",
    "Database",
    "Meta",
    "MetaError",
    "MetaRepository",
    "Sighting",
    "SightingEvent",
    "SightingTrack",
    "SightingTrackCheckpoint",
    "create_sqlite_engine",
    "database_path",
    "from_epoch_ms",
    "initialize_database",
    "sqlite_url",
    "to_epoch_ms",
    "utc_now_ms",
]
