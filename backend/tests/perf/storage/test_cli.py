"""``flightsite-storage-qual``: the standalone entry point.

The command is what ``docs/PERFORMANCE.md``'s storage procedure tells an
operator to run against the storage being qualified, so its contract is part of
the slice: the flags mean what the doc says, the exit status distinguishes a
met hard gate from a missed one, a reference overrun is loud but not fatal, and
``--json`` writes something a later run can be compared against.

The runs here are the smallest the tool allows. The numbers a real
qualification needs come from a multi-year ``--days`` on real storage, and
re-measuring them here would only duplicate
:mod:`tests.perf.storage.test_qualification` at many times the cost.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from flightsite.perf.storage_qualification.cli import DEFAULT_DAYS, build_arg_parser, main
from flightsite.perf.storage_qualification.generator import DEFAULT_SEED
from flightsite.perf.storage_qualification.scenarios import SCENARIO_A

#: The cheapest invocation that still exercises every leg of the CLI.
TINY = ("--days", "2", "--high-res-backlog-days", "1", "--probe-repeats", "1")


def test_the_default_span_is_the_three_years_the_criterion_names() -> None:
    """Roadmap slice 050 asks for a three-year dataset; the bare command builds one."""
    args = build_arg_parser().parse_args(["--data-dir", "x"])
    assert args.days == DEFAULT_DAYS == 1_095
    assert args.scenario == SCENARIO_A.name
    assert args.seed == DEFAULT_SEED
    assert args.skip_backup is False
    assert args.skip_vacuum is False


def test_the_data_directory_is_required() -> None:
    """There is no sensible default: the whole point is to name the storage
    being qualified, and silently choosing one would measure the wrong disk."""
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--days", "10"])


def test_only_the_documented_scenarios_are_accepted() -> None:
    """A typo must fail at the parser, not qualify a receiver nobody described."""
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--data-dir", "x", "--scenario", "subrban"])


def test_a_run_whose_hard_gates_hold_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 0, a printed table, and a JSON report a later run can be diffed against."""
    report_path = tmp_path / "report.json"
    status = main(
        [
            *TINY,
            "--data-dir",
            str(tmp_path / "data"),
            "--json",
            str(report_path),
            "--skip-vacuum",
        ]
    )
    assert status == 0

    printed = capsys.readouterr().out
    assert "FlightSite storage qualification" in printed
    assert "db_bytes_per_sighting" in printed
    assert "findings" in printed

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["scenario"]["days"] == 2
    assert payload["dataset"]["sightings"] > 0
    # A skipped leg is absent from metrics but still present, unmeasured, among
    # the verdicts: a gap in the report rather than a silent pass.
    assert "vacuum_s" not in payload["metrics"]
    assert payload["verdicts"]["vacuum_s"]["measured"] is False


def test_a_reference_overrun_is_reported_loudly_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``docs/PERFORMANCE.md`` §1's hybrid model, at the exit-status level.

    A reference budget is measured, reported and trended; it never fails a run.
    The distinction is the whole reason two kinds of budget exist, and it is
    only real if the exit status honours it.
    """
    status = main([*TINY, "--data-dir", str(tmp_path / "data"), "--skip-backup", "--skip-vacuum"])
    assert status == 0
    captured = capsys.readouterr()
    assert "REFERENCE BUDGETS EXCEEDED" in captured.err
    assert "db_bytes_per_sighting" in captured.err


def test_an_impossible_configuration_is_rejected_before_anything_is_generated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 for a bad invocation, distinct from exit 1 for a missed gate."""
    status = main(["--days", "0", "--data-dir", str(tmp_path / "data")])
    assert status == 2
    assert "invalid configuration" in capsys.readouterr().err
    assert not (tmp_path / "data" / "flightsite.sqlite3").exists()


def test_an_operator_can_still_ask_for_info_logging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI quiets logging by default because the analytics backfill logs per
    rebuilt day, and over three years that is a large fraction of the run — but
    an operator debugging one must still be able to ask for INFO and get it."""
    monkeypatch.setenv("FLIGHTSITE_LOG_LEVEL", "INFO")
    main([*TINY, "--data-dir", str(tmp_path / "data"), "--skip-backup", "--skip-vacuum"])
    assert os.environ["FLIGHTSITE_LOG_LEVEL"] == "INFO"
