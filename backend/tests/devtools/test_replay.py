"""``ReplayAdapter``: pacing, looping, health, protocol conformance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from flightsite.devtools.fixture import Fixture, FixtureHeader, FixtureRecord, write_fixture
from flightsite.devtools.replay import ReplayAdapter
from flightsite.ingest.health import HealthState
from flightsite.ingest.protocol import DecoderAdapter
from flightsite.ingest.types import AircraftStateBatch

from .conftest import T0, make_batches


class RecordedSleep:
    """Records requested delays instead of actually waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def make_fixture(count: int = 3, *, interval_s: float = 1.0) -> Fixture:
    batches = make_batches(count, interval_s=interval_s)
    header = FixtureHeader(
        format_version=1,
        created_at=T0,
        source="test",
        duration_s=interval_s * max(count - 1, 0),
        batch_count=count,
        update_count=sum(len(batch) for batch in batches),
    )
    records = tuple(
        FixtureRecord(relative_s=interval_s * index, batch=batch)
        for index, batch in enumerate(batches)
    )
    return Fixture(header=header, records=records)


async def collect(adapter: ReplayAdapter, *, limit: int | None = None) -> list[AircraftStateBatch]:
    collected: list[AircraftStateBatch] = []
    async for batch in adapter.updates():
        collected.append(batch)
        if limit is not None and len(collected) >= limit:
            break
    return collected


# --------------------------------------------------------------- pacing


async def test_as_fast_as_possible_never_sleeps() -> None:
    fixture = make_fixture(4)
    sleeper = RecordedSleep()
    adapter = ReplayAdapter(fixture, speed=None, sleep=sleeper)
    await adapter.start()

    batches = await collect(adapter)

    assert len(batches) == 4
    assert sleeper.delays == []


async def test_real_time_pacing_replays_recorded_gaps() -> None:
    fixture = make_fixture(3, interval_s=2.0)
    sleeper = RecordedSleep()
    adapter = ReplayAdapter(fixture, speed=1.0, sleep=sleeper)
    await adapter.start()

    await collect(adapter)

    assert sleeper.delays == pytest.approx([2.0, 2.0])


async def test_accelerated_pacing_divides_gaps_by_the_speed_factor() -> None:
    fixture = make_fixture(3, interval_s=2.0)
    sleeper = RecordedSleep()
    adapter = ReplayAdapter(fixture, speed=4.0, sleep=sleeper)
    await adapter.start()

    await collect(adapter)

    assert sleeper.delays == pytest.approx([0.5, 0.5])


async def test_speed_must_be_positive() -> None:
    fixture = make_fixture(1)
    with pytest.raises(ValueError, match="positive"):
        ReplayAdapter(fixture, speed=0)
    with pytest.raises(ValueError, match="positive"):
        ReplayAdapter(fixture, speed=-1.0)


# ---------------------------------------------------------------- health


async def test_health_starts_down_before_playback() -> None:
    adapter = ReplayAdapter(make_fixture(2), speed=None)
    assert adapter.health().state is HealthState.DOWN


async def test_health_is_connected_while_batches_are_yielded() -> None:
    adapter = ReplayAdapter(make_fixture(3), speed=None, sleep=RecordedSleep())
    await adapter.start()

    states = []
    async for _ in adapter.updates():
        states.append(adapter.health().state)

    assert states == [HealthState.CONNECTED] * 3


async def test_health_goes_down_at_eof_when_not_looping() -> None:
    adapter = ReplayAdapter(make_fixture(2), speed=None, sleep=RecordedSleep())
    await adapter.start()

    await collect(adapter)

    assert adapter.health().state is HealthState.DOWN


async def test_health_stays_connected_across_loop_restarts() -> None:
    adapter = ReplayAdapter(make_fixture(2), speed=None, loop=True, sleep=RecordedSleep())
    await adapter.start()

    batches = await collect(adapter, limit=5)  # more than one fixture's worth

    assert len(batches) == 5
    assert adapter.health().state is HealthState.CONNECTED


async def test_stop_marks_health_down() -> None:
    adapter = ReplayAdapter(make_fixture(3), speed=None, sleep=RecordedSleep())
    await adapter.start()
    async for _ in adapter.updates():
        break

    await adapter.stop()

    assert adapter.health().state is HealthState.DOWN


async def test_health_uses_the_injected_clock() -> None:
    fixed = datetime(2030, 1, 1, tzinfo=UTC)
    adapter = ReplayAdapter(make_fixture(1), speed=None, sleep=RecordedSleep(), now=lambda: fixed)
    await adapter.start()

    async for _ in adapter.updates():
        pass

    assert adapter.health().last_success == fixed


# ------------------------------------------------------------- lifecycle


async def test_a_stopped_adapter_yields_nothing() -> None:
    adapter = ReplayAdapter(make_fixture(3), speed=None, sleep=RecordedSleep())
    # Never started.

    batches = await collect(adapter)

    assert batches == []


async def test_stop_ends_playback_mid_stream() -> None:
    adapter = ReplayAdapter(make_fixture(5), speed=None, sleep=RecordedSleep())
    await adapter.start()

    collected = []
    async for batch in adapter.updates():
        collected.append(batch)
        if len(collected) == 2:
            await adapter.stop()

    assert len(collected) == 2


async def test_looping_replays_the_fixture_repeatedly() -> None:
    fixture = make_fixture(2)
    adapter = ReplayAdapter(fixture, speed=None, loop=True, sleep=RecordedSleep())
    await adapter.start()

    batches = await collect(adapter, limit=6)

    assert [b.timestamp for b in batches] == [
        record.batch.timestamp for record in fixture.records
    ] * 3


async def test_empty_fixture_yields_nothing_and_reports_down() -> None:
    empty = Fixture(
        header=FixtureHeader(
            format_version=1,
            created_at=T0,
            source="test",
            duration_s=0.0,
            batch_count=0,
            update_count=0,
        ),
        records=(),
    )
    adapter = ReplayAdapter(empty, speed=None, sleep=RecordedSleep())
    await adapter.start()

    batches = await collect(adapter)

    assert batches == []
    assert adapter.health().state is HealthState.DOWN


# --------------------------------------------------------------- protocol


async def test_replay_adapter_satisfies_the_decoder_adapter_protocol() -> None:
    assert isinstance(ReplayAdapter(make_fixture(1)), DecoderAdapter)


async def test_from_path_loads_a_written_fixture(tmp_path: Path) -> None:
    batches = make_batches(2)
    out = tmp_path / "session.fsrec.gz"
    write_fixture(out, batches=batches, source="test", duration_s=1.0, created_at=T0)

    adapter = ReplayAdapter.from_path(out, speed=None, sleep=RecordedSleep())
    await adapter.start()
    collected = await collect(adapter)

    assert collected == batches


def test_fixture_property_exposes_the_loaded_recording() -> None:
    fixture = make_fixture(2)
    adapter = ReplayAdapter(fixture, speed=None)

    assert adapter.fixture is fixture
