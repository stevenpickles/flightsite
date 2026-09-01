"""``flightsite-storage-qual`` — qualify multi-year storage on this machine.

The standalone entry point, and the one ``docs/PERFORMANCE.md``'s Raspberry Pi
storage procedure invokes. In the container, on the Pi::

    docker compose exec flightsite-backend \\
        uv run flightsite-storage-qual --scenario suburban --days 1095 \\
                                       --data-dir /opt/flightsite/qual \\
                                       --json /opt/flightsite/qual/report.json

``--data-dir`` should point at the storage being qualified. On a Pi that is the
SD card or the USB SSD the install actually uses; measuring a multi-gigabyte
database against a tmpfs would answer a question nobody asked, and would answer
it wrongly, because SD-card I/O is a large part of what is under test.

Be aware of what this costs before running it. A three-year Scenario A dataset
is several gigabytes written once, read several times over by the query probes,
and then read three more times by the backup leg — plus a full ``VACUUM``. The
``--skip-backup`` and ``--skip-vacuum`` flags exist for machines that cannot
spare the space or the time, and the report marks whatever was skipped as *not
measured* rather than quietly passing it.

Exit status is 0 when every measured hard gate held and 1 when one did not, so
the command drops straight into a release check. Reference budgets that were
exceeded are reported prominently but do not change the exit status — that is
what makes them reference budgets (``docs/PERFORMANCE.md`` §1).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from flightsite.logging import configure_logging
from flightsite.perf.storage_qualification.generator import (
    DEFAULT_HIGH_RES_BACKLOG_DAYS,
    DEFAULT_SEED,
    GenerationConfig,
)
from flightsite.perf.storage_qualification.qualify import (
    DEFAULT_PROBE_REPEATS,
    run_qualification,
)
from flightsite.perf.storage_qualification.report import StorageReport
from flightsite.perf.storage_qualification.scenarios import SCENARIOS, scenario_for

#: Three years, the span roadmap slice 050's acceptance criterion names.
DEFAULT_DAYS: int = 1_095


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightsite-storage-qual",
        description=(
            "Generate a realistic synthetic multi-year history and qualify database "
            "growth, query responsiveness, retention, backup and restore against "
            "docs/PERFORMANCE.md (SPEC §86)."
        ),
    )
    parser.add_argument(
        "--scenario",
        choices=[scenario.name for scenario in SCENARIOS],
        default=SCENARIOS[0].name,
        help="which docs/DATA_MODEL.md §9 receiver to model (default: %(default)s)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="days of history to synthesize (default: %(default)s, three years)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="where the database is built; point this at the storage being qualified",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="traffic seed; the same seed is the same history (default: %(default)s)",
    )
    parser.add_argument(
        "--timezone",
        default="UTC",
        help="IANA zone the analytics rollups bucket local days by (default: %(default)s)",
    )
    parser.add_argument(
        "--high-res-backlog-days",
        type=int,
        default=DEFAULT_HIGH_RES_BACKLOG_DAYS,
        help=(
            "high-resolution telemetry seeded beyond the retention window, so the "
            "prune has something to clear (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--probe-repeats",
        type=int,
        default=DEFAULT_PROBE_REPEATS,
        help="timings taken per query (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="do not run the backup/verify/restore leg",
    )
    parser.add_argument(
        "--skip-vacuum",
        action="store_true",
        help="do not run the full VACUUM leg",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="also write the full report as JSON to this path",
    )
    return parser


async def _run(args: argparse.Namespace) -> StorageReport:
    config = GenerationConfig(
        scenario=scenario_for(args.scenario),
        days=args.days,
        seed=args.seed,
        end=datetime.now(UTC),
        high_res_backlog_days=args.high_res_backlog_days,
        timezone=args.timezone,
    )
    return await run_qualification(
        config,
        data_dir=args.data_dir,
        probe_repeats=args.probe_repeats,
        include_backup=not args.skip_backup,
        include_vacuum=not args.skip_vacuum,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # Generating years of history at INFO would put a large fraction of the run
    # into the logger, and the analytics backfill logs per rebuilt day. Set
    # through the environment rather than by calling configure_logging here,
    # because create_app configures logging itself from settings during startup
    # and would otherwise put INFO back. setdefault, so an operator debugging a
    # run can still ask for INFO.
    os.environ.setdefault("FLIGHTSITE_LOG_LEVEL", "WARNING")
    configure_logging()

    try:
        report = asyncio.run(_run(args))
    except ValueError as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        return 2

    print(report.format_table())
    if args.json is not None:
        args.json.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    overruns = report.overruns()
    if overruns:
        print("\nREFERENCE BUDGETS EXCEEDED (reported, not fatal):", file=sys.stderr)
        for verdict in overruns:
            observed = verdict.observed
            assert observed is not None
            print(
                f"  {verdict.budget.metric}: {observed:.4g} {verdict.budget.unit} "
                f"against a bound of {verdict.budget.asserted:.4g}",
                file=sys.stderr,
            )

    if not report.passed:
        print("\nHARD GATE FAILURES:", file=sys.stderr)
        for verdict in report.failures():
            observed = verdict.observed
            assert observed is not None
            print(
                f"  {verdict.budget.metric}: {observed:.4g} {verdict.budget.unit} "
                f"against a bound of {verdict.budget.asserted:.4g}",
                file=sys.stderr,
            )
        return 1
    return 0


__all__ = ["DEFAULT_DAYS", "build_arg_parser", "main"]
