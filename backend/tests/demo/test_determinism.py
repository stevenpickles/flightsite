"""Determinism: the roadmap slice 011 acceptance criterion.

"Two runs with the same seed produce identical update sequences." Every
assertion here compares independently constructed objects — never state
carried over within one object — so a passing suite is proof the scenario is
a pure function of ``(seed, tick_index)``, not an accident of shared state.
"""

from __future__ import annotations

import pytest

from flightsite.demo import build_roster
from flightsite.demo.adapter import DEFAULT_CENTER, DemoAdapter
from flightsite.demo.scenario import SCENARIO_EPOCH
from flightsite.ingest.types import Position

SEATTLE = Position(latitude=47.4502, longitude=-122.3088)


def test_same_seed_produces_identical_rosters() -> None:
    first = build_roster(seed=42, population=50, center=DEFAULT_CENTER)
    second = build_roster(seed=42, population=50, center=DEFAULT_CENTER)

    assert first == second


def test_different_seeds_produce_different_rosters() -> None:
    first = build_roster(seed=1, population=50, center=DEFAULT_CENTER)
    second = build_roster(seed=2, population=50, center=DEFAULT_CENTER)

    assert first != second
    assert {profile.icao for profile in first} != {profile.icao for profile in second}


def test_roster_icaos_are_unique() -> None:
    roster = build_roster(seed=7, population=80, center=DEFAULT_CENTER)

    icaos = [profile.icao for profile in roster]
    assert len(icaos) == len(set(icaos))


@pytest.mark.parametrize("tick", [0, 1, 59, 300, 419, 900, 1799, 1800, 5000])
def test_two_adapters_same_seed_produce_identical_batches(tick: int) -> None:
    # The epoch is pinned because it now defaults to the wall clock (issue
    # #107): two adapters built microseconds apart would otherwise differ by
    # a constant offset on every timestamp, which is exactly the property
    # being asserted and would make this pass or fail on construction timing
    # rather than on determinism.
    first = DemoAdapter(seed=42, population=60, epoch=SCENARIO_EPOCH)
    second = DemoAdapter(seed=42, population=60, epoch=SCENARIO_EPOCH)

    assert first.batch_for_tick(tick) == second.batch_for_tick(tick)


def test_two_adapters_different_seed_diverge_somewhere_in_the_first_period() -> None:
    # Pinned for the same reason, and here it matters more: with differing
    # epochs every batch would differ by timestamp alone, so this would pass
    # without the seeds diverging at all.
    first = DemoAdapter(seed=1, population=60, epoch=SCENARIO_EPOCH)
    second = DemoAdapter(seed=2, population=60, epoch=SCENARIO_EPOCH)

    batches = [
        (first.batch_for_tick(tick), second.batch_for_tick(tick)) for tick in range(0, 900, 30)
    ]
    assert any(a != b for a, b in batches)


def test_batch_for_tick_is_stateless_and_order_independent() -> None:
    """Re-asking for an earlier tick after a later one gives the same answer.

    Nothing may be cached or threaded from one call to the next: this is what
    lets a consumer resync (WebSocket reconnect, a replayed capture) to any
    tick without replaying the ticks before it.
    """
    adapter = DemoAdapter(seed=42, population=60)

    forward = [adapter.batch_for_tick(tick) for tick in range(60)]
    out_of_order = [adapter.batch_for_tick(tick) for tick in reversed(range(60))]

    assert forward == list(reversed(out_of_order))


def test_a_receiver_relocated_center_changes_the_roster_deterministically() -> None:
    """The center is scenario geometry, not randomness — but it still must be
    reproducible: the same ``(seed, center)`` pair always builds the same
    roster.
    """
    first = build_roster(seed=99, population=40, center=SEATTLE)
    second = build_roster(seed=99, population=40, center=SEATTLE)
    different_center = build_roster(seed=99, population=40, center=DEFAULT_CENTER)

    assert first == second
    assert first != different_center


async def test_updates_stream_yields_ticks_in_order_from_the_injected_clock() -> None:
    """The async loop is just plumbing around ``batch_for_tick``: it must
    yield exactly the ticks the injected clock says have elapsed, in order.
    """

    class FakeClock:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = FakeClock()

    async def fake_sleep(seconds: float) -> None:
        clock.value += seconds

    adapter = DemoAdapter(seed=1, population=10, clock=clock, sleep=fake_sleep)
    await adapter.start()

    collected = []
    async for batch in adapter.updates():
        collected.append(batch)
        if len(collected) == 4:
            break
    await adapter.stop()

    expected = [adapter.batch_for_tick(tick) for tick in (0, 1, 2, 3)]
    assert collected == expected
