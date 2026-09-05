"""Read-only aggregation behind ``GET /api/v1/diagnostics`` (SPEC §67).

The point of this module is that a user can answer "is FlightSite healthy?"
from a browser instead of an SSH session. It therefore *reads* from every
subsystem and *writes* to none: no lock is taken that ingestion needs, no
writer session is opened, and every database question goes through
:meth:`Database.read_session`, which sets ``query_only``. A diagnostics request
that arrives during a decoder burst must cost the burst nothing.

Every section degrades rather than fails. A first-run install has no decoder,
an install that has never imported metadata has no dataset age, and a database
that has not been written to has no rows — each of those is a legitimate state
the health area has to render, so the collector reports ``None`` and a reason
instead of raising. One subsystem being absent never blanks the rest of the
page: section builders are individually guarded, so a failure to read the
database still leaves the decoder, version and error sections intact.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import func, select

from flightsite import __version__
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db import (
    ActivityEvent,
    Aircraft,
    AircraftMetadata,
    Airport,
    AlertMatch,
    Database,
    ReceiverMetricRaw,
    Sighting,
    SightingTrack,
)
from flightsite.diagnostics.errors import (
    CATEGORIES,
    ErrorRing,
    RecentError,
    redact_value,
    secrets_from_settings,
)
from flightsite.diagnostics.errors import (
    error_ring as default_error_ring,
)
from flightsite.maintenance.stats import gather_stats

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

    from flightsite.config.models import Settings

#: Overall roll-up states, worst last. The UI renders a single banner from this
#: so a user does not have to read every card to learn something is wrong.
STATUS_OK: Final = "ok"
STATUS_DEGRADED: Final = "degraded"
STATUS_DOWN: Final = "down"

_STATUS_SEVERITY: Final[dict[str, int]] = {STATUS_OK: 0, STATUS_DEGRADED: 1, STATUS_DOWN: 2}

#: How many recent errors each category contributes to the payload. The ring
#: retains more; the wire keeps the response small enough to poll.
RECENT_ERROR_LIMIT: Final = 20

#: Row counts worth showing (SPEC §67 "useful row counts"). Deliberately a
#: curated list rather than every table: the point is to tell a user whether
#: their data is accumulating, not to dump the schema.
_ROW_COUNT_TABLES: Final[tuple[tuple[str, type[Any]], ...]] = (
    ("aircraft", Aircraft),
    ("sightings", Sighting),
    ("sighting_tracks", SightingTrack),
    ("activity_events", ActivityEvent),
    ("alert_matches", AlertMatch),
    ("aircraft_metadata", AircraftMetadata),
    ("airports", Airport),
    ("receiver_metrics_raw", ReceiverMetricRaw),
)


def _iso(moment: datetime | None) -> str | None:
    """Render an aware datetime as UTC ISO-8601 with a ``Z`` suffix (§2.2)."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso_from_ms(epoch_ms: int | None) -> str | None:
    """Render stored epoch milliseconds as an ISO-8601 instant."""
    if epoch_ms is None:
        return None
    return _iso(datetime.fromtimestamp(epoch_ms / 1000, UTC))


def _age_s(moment: datetime | None, now: datetime) -> float | None:
    """Seconds since ``moment``, clamped at zero to absorb clock skew."""
    if moment is None:
        return None
    return max(0.0, (now - moment.astimezone(UTC)).total_seconds())


def _worst(*states: str) -> str:
    """Return the most severe of the given roll-up states."""
    return max(states, key=lambda state: _STATUS_SEVERITY.get(state, 0))


def _state(app: FastAPI, name: str) -> Any:
    """Read an ``app.state`` attribute that may not exist yet.

    Services are assigned across ``create_app`` and the lifespan hook, and
    ``app.state.ingestion`` can be ``None`` for the whole life of a first-run
    process. Diagnostics is the one endpoint that must survive every one of
    those partial states, so every access goes through here.
    """
    return getattr(app.state, name, None)


def _versions(schema_revision: str | None) -> dict[str, Any]:
    """SPEC §67: frontend/backend version.

    The frontend is served from the same image and build as the backend, so its
    version *is* the backend's — the UI labels it rather than asking a second
    source that could disagree.
    """
    return {
        "backend": __version__,
        "frontend": __version__,
        "api": "v1",
        "schema_revision": schema_revision,
    }


