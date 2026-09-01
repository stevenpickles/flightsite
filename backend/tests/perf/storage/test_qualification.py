"""The qualification end to end, in-suite and at multi-year scale.

Two runs, the same split slice 049 uses:

* an **in-suite** qualification over a fortnight of small traffic, which runs on
  every ordinary test run and asserts every hard gate. The gates here are
  structural rather than statistical — a retention pass that stopped pruning, a
  downsample that lost an hour, or a probe that started returning 500s fails on
  a fortnight exactly as it would on three years.
* a **multi-year** qualification behind the ``load`` marker, which is the one
  the acceptance criterion names and the one whose numbers reach
  ``docs/PERFORMANCE.md``. It is minutes of wall clock and gigabytes of disk,
  so it is excluded from the default suite:

      uv run pytest -m load --no-cov

The load run is the same code path as ``flightsite-storage-qual``; the command
exists so it can be pointed at a Pi's real storage, and this exists so CI can
run it on demand without one.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from flightsite.perf.budgets import GateKind
from flightsite.perf.storage_qualification.budgets import STORAGE_BUDGETS
from flightsite.perf.storage_qualification.generator import GenerationConfig
from flightsite.perf.storage_qualification.qualify import run_qualification
from flightsite.perf.storage_qualification.report import StorageReport
from flightsite.perf.storage_qualification.scenarios import SCENARIO_A
from tests.perf.storage.conftest import SMOKE_END, SMOKE_SCENARIO

#: A fortnight: the shortest span that still crosses the 14-day retention
#: window and therefore still has a prune and a downsample to perform.
SMOKE_DAYS = 14

#: One timing per query in-suite. The in-suite gates are structural, and three
#: repeats of forty queries would be most of this module's run time for a
#: statistic nothing here asserts on.
SMOKE_REPEATS = 1

HARD_METRICS = [budget.metric for budget in STORAGE_BUDGETS if budget.gate is GateKind.HARD]


@pytest.fixture(scope="module")
def qualification(tmp_path_factory: pytest.TempPathFactory) -> StorageReport:
    """One complete in-suite qualification, shared by the module.

    Backup and vacuum are included deliberately even though they are the
    expensive legs: on a dataset this small they cost under a second each, and
    they are two of SPEC §86's nine items. Skipping them in-suite would mean
    the first time anybody ran them at all was on a three-year database.
    """
    data_dir: Path = tmp_path_factory.mktemp("storage-qualification")
    return asyncio.run(
        run_qualification(
            GenerationConfig(
                scenario=SMOKE_SCENARIO,
                days=SMOKE_DAYS,
                end=SMOKE_END,
                high_res_backlog_days=2,
            ),
            data_dir=data_dir,
            probe_repeats=SMOKE_REPEATS,
        )
    )


def test_the_qualification_reports(
    qualification: StorageReport, capsys: pytest.CaptureFixture[str]
) -> None:
    """Print the table: on a qualification run this output *is* the artifact."""
    with capsys.disabled():
        print("\n" + qualification.format_table())
    assert qualification.measurement("dataset_days") is not None


def test_every_budget_in_the_table_was_measured(qualification: StorageReport) -> None:
    """A budget nothing measures is a budget nothing enforces."""
    unmeasured = {
        verdict.budget.metric for verdict in qualification.verdicts() if not verdict.measured
    }
    assert not unmeasured, f"unmeasured storage budgets: {unmeasured}"


@pytest.mark.parametrize("metric", HARD_METRICS)
def test_each_hard_gate_holds(qualification: StorageReport, metric: str) -> None:
    """SPEC §86's correctness-critical claims, one assertion each."""
    verdict = next(item for item in qualification.verdicts() if item.budget.metric == metric)
    observed = verdict.observed
    assert observed is not None
    assert verdict.passed, (
        f"{metric}: {verdict.budget.statistic.value} was {observed:.4g} "
        f"{verdict.budget.unit} against a bound of {verdict.budget.asserted:.4g}"
    )


def test_a_reference_budget_never_fails_the_run(qualification: StorageReport) -> None:
    """The trend half of the hybrid model.

    Asserted structurally rather than by hoping no reference budget is crossed:
    on this dataset ``db_bytes_per_sighting`` *is* crossed, deliberately and
    reproducibly, and it still must not fail anything.
    """
    for verdict in qualification.verdicts():
        if not verdict.budget.hard:
            assert verdict not in qualification.failures()
    assert qualification.passed


def test_the_overflow_page_finding_reaches_the_report(
    qualification: StorageReport,
) -> None:
    """The finding this slice exists to surface must be stated, not just scored.

    Packed tracks over ~46 points spill a whole overflow page at the default
    4 KiB page size, so ``sighting_tracks`` costs about twice what ADR-0005 and
    ``docs/DATA_MODEL.md`` §2.4 size it at. A qualification that measured that
    and printed only a number would leave the reader to rediscover the cause.

    Note what is *not* asserted here: that ``db_bytes_per_sighting`` overruns
    for this reason on this dataset. At smoke scale it overruns mostly because
    the 14-day high-resolution telemetry window is a fixed cost spread over a
    fortnight of deliberately tiny traffic. The per-sighting budget is only
    meaningful at scenario scale, which is what the ``load`` run measures; the
    overflow finding is derived from the per-row cost and is honest at both.
    """
    tracks = qualification.generation.table("sighting_tracks")
    assert tracks is not None and tracks.rows > 0
    payload = 5 + 21 * qualification.generation.mean_track_points
    assert tracks.bytes_per_row > payload * 1.6, (
        "packed tracks did not overflow, so the finding below would be absent; "
        "if this ever fails on purpose, the page size or table format changed"
    )
    assert any("overflow page" in finding for finding in qualification.findings)


