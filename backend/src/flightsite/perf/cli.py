"""``flightsite-perf`` — run the load harness against this machine.

The standalone entry point, and the one the Raspberry Pi 4 qualification
procedure in ``docs/PERFORMANCE.md`` invokes. In the container, on the Pi::

    docker compose exec flightsite-backend \\
        uv run flightsite-perf --realtime --ticks 600 --data-dir /tmp/perf

``--realtime`` is what makes a standalone run mean what it says: ticks are paced
against the wall clock at the product's 1 Hz cadence, so 600 ticks is ten
minutes of genuinely sustained 500-aircraft load rather than a burst run as fast
as the CPU allows. Without it the harness still measures what each stage costs,
which is the useful question in CI and a useless one on hardware being
qualified.

``--data-dir`` should point at the storage being qualified. On a Pi that is the
SD card or the USB SSD the install actually uses; measuring against a tmpfs
would answer a question nobody asked.

Exit status is 0 when every measured hard gate held and 1 when one did not, so
the command drops straight into a release check. ``--json`` writes the full
report for trend tracking across runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from flightsite.logging import configure_logging
from flightsite.perf.budgets import TARGET_AIRCRAFT
from flightsite.perf.harness import DEFAULT_PROBE_EVERY, HarnessReport, run_harness
from flightsite.perf.workload import DEFAULT_WS_CLIENTS, WorkloadConfig


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightsite-perf",
        description=(
            "Run the FlightSite performance harness: sustained demo-driven load "
            "at the SPEC §5 envelope, judged against docs/PERFORMANCE.md."
        ),
    )
    parser.add_argument(
        "--population",
        type=int,
        default=TARGET_AIRCRAFT,
        help="target concurrent aircraft (default: %(default)s)",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=60,
        help="measured 1 Hz ticks after warm-up (default: %(default)s)",
    )
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=5,
        help="ticks applied but not measured (default: %(default)s)",
    )
    parser.add_argument(
        "--ws-clients",
        type=int,
        default=DEFAULT_WS_CLIENTS,
        help="simulated WebSocket clients (default: %(default)s)",
    )
    parser.add_argument(
        "--probe-every",
        type=int,
        default=DEFAULT_PROBE_EVERY,
        help="ticks between HTTP and memory probes (default: %(default)s)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="pace ticks at the 1 Hz product cadence (use this on real hardware)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="data directory for the harness database; defaults to FLIGHTSITE_DATA_DIR",
    )
    parser.add_argument(
        "--skip-startup",
        action="store_true",
        help="do not measure cold startup",
    )
    parser.add_argument(
        "--skip-recovery",
        action="store_true",
        help="do not measure unclean-shutdown recovery",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="also write the full report as JSON to this path",
    )
    return parser


async def _run(args: argparse.Namespace) -> HarnessReport:
    config = WorkloadConfig(
        population=args.population,
        ticks=args.ticks,
        warmup_ticks=args.warmup_ticks,
        ws_clients=args.ws_clients,
        realtime=args.realtime,
    )
    return await run_harness(
        config,
        data_dir=args.data_dir,
        probe_every=args.probe_every,
        include_startup=not args.skip_startup,
        include_recovery=not args.skip_recovery,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # The pipeline logs an event per subsystem per tick at INFO; at 500
    # aircraft that is a large fraction of a run's cost, and the harness would
    # be measuring the logger. Set through the environment rather than by
    # calling configure_logging here, because create_app configures logging
    # itself from settings during startup and would otherwise put INFO back.
    # setdefault, so an operator debugging a run can still ask for INFO.
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

    if not report.passed:
        print("\nHARD GATE FAILURES:", file=sys.stderr)
        for verdict in report.failures():
            observed = verdict.observed
            print(
                f"  {verdict.budget.metric}: {observed:.3g} {verdict.budget.unit} "
                f"against a bound of {verdict.budget.asserted:.3g}",
                file=sys.stderr,
            )
        return 1
    return 0


__all__ = ["build_arg_parser", "main"]