def _uptime(app: FastAPI, now: datetime) -> dict[str, Any]:
    """SPEC §67: backend uptime, plus the decoder's own reported uptime."""
    start = _state(app, "start_time")
    backend_s = None if start is None else max(0.0, time.monotonic() - float(start))

    decoder_s: float | None = None
    metrics = _state(app, "receiver_metrics")
    if metrics is not None:
        stats = getattr(metrics, "latest_stats", None)
        if stats is not None:
            decoder_s = getattr(stats, "uptime_s", None)

    return {
        "backend_s": None if backend_s is None else round(backend_s, 3),
        # Derived rather than recorded: the process stores a monotonic origin,
        # which is the right clock for a duration but cannot name an instant.
        "started_at": None if backend_s is None else _iso(now - timedelta(seconds=backend_s)),
        "decoder_s": decoder_s,
    }


def _decoder_section(app: FastAPI) -> tuple[dict[str, Any], str]:
    """SPEC §67: decoder connection state. Returns the section and its status."""
    service = _state(app, "ingestion")
    demo = bool(_state(app, "demo_enabled"))

    if service is None:
        # A first-run install with no configured receiver. Not an outage:
        # there is nothing to be disconnected from yet.
        return (
            {
                "configured": False,
                "state": "unconfigured",
                "last_success": None,
                "last_failure": None,
                "last_error": None,
                "consecutive_failures": 0,
                "total_failures": 0,
                "total_successes": 0,
                "next_retry_delay_s": None,
                "batches_ingested": 0,
                "updates_ingested": 0,
                "demo_mode": demo,
            },
            STATUS_DEGRADED,
        )

    health = service.health()
    state = str(getattr(health.state, "value", health.state))
    status = {
        "connected": STATUS_OK,
        "degraded": STATUS_DEGRADED,
        "down": STATUS_DOWN,
    }.get(state, STATUS_DEGRADED)

    return (
        {
            "configured": True,
            "state": state,
            "last_success": _iso(health.last_success),
            "last_failure": _iso(health.last_failure),
            "last_error": health.last_error,
            "consecutive_failures": health.consecutive_failures,
            "total_failures": health.total_failures,
            "total_successes": health.total_successes,
            "next_retry_delay_s": health.next_retry_delay_s,
            "batches_ingested": getattr(service, "batches_ingested", 0),
            "updates_ingested": getattr(service, "updates_ingested", 0),
            "demo_mode": demo,
        },
        status,
    )


def _live_section(app: FastAPI, now: datetime) -> dict[str, Any]:
    """SPEC §67: last successful aircraft update, and what is currently visible."""
    live = _state(app, "live")
    if live is None:
        return {
            "last_aircraft_update": None,
            "last_aircraft_update_age_s": None,
            "total": 0,
            "positioned": 0,
            "non_positioned": 0,
            "stale": 0,
        }

    counts = live.counts()
    # The freshest `last_seen` across the live picture is the honest answer to
    # "last successful aircraft update": the decoder can be polling happily
    # while the sky is empty, which is a different fact from a broken feed.
    last_seen: datetime | None = None
    for aircraft in live.snapshot():
        seen = getattr(aircraft, "last_seen", None)
        if seen is not None and (last_seen is None or seen > last_seen):
            last_seen = seen

    return {
        "last_aircraft_update": _iso(last_seen),
        "last_aircraft_update_age_s": _age_s(last_seen, now),
        "total": counts.total,
        "positioned": counts.positioned,
        "non_positioned": counts.non_positioned,
        "stale": counts.stale,
    }


async def _row_counts(database: Database) -> dict[str, int | None]:
    """SPEC §67: useful row counts, read through a read-only session."""
    counts: dict[str, int | None] = {}
    async with database.read_session() as session:
        for label, model in _ROW_COUNT_TABLES:
            try:
                result = await session.execute(select(func.count()).select_from(model))
                counts[label] = int(result.scalar_one())
            except Exception:
                # One missing or unreadable table must not cost the user every
                # other count on the page.
                counts[label] = None
    return counts


