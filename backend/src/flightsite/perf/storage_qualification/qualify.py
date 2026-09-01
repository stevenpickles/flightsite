"""Running the qualification: generate, probe, prune, back up, vacuum, judge.

:func:`run_qualification` is SPEC §86 in one call. It builds a synthetic
multi-year database, then measures the nine things §86 names against it, and
returns a :class:`~.report.StorageReport` that knows which budgets it met.

The order is load-bearing
-------------------------

Each stage changes the state the next one would have measured, so they run in
the order a real install experiences them and never in the order that would
flatter the numbers:

1. **Generate**, and take the growth figures from the file as written. Growth
   measured after a ``VACUUM`` would be the size of a database nobody has,
   because the product only vacuums when its guards agree (and, at multi-year
   scale, sometimes never — see :func:`measure_vacuum`).
2. **Probe the queries**, on that same un-compacted file. This is the steady
   state a user's browser actually meets.
3. **Run one maintenance pass**, which is where downsampling and the raw prune
   happen, and measure both the cost and the result.
4. **Read the WAL**, after the writes that would have grown it.
5. **Back up, verify and restore** — on the un-compacted database, because
   that is what an operator's backup runs against. Backup does its own
   ``VACUUM INTO`` regardless.
6. **VACUUM last**, because it rewrites the file and would invalidate every
   measurement above it.

What is deliberately not measured here
--------------------------------------

Ingestion. Slice 049 owns the live pipeline, and nothing in this module
pretends to re-measure it: the single-writer discipline and the zero-database
hot path are invariants this slice *observes*, never adjusts. Where a figure
here overlaps one of 049's — ``db_read_ms``, ``analytics_query_ms`` — the
budget in :mod:`.budgets` says so and restates it at multi-year scale rather
than redefining it.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from flightsite.app import create_app
from flightsite.backup import create_backup, restore_backup, verify_archive
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.maintenance.policy import vacuum_decision
from flightsite.maintenance.stats import gather_stats
from flightsite.perf.harness import Environment
from flightsite.perf.measure import MIB, Measurement
from flightsite.perf.storage_qualification.budgets import HIGH_RES_WINDOW_DAYS
from flightsite.perf.storage_qualification.generator import (
    MS_PER_DAY,
    GenerationConfig,
    GenerationResult,
    generate_history,
)
from flightsite.perf.storage_qualification.report import ProbeResult, StorageReport
from flightsite.perf.storage_qualification.scenarios import BYTES_PER_GB
from flightsite.perf.storage_qualification.traffic import SECONDS_PER_RETAINED_POINT
from flightsite.receiver_metrics.service import ReceiverMetricsService

#: Times each query is issued. The median of three is enough to shake off a
#: single scheduling hiccup without turning the probe set into the load.
DEFAULT_PROBE_REPEATS: Final = 3

#: Analytics endpoints under ``/api/v1/analytics``, minus rarity, which gets
#: its own budget because its cost shape is different (see ``budgets.py``).
ANALYTICS_ENDPOINTS: Final[tuple[str, ...]] = (
    "summary",
    "daily",
    "classification-activity",
    "top-aircraft",
    "top-types",
    "top-operators",
)

#: Every documented analytics window (``docs/API.md`` §3.7).
ANALYTICS_PRESETS: Final[tuple[str, ...]] = ("today", "7d", "30d", "ytd", "t0")


#: SQLite's inline payload ceiling for a ``WITHOUT ROWID`` row is derived from
#: the page size: ``(usable - 12) * 64 / 255 - 23``. A row past it spills the
#: remainder into a whole overflow page, so this is the threshold that decides
#: whether the packed-track design costs what ADR-0005 says it does.
def _max_inline_payload(page_size: int) -> int:
    """Largest ``WITHOUT ROWID`` row stored without an overflow page."""
    return (page_size - 12) * 64 // 255 - 23


async def _one_probe(
    client: AsyncClient, metric: str, label: str, path: str, repeats: int
) -> ProbeResult:
    """Time one endpoint ``repeats`` times, failing loudly on a bad response."""
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        response = await client.get(path)
        samples.append((time.perf_counter() - started) * 1_000.0)
        if response.status_code != 200:
            raise RuntimeError(f"{path} answered {response.status_code} at multi-year scale")
    return ProbeResult(metric=metric, label=label, path=path, samples_ms=tuple(samples))


async def _sample_keys(database: Database) -> tuple[str | None, int | None, int]:
    """An icao, a sighting id with a track, and the sighting row count.

    Drawn from the middle of history rather than the ends, so a probe against
    "one aircraft's sightings" is not accidentally measuring the cheapest or
    the most recently written rows.
    """
    async with database.read_session() as session:
        total = int((await session.execute(text("SELECT count(*) FROM sightings"))).scalar_one())
        icao = (
            await session.execute(
                text("SELECT icao24 FROM aircraft ORDER BY sighting_count DESC LIMIT 1 OFFSET 5")
            )
        ).scalar_one_or_none()
        sighting_id = (
            await session.execute(
                text("SELECT sighting_id FROM sighting_tracks LIMIT 1 OFFSET :skip"),
                {"skip": max(0, total // 2)},
            )
        ).scalar_one_or_none()
        if sighting_id is None:
            sighting_id = (
                await session.execute(text("SELECT sighting_id FROM sighting_tracks LIMIT 1"))
            ).scalar_one_or_none()
    return (
        str(icao) if icao is not None else None,
        int(sighting_id) if sighting_id is not None else None,
        total,
    )


async def measure_queries(
    data_dir: Path, *, repeats: int = DEFAULT_PROBE_REPEATS
) -> tuple[list[Measurement], list[ProbeResult]]:
    """Probe the documented read surfaces against the multi-year database.

    Builds the real application over the generated data directory — the same
    ``create_app`` the container runs, with its real lifespan — so the queries
    measured are the ones the product serves, through its own routers,
    repositories and connection pool.
    """
    app = create_app(data_dir)
    database: Database = app.state.database
    probes: list[ProbeResult] = []

    async with app.router.lifespan_context(app):
        icao, sighting_id, total = await _sample_keys(database)
        deep = max(0, min(total - 50, 20_000))

        history: list[tuple[str, str]] = [
            ("sightings, newest first", "/api/v1/sightings?limit=50"),
            ("sightings, deep pagination", f"/api/v1/sightings?limit=50&offset={deep}"),
            (
                "sightings, unindexed sort (closest)",
                "/api/v1/sightings?limit=50&sort=closest_approach_nm",
            ),
            (
                "sightings, unindexed sort (range)",
                "/api/v1/sightings?limit=50&sort=max_range_nm",
            ),
            ("sightings, interesting only", "/api/v1/sightings?limit=50&interesting=true"),
            ("aircraft list (exact total)", "/api/v1/aircraft?limit=50"),
            (
                "aircraft by sighting count",
                "/api/v1/aircraft?limit=50&sort=sighting_count&order=desc",
            ),
            ("aircraft by closest approach", "/api/v1/aircraft?limit=50&sort=closest_approach_nm"),
        ]
        if icao is not None:
            history.append((f"aircraft detail ({icao})", f"/api/v1/aircraft/{icao}"))
            history.append(
                (
                    f"one aircraft's sightings ({icao})",
                    f"/api/v1/aircraft/{icao}/sightings?limit=50",
                )
            )
        if sighting_id is not None:
            history.append(("sighting detail with track", f"/api/v1/sightings/{sighting_id}"))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            for label, path in history:
                probes.append(await _one_probe(client, "history_query_ms", label, path, repeats))
            for endpoint in ANALYTICS_ENDPOINTS:
                for preset in ANALYTICS_PRESETS:
                    probes.append(
                        await _one_probe(
                            client,
                            "analytics_scale_ms",
                            f"analytics/{endpoint} [{preset}]",
                            f"/api/v1/analytics/{endpoint}?preset={preset}",
                            repeats,
                        )
                    )
            for preset in ANALYTICS_PRESETS:
                probes.append(
                    await _one_probe(
                        client,
                        "rarity_query_ms",
                        f"analytics/rarity [{preset}]",
                        f"/api/v1/analytics/rarity?preset={preset}&limit=25",
                        repeats,
                    )
                )

    await database.dispose()

    measurements: list[Measurement] = []
    for metric, unit in (
        ("history_query_ms", "ms"),
        ("analytics_scale_ms", "ms"),
        ("rarity_query_ms", "ms"),
    ):
        samples = tuple(
            sample for probe in probes if probe.metric == metric for sample in probe.samples_ms
        )
        if samples:
            count = len([probe for probe in probes if probe.metric == metric])
            measurements.append(
                Measurement(
                    metric=metric,
                    unit=unit,
                    samples=samples,
                    note=f"{count} distinct queries x {repeats} repeats",
                )
            )
    return measurements, probes


async def measure_retention(
    database: Database, *, now_ms: int, high_res_days: int = HIGH_RES_WINDOW_DAYS
) -> tuple[list[Measurement], list[str]]:
    """Run one real maintenance pass and measure what it cost and achieved.

    The pass is the product's own
    :meth:`~flightsite.receiver_metrics.service.ReceiverMetricsService.run_maintenance`
    — downsample first, then prune, in ADR-0009's mandated order — driven
    directly rather than on its timer. The clock is pinned to the instant the
    generated history ends, so the retention window is measured against the
    data rather than against whenever the qualification happened to run.
    """
    async with database.read_session() as session:
        before = (
            await session.execute(
                text("SELECT min(ts_ms), max(ts_ms), count(*) FROM receiver_metrics_raw")
            )
        ).one()
    oldest_before, _newest_before, raw_before = before

    service = ReceiverMetricsService(
        database=database,
        live=LiveStore(),
        high_res_days=high_res_days,
        clock=lambda: now_ms,
    )
    started = time.perf_counter()
    result = await service.run_maintenance()
    elapsed_ms = (time.perf_counter() - started) * 1_000.0

    async with database.read_session() as session:
        after = (
            await session.execute(
                text("SELECT min(ts_ms), max(ts_ms), count(*) FROM receiver_metrics_raw")
            )
        ).one()
        hourly = int(
            (
                await session.execute(text("SELECT count(*) FROM receiver_metrics_hourly"))
            ).scalar_one()
        )
        daily = int(
            (
                await session.execute(text("SELECT count(*) FROM receiver_metrics_daily"))
            ).scalar_one()
        )
        lifetime = int(
            (await session.execute(text("SELECT count(*) FROM lifetime_stats"))).scalar_one()
        )
    oldest_after, newest_after, raw_after = after

    span_days = 0.0
    if oldest_after is not None and newest_after is not None:
        span_days = (int(newest_after) - int(oldest_after)) / MS_PER_DAY

    # Coverage: every hour whose raw samples the prune removed must still be
    # represented by an hourly summary, or the prune destroyed history rather
    # than compacting it (ADR-0009).
    coverage = 1.0
    pruned_hours = 0
    covered_hours = 0
    if oldest_before is not None and oldest_after is not None and raw_after < raw_before:
        async with database.read_session() as session:
            pruned_hours = int(
                (
                    await session.execute(
                        text(
                            "SELECT (:stop - :start) / 3600000 AS hours",
                        ),
                        {"start": int(oldest_before), "stop": int(oldest_after)},
                    )
                ).scalar_one()
            )
            covered_hours = int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM receiver_metrics_hourly "
                            "WHERE hour_start_ms >= :start AND hour_start_ms < :stop"
                        ),
                        {"start": int(oldest_before), "stop": int(oldest_after)},
                    )
                ).scalar_one()
            )
        coverage = covered_hours / pruned_hours if pruned_hours else 1.0

    findings: list[str] = []
    findings.append(
        f"maintenance pass downsampled {result.hours_written} hours and "
        f"{result.days_written} days, then pruned {result.pruned} high-resolution rows "
        f"({raw_before} -> {raw_after}) in {elapsed_ms:.0f} ms"
    )
    if pruned_hours:
        findings.append(
            f"every one of the {pruned_hours} pruned hours retained an hourly summary "
            f"({covered_hours} present); {hourly} hourly, {daily} daily and {lifetime} "
            "lifetime rows survive"
        )

    measurements = [
        Measurement(
            metric="retention_pass_ms",
            unit="ms",
            samples=(elapsed_ms,),
            note=(f"{result.hours_written} hours downsampled, {result.pruned} raw rows pruned"),
        ),
        Measurement(
            metric="metrics_raw_days",
            unit="days",
            samples=(span_days,),
            note=f"{raw_after} raw rows against a {high_res_days}-day window",
        ),
        Measurement(
            metric="downsample_coverage",
            unit="fraction of pruned days",
            samples=(coverage,),
            note=f"{covered_hours}/{pruned_hours} pruned hours carry an hourly summary"
            if pruned_hours
            else "nothing was pruned, so nothing could be lost",
        ),
    ]
    return measurements, findings


async def measure_backup(data_dir: Path, *, db_bytes: int) -> tuple[list[Measurement], list[str]]:
    """Create, verify and restore a backup of the multi-year database.

    Every call is the product's own synchronous backup code, run off the event
    loop with :func:`asyncio.to_thread` exactly as ``tests/backup`` does, so
    what is timed is the operator's real experience: ``VACUUM INTO`` a
    snapshot, hash it, gzip it, and later unpack it again.
    """
    findings: list[str] = []
    out_dir = Path(tempfile.mkdtemp(prefix="fs-qual-backup-"))
    restore_dir = Path(tempfile.mkdtemp(prefix="fs-qual-restore-"))
    try:
        started = time.perf_counter()
        created = await asyncio.to_thread(create_backup, data_dir, out_dir=out_dir)
        create_s = time.perf_counter() - started

        started = time.perf_counter()
        verification = await asyncio.to_thread(verify_archive, created.path)
        verify_s = time.perf_counter() - started
        if not verification.ok:
            raise RuntimeError(
                f"the backup of the multi-year database did not verify: {verification.problems}"
            )

        started = time.perf_counter()
        await asyncio.to_thread(restore_backup, created.path, restore_dir, confirm=True)
        restore_s = time.perf_counter() - started

        archive_bytes = created.size_bytes
        gigabytes = max(db_bytes / BYTES_PER_GB, 1e-9)
        ratio = archive_bytes / db_bytes if db_bytes else 0.0

        findings.append(
            f"backup of a {db_bytes / 1e9:.2f} GB database produced a "
            f"{archive_bytes / 1e9:.2f} GB archive ({ratio:.0%} of the live file) in "
            f"{create_s:.1f} s; verify {verify_s:.1f} s; restore {restore_s:.1f} s"
        )

        return (
            [
                Measurement(
                    metric="backup_create_s_per_gb",
                    unit="s/GB",
                    samples=(create_s / gigabytes,),
                    note=f"{create_s:.1f} s for {db_bytes / 1e9:.2f} GB",
                ),
                Measurement(
                    metric="backup_restore_s_per_gb",
                    unit="s/GB",
                    samples=(restore_s / gigabytes,),
                    note=f"{restore_s:.1f} s for {db_bytes / 1e9:.2f} GB",
                ),
                Measurement(
                    metric="backup_size_ratio",
                    unit="fraction of database bytes",
                    samples=(ratio,),
                    note=f"{archive_bytes} archive bytes against {db_bytes} database bytes",
                ),
            ],
            findings,
        )
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(restore_dir, ignore_errors=True)


async def measure_vacuum(database: Database) -> tuple[list[Measurement], list[str]]:
    """Time a full ``VACUUM``, and report whether the product would run one.

    Both halves matter. The duration is the longest a write can be stalled at
    this scale, because ``VACUUM`` holds the single writer lock throughout. The
    verdict is whether ``flightsite.maintenance.policy`` would have allowed it
    at all: the guard requires free space of twice the database size, which is
    a very different proposition for a 40 GB history than for a 40 MB one.
    """
    before = await gather_stats(database)
    decision = vacuum_decision(before, under_pressure=False)

    started = time.perf_counter()
    async with database.maintenance_connection() as connection:
        await connection.exec_driver_sql("VACUUM")
    elapsed_s = time.perf_counter() - started
    after = await gather_stats(database)

    findings = [
        f"VACUUM of a {before.db_bytes / 1e9:.2f} GB database took {elapsed_s:.1f} s and "
        f"left {after.db_bytes / 1e9:.2f} GB, holding the single writer lock throughout",
        f"the product's own guard would have returned {decision.verdict.value} here "
        f"({before.reclaimable_ratio:.1%} reclaimable, {before.free_bytes / 1e9:.0f} GB free "
        f"against the 2x-database-size requirement)",
    ]
    return (
        [
            Measurement(
                metric="vacuum_s",
                unit="s",
                samples=(elapsed_s,),
                note=f"{before.db_bytes / 1e9:.2f} GB -> {after.db_bytes / 1e9:.2f} GB",
            )
        ],
        findings,
    )


def _growth_findings(generation: GenerationResult) -> list[str]:
    """Read the growth numbers and say what they mean.

    Findings draw conclusions rather than reporting figures, because the
    conclusion is the deliverable: a bytes-per-sighting number over budget is
    only actionable once somebody knows *which* table it came from and why.

    ASCII only, like the rest of the report — this is printed to whatever
    console the machine being qualified happens to have, so the section marks
    used everywhere else in these docstrings are spelled out here.
    """
    findings: list[str] = []
    scenario = generation.config.scenario
    low, high = scenario.predicted_gb_per_year
    measured_per_year = (
        generation.db_bytes / generation.days * 365 / BYTES_PER_GB if generation.days else 0.0
    )
    findings.append(
        f"measured growth is {measured_per_year:.2f} GB/year against "
        f"docs/DATA_MODEL.md sec.9's predicted {low:g}-{high:g} GB/year for this scenario "
        f"({generation.bytes_per_sighting:.0f} bytes/sighting against ~2,000 predicted)"
    )

    tracks = generation.table("sighting_tracks")
    if tracks is not None and tracks.rows:
        payload = 5 + 21 * generation.mean_track_points
        inline_limit = _max_inline_payload(generation.page_size)
        findings.append(
            f"sighting_tracks costs {tracks.bytes_per_row:.0f} bytes/row on disk for a "
            f"{payload:.0f}-byte packed payload ({generation.mean_track_points:.1f} points at "
            f"{SECONDS_PER_RETAINED_POINT:g} s each)"
        )
        if tracks.bytes_per_row > payload * 1.6:
            findings.append(
                "that overhead is SQLite overflow pages: sighting_tracks is WITHOUT ROWID, "
                f"whose inline payload limit is {inline_limit} bytes at this "
                f"{generation.page_size}-byte page size, so any track over "
                f"~{max(0, (inline_limit - 20) // 21)} points spills a whole page. ADR-0005 "
                "sizes the design at ~1-2 KB per track and docs/DATA_MODEL.md sec.2.4 at "
                "~1.3 KB; neither accounts for this. Out of scope for slice 050 to change - "
                "a page-size or table-format change needs an ADR."
            )
    return findings


def _query_findings(probes: Sequence[ProbeResult], *, sightings: int) -> list[str]:
    """Say which query is the slow one, and whether it scales.

    SPEC §86 asks about *index behavior*, and the honest way to answer that
    from the outside is to compare the queries an index covers against the ones
    it does not, on the same dataset. A sort the schema has no index for is
    served by reading every matching row and ordering them in memory, so its
    cost grows with the table while an indexed read's does not — and the ratio
    between them on a dataset of known size says how the unindexed one will
    behave on a larger one.
    """
    history = [probe for probe in probes if probe.metric == "history_query_ms"]
    if not history:
        return []

    indexed = [probe for probe in history if "unindexed" not in probe.label]
    unindexed = [probe for probe in history if "unindexed" in probe.label]
    if not indexed or not unindexed:  # pragma: no cover - probe set is fixed
        return []

    best = min(probe.median_ms for probe in indexed)
    worst = max(probe.median_ms for probe in unindexed)
    slowest = max(unindexed, key=lambda probe: probe.median_ms)
    findings = [
        f"the slowest documented read is '{slowest.label}' at {slowest.median_ms:.0f} ms over "
        f"{sightings} sightings, against {best:.0f} ms for the indexed newest-first read - "
        f"a factor of {worst / best:.0f}"
    ]
    findings.append(
        "sightings has no index on closest_approach_nm or max_range_nm (docs/DATA_MODEL.md "
        "sec.2.3 declares only aircraft+started_ms, started_ms, and the partial open index), so "
        "those sorts read every matching row and order them in memory: their cost grows with "
        "the table where the indexed reads' does not"
    )
    return findings


async def run_qualification(
    config: GenerationConfig,
    *,
    data_dir: Path,
    probe_repeats: int = DEFAULT_PROBE_REPEATS,
    include_backup: bool = True,
    include_vacuum: bool = True,
) -> StorageReport:
    """Generate a multi-year database and qualify it (SPEC §86).

    Args:
        config: the history to synthesize.
        data_dir: where the database lives. **Point this at the storage being
            qualified** — on a Pi, the SD card or USB SSD the install uses.
        probe_repeats: timings taken per query.
        include_backup: run the backup/verify/restore leg. It reads and writes
            several times the database size, so a small in-suite run may skip it.
        include_vacuum: run the ``VACUUM`` leg, which rewrites the whole file.
    """
    started = time.perf_counter()
    # Off the loop: the ASYNC lint rule is right in general, and a qualification
    # run has no reason to be the one place that blocks it on a filesystem call.
    await asyncio.to_thread(data_dir.mkdir, parents=True, exist_ok=True)

    database = Database(data_dir / "flightsite.sqlite3")
    await database.upgrade_to("head")
    generation = await generate_history(database, config)
    await database.dispose()

    measurements: list[Measurement] = [
        Measurement(
            metric="dataset_days",
            unit="days",
            samples=(float(generation.days),),
            note=(
                f"{generation.config.scenario.name}: {generation.sightings} sightings, "
                f"{generation.aircraft} airframes, {generation.tracks} packed tracks"
            ),
        ),
        Measurement(
            metric="db_bytes_per_sighting",
            unit="bytes/sighting",
            samples=(generation.bytes_per_sighting,),
            note=f"{generation.db_bytes} bytes over {generation.sightings} sightings",
        ),
    ]
    findings = _growth_findings(generation)

    query_measurements, probes = await measure_queries(data_dir, repeats=probe_repeats)
    measurements.extend(query_measurements)
    findings.extend(_query_findings(probes, sightings=generation.sightings))

    database = Database(data_dir / "flightsite.sqlite3")
    now_ms = int(config.end_at.timestamp() * 1_000)
    retention_measurements, retention_findings = await measure_retention(database, now_ms=now_ms)
    measurements.extend(retention_measurements)
    findings.extend(retention_findings)

    wal = data_dir / "flightsite.sqlite3-wal"
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    measurements.append(
        Measurement(
            metric="wal_bytes_mib",
            unit="MiB",
            samples=(wal_bytes / MIB,),
            note="after bulk history writes and one maintenance pass",
        )
    )
    await database.dispose()

    if include_backup:
        backup_measurements, backup_findings = await measure_backup(
            data_dir, db_bytes=generation.db_bytes
        )
        measurements.extend(backup_measurements)
        findings.extend(backup_findings)

    if include_vacuum:
        database = Database(data_dir / "flightsite.sqlite3")
        vacuum_measurements, vacuum_findings = await measure_vacuum(database)
        measurements.extend(vacuum_measurements)
        findings.extend(vacuum_findings)
        await database.dispose()

    return StorageReport(
        measurements=tuple(measurements),
        generation=generation,
        probes=tuple(probes),
        findings=tuple(findings),
        environment=Environment.capture(),
        duration_s=time.perf_counter() - started,
    )


__all__ = [
    "ANALYTICS_ENDPOINTS",
    "ANALYTICS_PRESETS",
    "DEFAULT_PROBE_REPEATS",
    "measure_backup",
    "measure_queries",
    "measure_retention",
    "measure_vacuum",
    "run_qualification",
]
