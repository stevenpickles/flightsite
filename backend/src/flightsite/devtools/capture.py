"""``flightsite-capture`` — record a live decoder into a fixture.

Polls a real readsb / dump1090-fa endpoint through the same
:class:`~flightsite.ingest.readsb.ReadsbJsonAdapter` production code uses, for
a bounded wall-clock duration, and writes every normalized batch it saw to a
``.fsrec.gz`` fixture (:mod:`flightsite.devtools.fixture`) that
:class:`~flightsite.devtools.replay.ReplayAdapter` can play back later.

Usage::

    uv run flightsite-capture --host 192.168.1.50 --port 8080 \\
        --path /data/aircraft.json --duration 60 --out session.fsrec.gz

Capturing from demo mode is out of scope for this slice (roadmap 012): demo
mode (slice 011) is itself a deterministic, seed-reproducible source, so it
gets no benefit from being recorded and replayed — this tool exists to turn
an unrepeatable live decoder session into a repeatable one.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flightsite.devtools.fixture import FixtureHeader, write_fixture
from flightsite.ingest.protocol import DecoderAdapter
from flightsite.ingest.readsb import ReadsbJsonAdapter
from flightsite.ingest.types import AircraftStateBatch, DecoderEndpoint

#: Generator tag recorded in every fixture this tool writes.
GENERATOR: str = "flightsite-capture"


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    """What a capture run produced, for the CLI's printed summary."""

    header: FixtureHeader
    aircraft_seen: int
    out_path: Path
    bytes_written: int


async def run_capture(
    adapter: DecoderAdapter,
    *,
    duration_s: float,
    out_path: str | Path,
    source: str,
    monotonic: Callable[[], float] | None = None,
    now: Callable[[], datetime] | None = None,
) -> CaptureSummary:
    """Poll ``adapter`` for ``duration_s`` seconds and write a fixture.

    ``adapter`` is started and stopped here, so callers hand in a fresh,
    unstarted one. Bounded by wall-clock time via ``monotonic``/``asyncio``
    timeout rather than a batch count, so it works regardless of the
    adapter's own polling cadence — including one slower than the requested
    duration, which simply yields zero batches rather than hanging.
    """
    monotonic = monotonic if monotonic is not None else asyncio.get_running_loop().time
    now = now if now is not None else _utc_now
    out_path = Path(out_path)

    started_at = now()
    start = monotonic()
    batches: list[AircraftStateBatch] = []
    await adapter.start()
    try:
        try:
            async with asyncio.timeout(duration_s):
                async for batch in adapter.updates():
                    batches.append(batch)
        except TimeoutError:
            pass
    finally:
        await adapter.stop()
    elapsed_s = monotonic() - start

    header = write_fixture(
        out_path,
        batches=batches,
        source=source,
        duration_s=elapsed_s,
        created_at=started_at,
        generator=GENERATOR,
    )
    aircraft_seen = {update.icao for batch in batches for update in batch}
    return CaptureSummary(
        header=header,
        aircraft_seen=len(aircraft_seen),
        out_path=out_path,
        bytes_written=out_path.stat().st_size,
    )


def format_summary(summary: CaptureSummary) -> str:
    """Render a capture summary for the CLI's stdout."""
    header = summary.header
    return (
        f"Captured {header.batch_count} batches "
        f"({header.update_count} updates, {summary.aircraft_seen} aircraft seen) "
        f"over {header.duration_s:.1f}s from {header.source!r}\n"
        f"Wrote {summary.out_path} ({summary.bytes_written} bytes)"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightsite-capture",
        description="Capture a bounded-duration decoder session into a replayable fixture.",
    )
    parser.add_argument("--host", required=True, help="decoder host or IP")
    parser.add_argument("--port", required=True, type=int, help="decoder port")
    parser.add_argument(
        "--path",
        default="/data/aircraft.json",
        help="decoder aircraft-document path (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="seconds between polls (default: %(default)s)",
    )
    parser.add_argument(
        "--duration",
        required=True,
        type=float,
        help="how many seconds to capture",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="output fixture path (conventionally ending in .fsrec.gz)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.duration <= 0:
        print("--duration must be positive", file=sys.stderr)
        return 2

    endpoint = DecoderEndpoint(
        host=args.host, port=args.port, path=args.path, poll_interval_s=args.poll_interval
    )
    adapter = ReadsbJsonAdapter(endpoint)
    summary = asyncio.run(
        run_capture(
            adapter,
            duration_s=args.duration,
            out_path=args.out,
            source=f"readsb@{endpoint.url}",
        )
    )
    print(format_summary(summary))
    return 0


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "GENERATOR",
    "CaptureSummary",
    "build_arg_parser",
    "format_summary",
    "main",
    "run_capture",
]