def _maintenance_section(app: FastAPI) -> tuple[dict[str, Any], str]:
    """Maintenance outcomes and the retained quick_check (SPEC §70 into §67)."""
    service = _state(app, "maintenance")
    if service is None:
        return (
            {
                "cycles": 0,
                "last_cycle_at": None,
                "healthy": None,
                "jobs": {},
                "vacuum_refusal": None,
            },
            STATUS_OK,
        )

    report = service.report
    refusal = report.vacuum_refusal
    jobs = {
        name: {
            "outcome": str(getattr(job.outcome, "value", job.outcome)),
            "started_at": _iso_from_ms(job.started_ms),
            "duration_ms": job.duration_ms,
            "detail": dict(job.detail),
        }
        for name, job in report.jobs.items()
    }
    status = STATUS_OK if report.healthy else STATUS_DEGRADED
    return (
        {
            "cycles": report.cycles,
            "last_cycle_at": _iso_from_ms(report.last_cycle_ms),
            "healthy": report.healthy,
            "running": bool(getattr(service, "running", False)),
            "jobs": jobs,
            # Why the guarded VACUUM last declined, with the gap that caused
            # it. `None` once one runs, or before the job has ever been due
            # (issue #116). A refusal is not a degradation: declining to
            # rewrite a healthy database is the policy working, so this
            # informs without moving `status`.
            "vacuum_refusal": (
                None
                if refusal is None
                else {
                    "reason": refusal.reason,
                    "required_free_bytes": refusal.required_free_bytes,
                    "available_free_bytes": refusal.available_free_bytes,
                }
            ),
        },
        status,
    )


def _quick_check_section(app: FastAPI) -> tuple[dict[str, Any], str]:
    """SPEC §67: database health, as the last retained integrity check.

    The retained result is used rather than running a fresh ``quick_check``:
    that pragma takes the writer lock and walks the file, which is precisely
    the kind of work a read-only diagnostics request must not impose on a
    running receiver. Maintenance runs it on a schedule; this reports it.
    """
    service = _state(app, "maintenance")
    outcome = None if service is None else service.report.quick_check

    if outcome is None:
        return (
            {"healthy": None, "checked_at": None, "error": None, "rows": []},
            STATUS_OK,
        )

    return (
        {
            "healthy": outcome.healthy,
            "checked_at": _iso_from_ms(outcome.checked_ms),
            "error": outcome.error,
            "rows": list(outcome.rows),
        },
        STATUS_OK if outcome.healthy else STATUS_DOWN,
    )


def _recovery_section(app: FastAPI) -> tuple[dict[str, Any], str]:
    """Unclean-shutdown recovery outcome (SPEC §71 into §67)."""
    worker = _state(app, "persistence")
    report = None if worker is None else getattr(worker, "recovery", None)
    if report is None:
        return ({"recovered": 0, "continued": 0, "anomalies": 0, "failed": 0}, STATUS_OK)

    section = {
        "recovered": report.recovered,
        "continued": report.continued,
        "points_recovered": report.points_recovered,
        "orphan_checkpoints": report.orphan_checkpoints,
        "orphan_sightings": report.orphan_sightings,
        "failed": report.failed,
        "anomalies": report.anomalies,
    }
    return (section, STATUS_DEGRADED if report.anomalies else STATUS_OK)


async def _metadata_section(app: FastAPI, now: datetime) -> tuple[dict[str, Any], str]:
    """SPEC §67: metadata database age, per source and overall."""
    service = _state(app, "metadata")
    if service is None:
        return ({"sources": [], "oldest_success_at": None, "age_s": None}, STATUS_OK)

    records: Sequence[Any] = await service.statuses()
    sources: list[dict[str, Any]] = []
    newest_ms: int | None = None
    any_failed = False

    for record in records:
        status = str(getattr(record.status, "value", record.status))
        any_failed = any_failed or status == "failed"
        success_ms = record.last_success_ms
        if success_ms is not None and (newest_ms is None or success_ms > newest_ms):
            newest_ms = success_ms
        sources.append(
            {
                "source": record.source,
                "status": status,
                "last_attempt_at": _iso_from_ms(record.last_attempt_ms),
                "last_success_at": _iso_from_ms(success_ms),
                "age_s": (
                    None if success_ms is None else max(0.0, now.timestamp() - success_ms / 1000)
                ),
                "dataset_version": record.dataset_version,
                "row_count": record.row_count,
                "last_error": record.last_error,
                "running": bool(record.run.running),
            }
        )

    return (
        {
            "sources": sources,
            # "Metadata database age" as one number: the most recent successful
            # import across sources, which is what the user actually asks about.
            "newest_success_at": _iso_from_ms(newest_ms),
            "age_s": None if newest_ms is None else max(0.0, now.timestamp() - newest_ms / 1000),
        },
        STATUS_DEGRADED if any_failed else STATUS_OK,
    )