def test_the_report_names_the_slowest_query(qualification: StorageReport) -> None:
    """ "Index behavior" is only actionable if the report says which query."""
    slowest = qualification.slowest_probes(limit=3)
    assert slowest
    assert all(probe.median_ms > 0 for probe in slowest)
    assert any("unindexed" in finding for finding in qualification.findings)


def test_the_formatted_table_is_ascii_only(qualification: StorageReport) -> None:
    """It is printed to whatever console a machine being qualified has.

    A Pi over a serial console, or a Windows terminal on a legacy code page,
    should get a readable report rather than mojibake — which is exactly what a
    section mark in a finding produced before this test existed.
    """
    table = qualification.format_table()
    assert table.isascii(), "the report must survive a serial console"
    for budget in STORAGE_BUDGETS:
        assert budget.metric in table


def test_the_json_form_round_trips_every_metric(qualification: StorageReport) -> None:
    """Trend tracking across runs reads this, not the printed table."""
    payload = qualification.to_dict()
    assert payload["passed"] is qualification.passed
    assert payload["scenario"]["days"] == SMOKE_DAYS
    assert payload["dataset"]["page_size"] > 0
    for measurement in qualification.measurements:
        assert payload["metrics"][measurement.metric]["count"] == measurement.count
    for budget in STORAGE_BUDGETS:
        assert payload["verdicts"][budget.metric]["bound"] == budget.asserted
    assert payload["findings"]
    assert payload["probes"]


def test_the_backup_leg_can_be_skipped_without_being_reported_as_passing(
    tmp_path: Path,
) -> None:
    """A skipped leg is a gap in the report, not a silent success.

    ``--skip-backup`` and ``--skip-vacuum`` exist for machines that cannot
    spare the space, and it matters that the resulting report distinguishes
    "not measured" from "measured and fine" — the same distinction slice 049's
    ``Verdict.measured`` carries.
    """
    report = asyncio.run(
        run_qualification(
            GenerationConfig(
                scenario=SMOKE_SCENARIO,
                days=2,
                end=SMOKE_END,
                high_res_backlog_days=1,
            ),
            data_dir=tmp_path / "skipped",
            probe_repeats=1,
            include_backup=False,
            include_vacuum=False,
        )
    )
    for metric in ("backup_create_s_per_gb", "backup_size_ratio", "vacuum_s"):
        verdict = next(item for item in report.verdicts() if item.budget.metric == metric)
        assert not verdict.measured
        assert verdict.passed, "an unmeasured budget is a gap, and must not fail the run"
    assert "not measured" in report.format_table()


# --------------------------------------------------------------- the load run

#: Span the ``load`` run builds, in days. A year of Scenario A is ~1.8 GB, and
#: the qualification needs room for the database, the backup's snapshot, the
#: archive and a full ``VACUUM`` beside it — roughly four times the database —
#: which fits a shared CI runner's disk where three years does not.
#:
#: Three years is what roadmap slice 050's acceptance criterion names, and it
#: *is* run: by ``flightsite-storage-qual`` on a machine with the disk for it,
#: with the results recorded in ``docs/PERFORMANCE.md`` §7.6. This is the same
#: split slice 049 uses — its in-suite sustained run is shorter than the
#: standalone run whose numbers the document carries. Override for a longer
#: run wherever there is room:
#:
#:     FLIGHTSITE_STORAGE_QUAL_DAYS=1095 uv run pytest -m load --no-cov
#: Empty is treated as unset, not as an error: a ``workflow_dispatch`` input
#: nobody filled in arrives as the empty string rather than as an absent
#: variable, and a qualification job that died on ``int("")`` would be a
#: confusing way to learn that.
LOAD_DAYS = int(os.environ.get("FLIGHTSITE_STORAGE_QUAL_DAYS") or "365")


@pytest.mark.load
def test_a_multi_year_dataset_meets_every_hard_gate(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Scenario A at multi-year scale, judged against the whole storage table.

    What this adds over the in-suite run is scale itself. The hard gates are
    structural and hold on a fortnight, but the *reference* figures — growth
    per sighting, query latency, retention cost, backup and restore throughput
    — only mean anything once the database is large enough for index depth,
    overflow pages and full-table sorts to behave as they will in service.

    Gigabytes are generated, so the data directory is removed afterwards
    whatever happens: a load run that left one behind on a developer machine
    would be a bug in the test rather than a finding about the product.
    """
    data_dir: Path = tmp_path_factory.mktemp("storage-load")
    try:
        report = asyncio.run(
            run_qualification(
                GenerationConfig(scenario=SCENARIO_A, days=LOAD_DAYS),
                data_dir=data_dir,
            )
        )
        print("\n" + report.format_table())

        failures = [
            f"{verdict.budget.metric}: {verdict.observed:.4g} {verdict.budget.unit} "
            f"against {verdict.budget.asserted:.4g}"
            for verdict in report.failures()
        ]
        assert not failures, "; ".join(failures)
        assert report.generation.days == LOAD_DAYS
        assert report.generation.sightings > SCENARIO_A.sightings_per_day * LOAD_DAYS * 0.9
        # At this scale the growth figure is dominated by the sightings and
        # their tracks rather than by the fixed telemetry window, so it is
        # meaningful here in a way it is not on the in-suite fortnight.
        assert report.generation.bytes_per_sighting > 0
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
