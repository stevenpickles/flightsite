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
    METADATA_SOURCE_STATUS_CHECK,
    ROUTE_CACHE_STATUS_CHECK,
    WATCHLIST_ENTRY_KIND_CHECK,
    Aircraft,
    AircraftClassification,
    AircraftMetadata,
    AircraftMetadataResolved,
    AircraftMetadataStaging,
    Airport,
    Base,
    DailyOperatorStats,
    DailyStats,
    DailyTypeStats,
    LifetimeStat,
    Meta,
    MetadataSource,
    Operator,
    OperatorGroup,
    RangeByBearingDaily,
    ReceiverMetricDaily,
    ReceiverMetricHourly,
    ReceiverMetricRaw,
    RouteCache,
    Sighting,
    SightingEvent,
    SightingTrack,
    SightingTrackCheckpoint,
    TypeStats,
    Watchlist,
    WatchlistEntry,
)
from flightsite.db.startup import DATABASE_SUBSYSTEM, initialize_database

__all__ = [
    "BUSY_TIMEOUT_MS",
    "DATABASE_SUBSYSTEM",
    "DB_FILENAME",
    "METADATA_SOURCE_STATUS_CHECK",
    "META_KEY_T0",
    "QUICK_CHECK_OK",
    "ROUTE_CACHE_STATUS_CHECK",
    "WATCHLIST_ENTRY_KIND_CHECK",
    "Aircraft",
    "AircraftClassification",
    "AircraftMetadata",
    "AircraftMetadataResolved",
    "AircraftMetadataStaging",
    "Airport",
    "Base",
    "DailyOperatorStats",
    "DailyStats",
    "DailyTypeStats",
    "Database",
    "LifetimeStat",
    "Meta",
    "MetaError",
    "MetaRepository",
    "MetadataSource",
    "Operator",
    "OperatorGroup",
    "RangeByBearingDaily",
    "ReceiverMetricDaily",
    "ReceiverMetricHourly",
    "ReceiverMetricRaw",
    "RouteCache",
    "Sighting",
    "SightingEvent",
    "SightingTrack",
    "SightingTrackCheckpoint",
    "TypeStats",
    "Watchlist",
    "WatchlistEntry",
    "create_sqlite_engine",
    "database_path",
    "from_epoch_ms",
    "initialize_database",
    "sqlite_url",
    "to_epoch_ms",
    "utc_now_ms",
]