def _notifications_section(settings: Settings | None) -> dict[str, Any]:
    """SPEC §67: notification status, as far as the *backend* can know it.

    Browser permission is a client fact the server cannot observe, so this
    reports only the configured preferences and says so; the health page joins
    it with slice 040's store to show the permission the user actually granted.
    """
    if settings is None:
        return {"configured_enabled": False, "severities": {}, "permission_known_by": "client"}

    prefs = settings.notifications
    return {
        "configured_enabled": bool(prefs.enabled),
        "severities": {
            "info": bool(prefs.info),
            "interesting": bool(prefs.interesting),
            "high": bool(prefs.high),
            "critical": bool(prefs.critical),
        },
        "permission_known_by": "client",
    }


def _websocket_section(app: FastAPI, counter_values: Mapping[str, int]) -> dict[str, Any]:
    """SPEC §67: WebSocket issues."""
    broadcaster = _state(app, "broadcaster")
    return {
        "clients": 0 if broadcaster is None else int(getattr(broadcaster, "client_count", 0)),
        "running": bool(getattr(broadcaster, "running", False)),
        "disconnects": counter_values.get("ws_disconnects", 0),
        "events_dropped": counter_values.get("live_events_dropped", 0),
    }


def _enrichment_section(
    app: FastAPI, counter_values: Mapping[str, int], now: datetime
) -> dict[str, Any]:
    """SPEC §67: enrichment failures, and what the day's credits went on.

    ``budget`` and ``cache`` were added by slice 070 for the Health page's
    enrichment card. Both are read from the service's own memory — the budget
    ledger is refreshed from ``route_cache`` at start and at midnight, not per
    request — so this stays what the endpoint promises to be: no query, no
    writer session, nothing a diagnostics poll can make expensive.

    ``limit`` and ``remaining`` are ``null`` on an uncapped install, which is
    the default and is not the same as ``0``: one means "no ceiling", the other
    would mean "no lookups left today".
    """
    service = _state(app, "enrichment")
    return {
        "enabled": bool(getattr(service, "enabled", False)),
        "running": bool(getattr(service, "running", False)),
        "circuit_open": bool(getattr(service, "circuit_open", False)),
        "lookups": int(getattr(service, "lookups", 0)),
        "dropped": int(getattr(service, "dropped", 0)),
        "pending": int(getattr(service, "pending", 0)),
        "failures": counter_values.get("enrichment_failures", 0),
        "budget": _enrichment_budget(getattr(service, "budget", None), now),
        "cache": _enrichment_cache(getattr(service, "cache_stats", None)),
    }


def _enrichment_budget(budget: Any, now: datetime) -> dict[str, Any]:
    """The daily lookup budget, or an uncapped one when there is no service."""
    if budget is None:
        return {
            "limit": None,
            "used_today": 0,
            "remaining": None,
            "resets_at": _iso(_next_utc_midnight(now)),
        }
    limit = budget.limit
    remaining = budget.remaining
    return {
        "limit": None if limit is None else int(limit),
        "used_today": int(budget.used_today),
        "remaining": None if remaining is None else int(remaining),
        "resets_at": _iso_from_ms(budget.resets_at_ms),
    }


def _enrichment_cache(stats: Any) -> dict[str, int]:
    """Cache hits, misses, learned schedules and stale serves.

    ``stale_served`` is slice 071's addition: expired routes kept on their
    sightings because neither the offline directory nor the provider could
    answer at the time. A number that climbs is the honest signal that
    something upstream has been unavailable — the routes on screen are still
    real, but they are last week's.
    """
    if stats is None:
        return {"hits": 0, "misses": 0, "learned": 0, "stale_served": 0}
    return {
        "hits": int(stats.hits),
        "misses": int(stats.misses),
        "learned": int(stats.learned),
        "stale_served": int(getattr(stats, "stale_served", 0)),
    }


def _next_utc_midnight(now: datetime) -> datetime:
    """The next 00:00 UTC after ``now``."""
    midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(days=1)


