"""Database startup: migrate, verify integrity, report readiness.

Startup sequence (roadmap slice 005, ADR-0001):

1. Apply Alembic migrations up to head on the writer connection.
2. Run ``PRAGMA quick_check``.
3. Mark the ``database`` readiness subsystem ready — only if both succeeded.

Failure policy: a database that cannot be migrated or that fails its integrity
check is **loud and visible, never fatal and never silent**. The process stays
up so an operator can reach ``/api/v1/health``, the logs, and (from slice 042)
the diagnostics surface; the ``db_errors`` counter increments; and the
``database`` subsystem stays not-ready, so ``/api/v1/ready`` answers 503 and a
container orchestrator or reverse proxy sees the instance as unhealthy.
Crashing the process instead would hide the diagnosis behind a restart loop.
"""

from __future__ import annotations

import structlog

from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.engine import QUICK_CHECK_OK, Database
from flightsite.readiness import ReadinessRegistry

logger = structlog.get_logger(__name__)

#: Readiness-registry name for the database subsystem.
DATABASE_SUBSYSTEM = "database"

DB_ERRORS_COUNTER = "db_errors"


async def initialize_database(
    database: Database,
    readiness: ReadinessRegistry,
    *,
    counters: CounterRegistry = default_counters,
) -> bool:
    """Migrate and integrity-check the database, then set its readiness.

    Args:
        database: the application database.
        readiness: registry holding the ``database`` subsystem, which must
            already be registered (the app factory registers it, so the
            subsystem shows as not-ready from the first request onward).
        counters: counter registry receiving ``db_errors`` on failure.

    Returns:
        True if the database migrated and passed ``quick_check``.
    """
    db_path = str(database.path)

    try:
        await database.upgrade_to("head")
    except Exception as exc:
        logger.error(
            "database_migration_failed",
            db_path=db_path,
            error=str(exc),
            error_type=type(exc).__name__,
            remediation=(
                "database left not-ready; /api/v1/ready reports 503. "
                "Inspect the database file and the migration history."
            ),
            exc_info=True,
        )
        counters.increment(DB_ERRORS_COUNTER)
        readiness.mark_not_ready(DATABASE_SUBSYSTEM)
        return False

    try:
        results = await database.quick_check()
    except Exception as exc:
        logger.error(
            "database_integrity_check_errored",
            db_path=db_path,
            error=str(exc),
            error_type=type(exc).__name__,
            remediation=(
                "database left not-ready; /api/v1/ready reports 503. "
                "Restore from a backup or move the file aside to start fresh."
            ),
            exc_info=True,
        )
        counters.increment(DB_ERRORS_COUNTER)
        readiness.mark_not_ready(DATABASE_SUBSYSTEM)
        return False

    if list(results) != [QUICK_CHECK_OK]:
        logger.error(
            "database_integrity_check_failed",
            db_path=db_path,
            quick_check=list(results),
            remediation=(
                "database left not-ready; /api/v1/ready reports 503. "
                "Restore from a backup or move the file aside to start fresh."
            ),
        )
        counters.increment(DB_ERRORS_COUNTER)
        readiness.mark_not_ready(DATABASE_SUBSYSTEM)
        return False

    revision = await database.current_revision()
    readiness.mark_ready(DATABASE_SUBSYSTEM)
    logger.info("database_ready", db_path=db_path, schema_revision=revision)
    return True
