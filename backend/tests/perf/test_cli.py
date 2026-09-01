"""``flightsite-perf``: the standalone entry point the Pi 4 procedure invokes.

The command is what ``docs/PERFORMANCE.md`` tells an operator to run on the
hardware being qualified, so its contract is part of the slice: the flags mean
what the doc says they mean, the exit status distinguishes a met budget from a
missed one, and ``--json`` writes something a later run can be compared against.

The run itself is kept as small as the harness allows — the numbers a real
qualification needs come from ``--realtime`` on real hardware, and re-measuring
them here would only duplicate :mod:`tests.perf.test_harness` at several times
the cost.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from flightsite.perf.budgets import TARGET_AIRCRAFT
from flightsite.perf.cli import build_arg_parser, main
from flightsite.perf.workload import DEFAULT_WS_CLIENTS

#: The cheapest run that still exercises every code path in the CLI.
TINY = ("--ticks", "3", "--warmup-ticks", "1", "--ws-clients", "1", "--skip-recovery")


def test_the_defaults_are_the_documented_envelope() -> None:
    """The bare command runs the product's stated load, not a toy one."""
    args = build_arg_parser().parse_args([])
    assert args.population == TARGET_AIRCRAFT
    assert args.ws_clients == DEFAULT_WS_CLIENTS
    assert args.realtime is False
    assert args.data_dir is None


def test_realtime_is_opt_in() -> None:
    """Pacing to the wall clock is what makes a standalone run sustained, and
    it is also what makes it slow; CI must not get it by accident."""
    assert build_arg_parser().parse_args(["--realtime"]).realtime is True


def test_a_run_that_meets_its_budgets_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "report.json"
    status = main(
        [
            *TINY,
            "--data-dir",
            str(tmp_path / "data"),
            "--json",
            str(report_path),
        ]
    )
    assert status == 0

    printed = capsys.readouterr().out
    assert "FlightSite performance harness" in printed
    assert "ingest_duty_cycle" in printed

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["config"]["population"] == TARGET_AIRCRAFT
    assert payload["metrics"]["ingest_apply_ms"]["count"] == 3
    # Skipped scenarios are absent from metrics but still present, unmeasured,
    # among the verdicts: a gap in the report rather than a silent pass.
    assert "recovery_s" not in payload["metrics"]
    assert payload["verdicts"]["recovery_s"]["measured"] is False


def test_an_impossible_configuration_is_rejected_before_any_load_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 for a bad invocation, distinct from exit 1 for a missed budget."""
    status = main(["--ticks", "0", "--data-dir", str(tmp_path / "data")])
    assert status == 2
    assert "invalid configuration" in capsys.readouterr().err


def test_the_harness_leaves_the_log_level_an_operator_chose_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI quiets logging by default because at 500 aircraft the logger is
    a measurable part of a run — but an operator debugging one must still be
    able to ask for INFO and get it."""
    monkeypatch.setenv("FLIGHTSITE_LOG_LEVEL", "INFO")
    main([*TINY, "--skip-startup", "--data-dir", str(tmp_path / "data")])
    assert os.environ["FLIGHTSITE_LOG_LEVEL"] == "INFO"