def _error_payload(entry: RecentError) -> dict[str, Any]:
    return {
        "at": _iso(entry.at),
        "category": entry.category,
        "event": entry.event,
        "level": entry.level,
        "logger": entry.logger,
        "detail": entry.detail,
    }


def _recent_errors(ring: ErrorRing) -> dict[str, list[dict[str, Any]]]:
    """SPEC §67: recent ingestion / database / enrichment / WebSocket errors."""
    snapshot = ring.snapshot(limit=RECENT_ERROR_LIMIT)
    return {category: [_error_payload(e) for e in snapshot[category]] for category in CATEGORIES}


async def collect_diagnostics(
    app: FastAPI,
    *,
    counters: CounterRegistry | None = None,
    ring: ErrorRing | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the whole SPEC §67 diagnostics payload.

    The registries are injectable so a test can drive a deterministic snapshot
    instead of whatever the process happens to have accumulated.
    """
    moment = now or datetime.now(UTC)
    registry = counters if counters is not None else default_counters
    buffer = ring if ring is not None else default_error_ring
    counter_values = registry.snapshot()

    settings: Settings | None = _state(app, "settings")
    database: Database | None = _state(app, "database")
    readiness = _state(app, "readiness")

    schema_revision: str | None = None
    # §2.7: the key set stays stable and ``null`` means unknown, so the
    # unreadable-database branch publishes exactly the keys the readable one
    # does rather than a shorter object the client has to feature-detect.
    storage: dict[str, Any] = {
        "database_bytes": None,
        "file_bytes": None,
        "wal_bytes": None,
        "reclaimable_bytes": None,
        "reclaimable_ratio": None,
        "disk_free_bytes": None,
        "page_count": None,
        "page_size": None,
    }
    row_counts: dict[str, int | None] = {}
    database_reachable = True

    if database is not None:
        try:
            stats = await gather_stats(database)
            storage = {
                "database_bytes": stats.db_bytes,
                "file_bytes": stats.file_bytes,
                "wal_bytes": stats.wal_bytes,
                "reclaimable_bytes": stats.reclaimable_bytes,
                "reclaimable_ratio": round(stats.reclaimable_ratio, 4),
                "disk_free_bytes": stats.free_bytes,
                "page_count": stats.page_count,
                "page_size": stats.page_size,
            }
            row_counts = await _row_counts(database)
            schema_revision = await database.current_revision()
        except Exception:
            # An unreadable database is itself a diagnostic, and the rest of
            # the page is still worth rendering.
            database_reachable = False

    decoder, decoder_status = _decoder_section(app)
    maintenance, maintenance_status = _maintenance_section(app)
    quick_check, quick_check_status = _quick_check_section(app)
    recovery, recovery_status = _recovery_section(app)
    metadata, metadata_status = await _metadata_section(app, moment)

    database_status = _worst(
        quick_check_status,
        maintenance_status,
        recovery_status,
        STATUS_OK if database_reachable else STATUS_DOWN,
    )

    payload: dict[str, Any] = {
        "generated_at": _iso(moment),
        "status": _worst(decoder_status, database_status, metadata_status),
        "ready": bool(getattr(readiness, "is_ready", False)),
        "subsystems": dict(readiness.snapshot()) if readiness is not None else {},
        "versions": _versions(schema_revision),
        "uptime": _uptime(app, moment),
        "decoder": decoder,
        "live": _live_section(app, moment),
        "database": {
            "status": database_status,
            "reachable": database_reachable,
            "quick_check": quick_check,
            "storage": storage,
            "row_counts": row_counts,
            "maintenance": maintenance,
            "recovery": recovery,
        },
        "metadata": metadata,
        "notifications": _notifications_section(settings),
        "enrichment": _enrichment_section(app, counter_values, moment),
        "websocket": _websocket_section(app, counter_values),
        "counters": dict(counter_values),
        "recent_errors": _recent_errors(buffer),
    }

    # Belt and braces over the whole payload, not only the fields believed to
    # be risky. Redaction on the way into the ring already covers captured log
    # text; this second pass means a *new* section added by a later slice
    # cannot leak a configured secret without that slice noticing, because the
    # secret-absence test walks this same output.
    return redact_value(payload, secrets_from_settings(settings))  # type: ignore[no-any-return]
