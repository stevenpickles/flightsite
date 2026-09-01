"""``flightsite-capture``: the bounded-duration capture loop and its CLI."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flightsite.devtools.capture import (
    GENERATOR,
    CaptureSummary,
    build_arg_parser,
    format_summary,
    main,
    run_capture,
)
from flightsite.devtools.fixture import read_fixture, write_fixture
from flightsite.ingest.health import AdapterHealth
from flightsite.ingest.types import AircraftStateBatch

from .conftest import T0, make_batches


class ScriptedAdapter:
    """A ``DecoderAdapter`` stand-in that yields a fixed batch list then ends."""

    def __init__(self, batches: list[AircraftStateBatch]) -> None:
        self._batches = batches
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def updates(self) -> AsyncIterator[AircraftStateBatch]:
        for batch in self._batches:
            yield batch

    def health(self) -> AdapterHealth:
        return AdapterHealth()


class HangingAdapter:
    """A ``DecoderAdapter`` stand-in that never yields (an unreachable decoder)."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def updates(self) -> AsyncIterator[AircraftStateBatch]:
        await asyncio.Event().wait()
        yield AircraftStateBatch(timestamp=T0)  # pragma: no cover - never reached

    def health(self) -> AdapterHealth:
        return AdapterHealth()


# ------------------------------------------------------------- run_capture


async def test_run_capture_writes_a_fixture_from_the_adapters_batches(tmp_path: Path) -> None:
    batches = make_batches(3)
    adapter = ScriptedAdapter(batches)
    out = tmp_path / "session.fsrec.gz"

    summary = await run_capture(adapter, duration_s=5.0, out_path=out, source="test-source")

    assert adapter.started and adapter.stopped
    assert summary.header.batch_count == 3
    assert summary.header.update_count == 6
    assert summary.header.source == "test-source"
    assert summary.header.generator == GENERATOR
    assert summary.aircraft_seen == 2
    assert summary.out_path == out
    assert summary.bytes_written == out.stat().st_size

    fixture = read_fixture(out)
    assert [record.batch for record in fixture.records] == batches


async def test_run_capture_stops_the_adapter_even_on_early_exhaustion(tmp_path: Path) -> None:
    adapter = ScriptedAdapter([])
    out = tmp_path / "session.fsrec.gz"

    summary = await run_capture(adapter, duration_s=5.0, out_path=out, source="test")

    assert adapter.stopped
    assert summary.header.batch_count == 0
    assert summary.aircraft_seen == 0


async def test_run_capture_bounds_duration_against_an_adapter_that_never_yields(
    tmp_path: Path,
) -> None:
    adapter = HangingAdapter()
    out = tmp_path / "session.fsrec.gz"

    summary = await run_capture(adapter, duration_s=0.02, out_path=out, source="test")

    assert adapter.stopped
    assert summary.header.batch_count == 0
    assert out.exists()


async def test_run_capture_uses_the_injected_clocks(tmp_path: Path) -> None:
    fixed_now = datetime(2030, 1, 1, tzinfo=UTC)
    ticks = iter([0.0, 3.5])
    adapter = ScriptedAdapter(make_batches(1))
    out = tmp_path / "session.fsrec.gz"

    summary = await run_capture(
        adapter,
        duration_s=10.0,
        out_path=out,
        source="test",
        monotonic=lambda: next(ticks),
        now=lambda: fixed_now,
    )

    assert summary.header.created_at == fixed_now
    assert summary.header.duration_s == pytest.approx(3.5)


# -------------------------------------------------------------- summary


def test_format_summary_reports_batches_aircraft_and_bytes(tmp_path: Path) -> None:
    out = tmp_path / "session.fsrec.gz"
    header = write_fixture(
        out, batches=make_batches(2), source="readsb@test", duration_s=1.5, created_at=T0
    )
    summary = CaptureSummary(
        header=header, aircraft_seen=2, out_path=out, bytes_written=out.stat().st_size
    )

    text = format_summary(summary)

    assert "2 batches" in text
    assert "2 aircraft seen" in text
    assert "readsb@test" in text
    assert str(out) in text
    assert f"{out.stat().st_size} bytes" in text


# ----------------------------------------------------------------- CLI


def test_build_arg_parser_requires_host_port_duration_and_out() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_arg_parser_applies_defaults() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        ["--host", "192.168.1.50", "--port", "8080", "--duration", "30", "--out", "x.fsrec.gz"]
    )

    assert args.path == "/data/aircraft.json"
    assert args.poll_interval == 1.0


def test_main_rejects_non_positive_duration(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--host", "h", "--port", "1", "--duration", "0", "--out", "x.fsrec.gz"])

    assert code == 2
    assert "--duration" in capsys.readouterr().err


def test_main_runs_a_capture_and_prints_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "session.fsrec.gz"
    captured_kwargs: dict[str, object] = {}

    async def fake_run_capture(adapter: object, **kwargs: object) -> CaptureSummary:
        captured_kwargs.update(kwargs)
        header = write_fixture(
            out, batches=[], source=str(kwargs["source"]), duration_s=1.0, created_at=T0
        )
        return CaptureSummary(header=header, aircraft_seen=0, out_path=out, bytes_written=1)

    monkeypatch.setattr("flightsite.devtools.capture.run_capture", fake_run_capture)

    code = main(
        [
            "--host",
            "192.168.1.50",
            "--port",
            "8080",
            "--duration",
            "10",
            "--out",
            str(out),
        ]
    )

    assert code == 0
    assert captured_kwargs["duration_s"] == 10.0
    assert captured_kwargs["source"] == "readsb@http://192.168.1.50:8080/data/aircraft.json"
    output = capsys.readouterr().out
    assert "Captured" in output
