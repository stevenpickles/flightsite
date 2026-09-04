"""Degraded-state rendering for the diagnostics aggregator (SPEC §67).

:func:`collect_diagnostics` reads only ``app.state``, so these tests drive it
with a stub instead of a running application. That is the point: the states
worth testing — a decoder that is down, an integrity check that failed, a
database that cannot be read at all — are awkward to provoke in a real app and
trivial to describe here, and the roadmap asks for "sensible degraded-state
rendering" for every item rather than only the healthy path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from flightsite.counters import CounterRegistry
from flightsite.diagnostics import STATUS_DEGRADED, STATUS_DOWN, STATUS_OK
from flightsite.diagnostics.errors import DATABASE, INGESTION, ErrorRing
from flightsite.diagnostics.service import collect_diagnostics
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.maintenance.model import (
    JobOutcome,
    JobReport,
    MaintenanceReport,
    QuickCheckOutcome,
    VacuumRefusal,
)
from flightsite.metadata.registry import SourceRunState, SourceStatus, SourceStatusRecord
from flightsite.sightings.recovery import RecoveryReport

NOW = datetime(2026, 8, 31, 14, 0, 0, tzinfo=UTC)


@dataclass
class _FakeIngestion:
    health_value: AdapterHealth
    batches_ingested: int = 0
    updates_ingested: int = 0

    def health(self) -> AdapterHealth:
        return self.health_value


class _FakeMetadata:
    def __init__(self, records: tuple[SourceStatusRecord, ...]) -> None:
        self._records = records

    async def statuses(self) -> tuple[SourceStatusRecord, ...]:
        return self._records


def _app(**state: Any) -> Any:
    """A stand-in exposing only what the collector reads."""
    return SimpleNamespace(state=SimpleNamespace(**state))


def _connected_decoder() -> _FakeIngestion:
    """A healthy decoder, so a roll-up assertion isolates what it is testing.

    Without one the collector correctly reports ``unconfigured`` and degrades
    the whole install — which would make a metadata assertion pass for the
    wrong reason.
    """
    return _FakeIngestion(AdapterHealth(state=HealthState.CONNECTED))


async def _collect(**state: Any) -> dict[str, Any]:
    return await collect_diagnostics(
        _app(**state),
        counters=CounterRegistry(),
        ring=ErrorRing(),
        now=NOW,
    )


class TestDecoderState:
    @pytest.mark.asyncio
    async def test_no_decoder_reads_as_unconfigured_not_down(self) -> None:
        """A first-run install is not an outage — there is nothing to be down."""
        payload = await _collect(ingestion=None)

        assert payload["decoder"]["state"] == "unconfigured"
        assert payload["decoder"]["configured"] is False
        assert payload["status"] == STATUS_DEGRADED

    @pytest.mark.asyncio
    async def test_a_connected_decoder_is_ok(self) -> None:
        payload = await _collect(
            ingestion=_FakeIngestion(
                AdapterHealth(
                    state=HealthState.CONNECTED,
                    last_success=NOW - timedelta(seconds=2),
                    total_successes=91,
                ),
                batches_ingested=12,
                updates_ingested=340,
            )
        )

        decoder = payload["decoder"]
        assert decoder["state"] == "connected"
        assert decoder["last_success"] == "2026-08-31T13:59:58.000Z"
        assert decoder["batches_ingested"] == 12
        assert payload["status"] == STATUS_OK

    @pytest.mark.asyncio
    async def test_a_down_decoder_drives_the_overall_status_down(self) -> None:
        payload = await _collect(
            ingestion=_FakeIngestion(
                AdapterHealth(
                    state=HealthState.DOWN,
                    consecutive_failures=7,
                    last_error="connection refused",
                    last_failure=NOW - timedelta(seconds=5),
                    next_retry_delay_s=30.0,
                )
            )
        )

        assert payload["decoder"]["state"] == "down"
        assert payload["decoder"]["last_error"] == "connection refused"
        assert payload["decoder"]["next_retry_delay_s"] == 30.0
        assert payload["status"] == STATUS_DOWN

    @pytest.mark.asyncio
    async def test_a_degraded_decoder_is_reported_as_degraded(self) -> None:
        payload = await _collect(
            ingestion=_FakeIngestion(AdapterHealth(state=HealthState.DEGRADED))
        )

        assert payload["decoder"]["state"] == "degraded"
        assert payload["status"] == STATUS_DEGRADED


class TestLivePicture:
    @pytest.mark.asyncio
    async def test_the_freshest_last_seen_is_the_last_aircraft_update(self) -> None:
        live = SimpleNamespace(
            counts=lambda: SimpleNamespace(total=2, positioned=1, non_positioned=1, stale=0),
            snapshot=lambda: (
                SimpleNamespace(last_seen=NOW - timedelta(seconds=30)),
                SimpleNamespace(last_seen=NOW - timedelta(seconds=4)),
            ),
        )
        payload = await _collect(live=live)

        assert payload["live"]["last_aircraft_update"] == "2026-08-31T13:59:56.000Z"
        assert payload["live"]["last_aircraft_update_age_s"] == 4.0
        assert payload["live"]["total"] == 2

    @pytest.mark.asyncio
    async def test_an_empty_sky_reports_null_rather_than_an_error(self) -> None:
        """No aircraft is a normal night, not a fault."""
        live = SimpleNamespace(
            counts=lambda: SimpleNamespace(total=0, positioned=0, non_positioned=0, stale=0),
            snapshot=lambda: (),
        )
        payload = await _collect(live=live)

        assert payload["live"]["last_aircraft_update"] is None
        assert payload["live"]["last_aircraft_update_age_s"] is None


class TestDatabaseHealth:
    @pytest.mark.asyncio
    async def test_a_failed_quick_check_takes_the_database_down(self) -> None:
        report = MaintenanceReport(
            quick_check=QuickCheckOutcome(
                healthy=False,
                checked_ms=int((NOW - timedelta(minutes=5)).timestamp() * 1000),
                rows=("row 3 missing from index",),
                error=None,
            )
        )
        payload = await _collect(maintenance=SimpleNamespace(report=report, running=True))

        assert payload["database"]["quick_check"]["healthy"] is False
        assert payload["database"]["quick_check"]["rows"] == ["row 3 missing from index"]
        assert payload["database"]["status"] == STATUS_DOWN
        assert payload["status"] == STATUS_DOWN

    @pytest.mark.asyncio
    async def test_a_never_run_quick_check_is_unknown_not_unhealthy(self) -> None:
        payload = await _collect(
            maintenance=SimpleNamespace(report=MaintenanceReport(), running=True)
        )

        assert payload["database"]["quick_check"]["healthy"] is None
        assert payload["database"]["status"] == STATUS_OK

    @pytest.mark.asyncio
    async def test_a_failed_maintenance_job_degrades_the_database(self) -> None:
        report = MaintenanceReport(
            cycles=4,
            last_cycle_ms=int(NOW.timestamp() * 1000),
            jobs={
                "retention": JobReport(
                    name="retention",
                    outcome=JobOutcome.FAILED,
                    started_ms=int(NOW.timestamp() * 1000),
                    duration_ms=12,
                    detail={"error": "disk full"},
                )
            },
        )
        payload = await _collect(maintenance=SimpleNamespace(report=report, running=True))

        maintenance = payload["database"]["maintenance"]
        assert maintenance["healthy"] is False
        assert maintenance["cycles"] == 4
        assert maintenance["jobs"]["retention"]["outcome"] == "failed"
        assert maintenance["jobs"]["retention"]["detail"] == {"error": "disk full"}
        assert payload["database"]["status"] == STATUS_DEGRADED

    @pytest.mark.asyncio
    async def test_a_vacuum_refusal_reaches_diagnostics_with_its_numbers(self) -> None:
        """Issue #116: the Health page's only route to "why has this never run?".

        The gap travels with the reason because the free-space requirement
        scales with the database — without both numbers an operator cannot see
        that this particular refusal will never clear on its own.
        """
        report = MaintenanceReport(
            cycles=9,
            last_cycle_ms=int(NOW.timestamp() * 1000),
            vacuum_refusal=VacuumRefusal(
                reason="insufficient_free_space",
                required_free_bytes=9_000_000_000,
                available_free_bytes=3_100_000_000,
            ),
        )
        payload = await _collect(maintenance=SimpleNamespace(report=report, running=True))

        refusal = payload["database"]["maintenance"]["vacuum_refusal"]
        assert refusal == {
            "reason": "insufficient_free_space",
            "required_free_bytes": 9_000_000_000,
            "available_free_bytes": 3_100_000_000,
        }
        # Declining to rewrite a healthy database is the policy working, so it
        # informs without degrading the database's status.
        assert payload["database"]["status"] == STATUS_OK

    @pytest.mark.asyncio
    async def test_no_vacuum_refusal_is_reported_as_null_not_omitted(self) -> None:
        """The key set stays stable; ``null`` is how "nothing to report" is said."""
        payload = await _collect(
            maintenance=SimpleNamespace(report=MaintenanceReport(cycles=1), running=True)
        )

        assert payload["database"]["maintenance"]["vacuum_refusal"] is None

    @pytest.mark.asyncio
    async def test_recovery_anomalies_are_surfaced(self) -> None:
        worker = SimpleNamespace(recovery=RecoveryReport(recovered=3, orphan_sightings=2, failed=1))
        payload = await _collect(persistence=worker)

        assert payload["database"]["recovery"]["recovered"] == 3
        assert payload["database"]["recovery"]["anomalies"] == 3
        assert payload["database"]["status"] == STATUS_DEGRADED

    @pytest.mark.asyncio
    async def test_a_clean_recovery_is_not_a_problem(self) -> None:
        worker = SimpleNamespace(recovery=RecoveryReport(recovered=5, continued=2))
        payload = await _collect(persistence=worker)

        assert payload["database"]["recovery"]["anomalies"] == 0
        assert payload["database"]["status"] == STATUS_OK

    @pytest.mark.asyncio
    async def test_an_unreadable_database_is_reported_not_raised(self) -> None:
        """The rest of the page is still worth rendering."""

        class _BrokenDatabase:
            def read_session(self) -> Any:
                raise OSError("disk I/O error")

        payload = await _collect(database=_BrokenDatabase())

        assert payload["database"]["reachable"] is False
        assert payload["database"]["status"] == STATUS_DOWN
        assert payload["database"]["storage"]["database_bytes"] is None
        # The key set stays stable even on the failure path (§2.7).
        assert "file_bytes" in payload["database"]["storage"]
        assert payload["versions"]["backend"]


class TestMetadataAge:
    @pytest.mark.asyncio
    async def test_the_newest_successful_import_is_the_overall_age(self) -> None:
        older = int((NOW - timedelta(days=9)).timestamp() * 1000)
        newer = int((NOW - timedelta(days=2)).timestamp() * 1000)
        service = _FakeMetadata(
            (
                SourceStatusRecord(
                    source="mictronics",
                    status=SourceStatus.OK,
                    last_success_ms=older,
                    row_count=100,
                ),
                SourceStatusRecord(
                    source="faa",
                    status=SourceStatus.OK,
                    last_success_ms=newer,
                    row_count=200,
                ),
            )
        )
        payload = await _collect(metadata=service, ingestion=_connected_decoder())

        assert payload["metadata"]["age_s"] == pytest.approx(2 * 86400)
        assert len(payload["metadata"]["sources"]) == 2
        assert payload["status"] == STATUS_OK

    @pytest.mark.asyncio
    async def test_a_failed_source_degrades_the_install(self) -> None:
        service = _FakeMetadata(
            (
                SourceStatusRecord(
                    source="faa",
                    status=SourceStatus.FAILED,
                    last_error="download timed out",
                    run=SourceRunState(running=False),
                ),
            )
        )
        payload = await _collect(metadata=service, ingestion=_connected_decoder())

        assert payload["metadata"]["sources"][0]["last_error"] == "download timed out"
        assert payload["status"] == STATUS_DEGRADED

    @pytest.mark.asyncio
    async def test_never_imported_metadata_has_no_age(self) -> None:
        service = _FakeMetadata(
            (SourceStatusRecord(source="mictronics", status=SourceStatus.NEVER_RUN),)
        )
        payload = await _collect(metadata=service, ingestion=_connected_decoder())

        assert payload["metadata"]["age_s"] is None
        assert payload["metadata"]["newest_success_at"] is None
        assert payload["status"] == STATUS_OK


class TestEnrichmentSection:
    """The Health page's enrichment card reads these keys and no others."""

    #: 2026-08-31T00:00:00Z — the midnight after :data:`NOW`.
    MIDNIGHT_MS = 1_788_134_400_000

    @classmethod
    def _service(cls, **overrides: Any) -> Any:
        state: dict[str, Any] = {
            "enabled": True,
            "running": True,
            "circuit_open": False,
            "lookups": 308,
            "dropped": 0,
            "pending": 2,
            "budget": SimpleNamespace(
                limit=500, used_today=137, remaining=363, resets_at_ms=cls.MIDNIGHT_MS
            ),
            "cache_stats": SimpleNamespace(hits=4_112, misses=308, learned=57),
        }
        state.update(overrides)
        return SimpleNamespace(**state)

    @pytest.mark.asyncio
    async def test_the_budget_and_cache_counters_reach_the_payload(self) -> None:
        app = _app(enrichment=self._service())

        payload = await collect_diagnostics(
            app, counters=CounterRegistry(), ring=ErrorRing(), now=NOW
        )

        assert payload["enrichment"]["budget"] == {
            "limit": 500,
            "used_today": 137,
            "remaining": 363,
            "resets_at": "2026-08-31T00:00:00.000Z",
        }
        assert payload["enrichment"]["cache"] == {"hits": 4_112, "misses": 308, "learned": 57}

    @pytest.mark.asyncio
    async def test_an_uncapped_budget_reports_null_rather_than_zero(self) -> None:
        """``null`` means "no ceiling"; ``0`` would mean "nothing left today"."""
        service = self._service(
            budget=SimpleNamespace(
                limit=None, used_today=12, remaining=None, resets_at_ms=self.MIDNIGHT_MS
            )
        )

        payload = await collect_diagnostics(
            _app(enrichment=service), counters=CounterRegistry(), ring=ErrorRing(), now=NOW
        )

        budget = payload["enrichment"]["budget"]
        assert (budget["limit"], budget["remaining"]) == (None, None)
        assert budget["used_today"] == 12

    @pytest.mark.asyncio
    async def test_a_process_with_no_enrichment_service_still_answers(self) -> None:
        """Every section degrades rather than failing — including this one."""
        payload = await collect_diagnostics(
            _app(), counters=CounterRegistry(), ring=ErrorRing(), now=NOW
        )

        assert payload["enrichment"]["budget"] == {
            "limit": None,
            "used_today": 0,
            "remaining": None,
            "resets_at": "2026-09-01T00:00:00.000Z",
        }
        assert payload["enrichment"]["cache"] == {"hits": 0, "misses": 0, "learned": 0}


