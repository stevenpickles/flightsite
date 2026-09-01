"""The generator's own contract: determinism, coverage, and honest accounting.

:mod:`.test_fidelity` asks whether the rows look like the product's. These ask
whether the *tool* behaves like a tool: the same seed gives the same history,
the byte accounting adds up to the file it claims to describe, and the traffic
it produced is the traffic that was asked for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from flightsite.db import Database
from flightsite.perf.storage_qualification.generator import (
    GenerationConfig,
    GenerationResult,
    generate_history,
)
from flightsite.perf.storage_qualification.scenarios import SCENARIO_A
from tests.perf.storage.conftest import SMOKE_DAYS, SMOKE_END, SMOKE_SCENARIO, Dataset


async def build(path: Path, *, seed: int = 20_500, days: int = 4) -> GenerationResult:
    """A very small history, for tests that need their own database."""
    database = Database(path)
    await database.upgrade_to("head")
    try:
        return await generate_history(
            database,
            GenerationConfig(
                scenario=SMOKE_SCENARIO,
                days=days,
                seed=seed,
                end=SMOKE_END,
                high_res_backlog_days=1,
                build_rollups=False,
            ),
        )
    finally:
        await database.dispose()


async def test_the_same_seed_generates_the_same_history(tmp_path: Path) -> None:
    """Determinism is what makes two growth figures comparable.

    Without it, a change in a measured number could always be the dice, and the
    qualification could never attribute a regression to the product.
    """
    first = await build(tmp_path / "a.sqlite3")
    second = await build(tmp_path / "b.sqlite3")

    assert first.sightings == second.sightings
    assert first.aircraft == second.aircraft
    assert first.track_points == second.track_points
    assert first.db_bytes == second.db_bytes


async def test_a_different_seed_generates_different_history(tmp_path: Path) -> None:
    """The seed has to actually reach the traffic, or determinism is vacuous."""
    first = await build(tmp_path / "a.sqlite3", seed=1)
    second = await build(tmp_path / "b.sqlite3", seed=2)
    assert first.track_points != second.track_points


async def test_the_run_generates_the_traffic_the_scenario_asks_for(
    dataset: Dataset,
) -> None:
    """Sightings land within a few percent of scenario x days.

    Not exact: the weekday factor moves traffic between days, so only the total
    is pinned, and only to the tolerance that factor introduces.
    """
    result = dataset.result
    expected = SMOKE_SCENARIO.sightings_per_day * SMOKE_DAYS
    assert result.days == SMOKE_DAYS
    assert result.sightings == pytest.approx(expected, rel=0.05)


async def test_the_airframe_population_grows_at_the_documented_rate(
    dataset: Dataset,
) -> None:
    """New airframes per year is what sizes the ``aircraft`` table."""
    result = dataset.result
    per_day = SMOKE_SCENARIO.new_aircraft_per_day
    # The first day mints a whole day's unique population; every day after adds
    # roughly `per_day` first-ever contacts.
    lower = SMOKE_SCENARIO.unique_aircraft_per_day
    upper = SMOKE_SCENARIO.unique_aircraft_per_day + per_day * SMOKE_DAYS + 5
    assert lower <= result.aircraft <= upper


async def test_the_byte_accounting_adds_up_to_the_file(dataset: Dataset) -> None:
    """Per-table attribution must account for very nearly the whole database.

    It cannot be exact — the schema itself, the Alembic version table and
    SQLite's own header and freelist pages belong to no measured phase — but a
    large unexplained remainder would mean the attribution is missing a table,
    and every per-row figure derived from it would be understated.
    """
    result = dataset.result
    attributed = sum(entry.bytes for entry in result.growth)
    assert attributed <= result.db_bytes
    assert attributed >= result.db_bytes * 0.9, (
        f"only {attributed} of {result.db_bytes} bytes were attributed to a table"
    )


async def test_every_table_the_growth_model_names_was_written(dataset: Dataset) -> None:
    """``docs/DATA_MODEL.md`` §9 sizes these; a missing one understates growth."""
    written = {entry.table for entry in dataset.result.growth}
    for table in (
        "aircraft",
        "sightings",
        "sighting_tracks",
        "sighting_events",
        "activity_events",
        "alert_matches",
        "receiver_metrics_raw",
        "receiver_metrics_hourly",
        "range_by_bearing_daily",
    ):
        assert table in written, f"{table} is in §9's growth arithmetic but was never written"


async def test_tracks_are_fewer_than_sightings(dataset: Dataset) -> None:
    """Mode S-only sightings carry no packed track (ADR-0005)."""
    result = dataset.result
    assert 0 < result.tracks < result.sightings


async def test_the_packed_payload_matches_the_row_count(
    dataset: Dataset, database: Database
) -> None:
    """``track_points`` is the sum of ``point_count``, and the blobs prove it.

    This is the identity the growth model turns into bytes, so it is checked
    against the database rather than against the generator's own counter.
    """
    async with database.read_session() as session:
        points, blob_bytes, rows = (
            await session.execute(
                text(
                    "SELECT sum(point_count), sum(length(points_blob)), count(*) "
                    "FROM sighting_tracks"
                )
            )
        ).one()

    assert int(points) == dataset.result.track_points
    assert int(rows) == dataset.result.tracks
    # ADR-0005's v1 layout, in aggregate: a 5-byte header per row plus 21 a point.
    assert int(blob_bytes) == 5 * int(rows) + 21 * int(points)


async def test_high_resolution_telemetry_is_seeded_beyond_the_window(
    dataset: Dataset, database: Database
) -> None:
    """There has to be a backlog, or the retention measurement measures a no-op.

    The generator seeds the retention window *plus* ``high_res_backlog_days``,
    representing an install whose maintenance pass has fallen behind. Without
    it, ``run_maintenance`` would prune nothing and the qualification would
    report a passing retention gate having exercised no retention.
    """
    async with database.read_session() as session:
        span_ms = int(
            (
                await session.execute(
                    text("SELECT max(ts_ms) - min(ts_ms) FROM receiver_metrics_raw")
                )
            ).scalar_one()
        )
    assert span_ms / 86_400_000 > 14.0, "no raw telemetry older than the 14-day window"


async def test_summaries_stop_where_the_backlog_begins(
    dataset: Dataset, database: Database
) -> None:
    """The catch-up state: recent hours are downsampled, the backlog is not.

    This is what gives ``run_maintenance`` real work — hours to summarize and
    rows to prune — rather than a database already in its steady state.
    """
    newest_raw_sql = "SELECT max(ts_ms) FROM receiver_metrics_raw"
    async with database.read_session() as session:
        newest_raw = int((await session.execute(text(newest_raw_sql))).scalar_one())
        newest_hour = (
            await session.execute(text("SELECT max(hour_start_ms) FROM receiver_metrics_hourly"))
        ).scalar_one()

    assert newest_hour is not None
    assert int(newest_hour) < newest_raw, "summaries already cover every raw sample"


def test_a_configuration_that_asks_for_nothing_is_rejected() -> None:
    """Zero days is not a small qualification, it is a mistake."""
    with pytest.raises(ValueError, match="days must be at least 1"):
        GenerationConfig(scenario=SCENARIO_A, days=0)
    with pytest.raises(ValueError, match="batch_rows"):
        GenerationConfig(scenario=SCENARIO_A, days=1, batch_rows=0)
    with pytest.raises(ValueError, match="high_res_backlog_days"):
        GenerationConfig(scenario=SCENARIO_A, days=1, high_res_backlog_days=-1)


def test_history_ends_when_it_is_told_to() -> None:
    """The analytics presets resolve against now, so the span has to reach it."""
    config = GenerationConfig(scenario=SCENARIO_A, days=30, end=SMOKE_END)
    assert config.end_at == SMOKE_END

    live = GenerationConfig(scenario=SCENARIO_A, days=30)
    assert live.end_at.tzinfo is UTC
    assert (datetime.now(UTC) - live.end_at).total_seconds() < 60


async def test_generation_reports_what_it_cost(dataset: Dataset) -> None:
    """The report is the artifact; empty timings would make it useless."""
    result = dataset.result
    assert result.duration_s > 0.0
    assert result.page_size > 0
    assert result.bytes_per_sighting > 0.0
    assert result.mean_track_points > 0.0
    assert result.rollup_days == SMOKE_DAYS