class TestCountersAndErrors:
    @pytest.mark.asyncio
    async def test_counter_values_reach_their_sections(self) -> None:
        registry = CounterRegistry()
        registry.increment("enrichment_failures", 4)
        registry.increment("ws_disconnects", 2)
        registry.increment("live_events_dropped", 9)

        payload = await collect_diagnostics(_app(), counters=registry, ring=ErrorRing(), now=NOW)

        assert payload["enrichment"]["failures"] == 4
        assert payload["websocket"]["disconnects"] == 2
        assert payload["websocket"]["events_dropped"] == 9
        assert payload["counters"]["enrichment_failures"] == 4

    @pytest.mark.asyncio
    async def test_recent_errors_are_grouped_by_category(self) -> None:
        ring = ErrorRing()
        ring.record(
            at=NOW,
            category=INGESTION,
            event="decoder_poll_failed",
            level="WARNING",
            logger="flightsite.ingest.readsb",
        )
        ring.record(
            at=NOW,
            category=DATABASE,
            event="write_failed",
            level="ERROR",
            logger="flightsite.sightings.worker",
        )

        payload = await collect_diagnostics(_app(), counters=CounterRegistry(), ring=ring, now=NOW)

        assert payload["recent_errors"]["ingestion"][0]["event"] == "decoder_poll_failed"
        assert payload["recent_errors"]["database"][0]["level"] == "ERROR"
        assert payload["recent_errors"]["enrichment"] == []

    @pytest.mark.asyncio
    async def test_the_wire_list_is_bounded_even_when_the_ring_holds_more(self) -> None:
        """A long outage must not produce an unbounded response."""
        ring = ErrorRing(capacity=200)
        for index in range(200):
            ring.record(
                at=NOW,
                category=INGESTION,
                event=f"failure-{index}",
                level="WARNING",
                logger="flightsite.ingest.readsb",
            )

        payload = await collect_diagnostics(_app(), counters=CounterRegistry(), ring=ring, now=NOW)

        assert len(payload["recent_errors"]["ingestion"]) == 20


class TestNotificationsAndVersions:
    @pytest.mark.asyncio
    async def test_the_backend_defers_browser_permission_to_the_client(self) -> None:
        """No server can observe a browser permission; saying so is the honest answer."""
        payload = await _collect()

        assert payload["notifications"]["permission_known_by"] == "client"

    @pytest.mark.asyncio
    async def test_configured_notification_preferences_are_reported(self) -> None:
        from flightsite.config.models import Settings

        settings = Settings()
        settings.notifications.enabled = True
        settings.notifications.critical = True
        payload = await _collect(settings=settings)

        assert payload["notifications"]["configured_enabled"] is True
        assert payload["notifications"]["severities"]["critical"] is True

    @pytest.mark.asyncio
    async def test_versions_are_always_present(self) -> None:
        """Version is the one item that must never be unknown."""
        payload = await _collect()

        assert payload["versions"]["backend"]
        assert payload["versions"]["frontend"] == payload["versions"]["backend"]
        assert payload["versions"]["api"] == "v1"

    @pytest.mark.asyncio
    async def test_uptime_is_derived_from_the_monotonic_origin(self) -> None:
        import time

        payload = await _collect(start_time=time.monotonic() - 3600)

        assert payload["uptime"]["backend_s"] == pytest.approx(3600, abs=5)
        assert payload["uptime"]["started_at"] is not None

    @pytest.mark.asyncio
    async def test_uptime_is_unknown_before_the_app_records_a_start(self) -> None:
        payload = await _collect()

        assert payload["uptime"]["backend_s"] is None
        assert payload["uptime"]["started_at"] is None
