"""Per-sighting reception statistics (SPEC §51).

The roadmap's acceptance criterion is that they "match brute-force computation
over the update stream", so that is what these tests do: build a stream of
observations, recompute every figure independently in the test, and compare.
The brute force deliberately reimplements the documented definitions rather
than calling the accumulator, which is the only way the comparison says
anything.

Definitions under test (``state.py``, ``ActiveSighting``):

* ``msg_count`` — the decoder's own cumulative counter, differenced.
* ``pos_count`` — one per *new* position report, not per observation.
* ``rssi_peak_db`` / ``rssi_min_db`` / ``rssi_avg_db`` — extremes and the mean
  over every observation that reported ``rssi_db``.
* ``pos_time_pct`` — the share of the sighting's elapsed time whose intervals
  carried a new position report.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

from .conftest import (
    REMOVE_S,
    SEATTLE,
    SimulatedTime,
    observe,
    offset_from,
    only_sighting,
    worker_on,
)


@dataclass(frozen=True, slots=True)
class Update:
    """One observation in a generated stream, as the decoder would report it."""

    step_s: float
    messages: int | None
    rssi_db: float | None
    positioned: bool


def stream(rng: random.Random, count: int) -> list[Update]:
    """A plausible update stream: mostly positioned, occasionally silent."""
    messages = 0
    updates: list[Update] = []
    for _ in range(count):
        messages += rng.randint(1, 40)
        updates.append(
            Update(
                step_s=float(rng.randint(1, 6)),
                messages=messages,
                rssi_db=round(rng.uniform(-32.0, -6.0), 1),
                positioned=rng.random() < 0.75,
            )
        )
    return updates


def apply(live: LiveStore, clock: SimulatedTime, updates: list[Update]) -> None:
    """Feed a generated stream into the live store on the simulated clock."""
    for index, update in enumerate(updates):
        clock.advance(update.step_s)
        observe(
            live,
            clock,
            position=offset_from(SEATTLE, 5.0 + index * 0.3, index * index * 0.01)
            if update.positioned
            else None,
            messages=update.messages,
            rssi_db=update.rssi_db,
            altitude_ft=20_000.0,
        )


def brute_force(updates: list[Update], clock_start_s: float = 0.0) -> dict[str, float | int | None]:
    """Recompute the statistics straight from the stream, per the definitions."""
    elapsed_s = clock_start_s
    first_ms: int | None = None
    last_ms = 0
    previous_ms: int | None = None
    messages_seen: int | None = None
    msg_count = 0
    pos_count = 0
    positioned_ms = 0
    rssi: list[float] = []

    for update in updates:
        elapsed_s += update.step_s
        at_ms = int(elapsed_s * 1_000)
        if first_ms is None:
            first_ms = at_ms
        last_ms = at_ms

        if update.messages is not None:
            if messages_seen is None or update.messages < messages_seen:
                msg_count += max(0, update.messages)
            else:
                msg_count += update.messages - messages_seen
            messages_seen = update.messages
        if update.rssi_db is not None:
            rssi.append(update.rssi_db)
        if update.positioned:
            pos_count += 1
            if previous_ms is not None:
                positioned_ms += at_ms - previous_ms
        previous_ms = at_ms

    duration_ms = last_ms - (first_ms or last_ms)
    return {
        "msg_count": msg_count,
        "pos_count": pos_count,
        "rssi_peak_db": max(rssi) if rssi else None,
        "rssi_min_db": min(rssi) if rssi else None,
        "rssi_avg_db": sum(rssi) / len(rssi) if rssi else None,
        "pos_time_pct": (
            None if duration_ms <= 0 else min(100.0, positioned_ms * 100.0 / duration_ms)
        ),
    }


async def test_statistics_match_brute_force_over_generated_streams(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    updates = stream(random.Random(2026), 120)
    apply(live, clock, updates)

    await worker.process_pending()

    expected = brute_force(updates)
    sighting = await only_sighting(database)
    assert sighting.msg_count == expected["msg_count"]
    assert sighting.pos_count == expected["pos_count"]
    assert sighting.rssi_peak_db == pytest.approx(expected["rssi_peak_db"])
    assert sighting.rssi_min_db == pytest.approx(expected["rssi_min_db"])
    assert sighting.rssi_avg_db == pytest.approx(expected["rssi_avg_db"])
    assert sighting.pos_time_pct == pytest.approx(expected["pos_time_pct"])


async def test_statistics_match_brute_force_across_many_seeds(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # One worker per test, so the seeds share a sighting: each iteration extends
    # the same stream, which is also the harder case — the running sums have to
    # stay right across flushes, not merely at the first one.
    updates: list[Update] = []
    for seed in range(5):
        batch = stream(random.Random(seed), 40)
        updates.extend(batch)
        apply(live, clock, batch)
        await worker.process_pending()

    expected = brute_force(updates)
    sighting = await only_sighting(database)
    assert sighting.msg_count == expected["msg_count"]
    assert sighting.pos_count == expected["pos_count"]
    assert sighting.rssi_avg_db == pytest.approx(expected["rssi_avg_db"])
    assert sighting.pos_time_pct == pytest.approx(expected["pos_time_pct"])


async def test_the_running_mean_is_a_mean_of_every_sample(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Stated on a hand-checkable case, because "running mean" is exactly the
    # kind of arithmetic a brute-force comparison can agree with while both
    # sides are wrong the same way.
    for rssi in (-10.0, -20.0, -30.0, -40.0):
        clock.advance(5.0)
        observe(live, clock, rssi_db=rssi)

    await worker.process_pending()

    sighting = await only_sighting(database)
    assert sighting.rssi_avg_db == pytest.approx(-25.0)
    assert sighting.rssi_peak_db == -10.0  # dBFS: the peak is the strongest
    assert sighting.rssi_min_db == -40.0


async def test_message_counts_are_deltas_of_the_decoder_counter(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # readsb reports a cumulative per-trackfile counter. Storing it raw would
    # make msg_count "messages since the decoder started", not "messages in
    # this sighting" — the same number only by coincidence.
    for messages in (100, 250, 400):
        clock.advance(5.0)
        observe(live, clock, messages=messages)

    await worker.process_pending()

    assert (await only_sighting(database)).msg_count == 400


async def test_a_decoder_counter_reset_is_not_a_negative_delta(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # A restarted decoder starts its trackfile counter again. Subtracting would
    # give a negative delta; the new value is what it has counted since.
    for messages in (100, 250, 30, 45):
        clock.advance(5.0)
        observe(live, clock, messages=messages)

    await worker.process_pending()

    assert (await only_sighting(database)).msg_count == 250 + 30 + 15


async def test_a_decoder_reporting_no_counts_leaves_the_count_at_zero(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # SPEC §60: a metric a decoder does not supply is not invented. Counting
    # observations instead would report a number that looks like a message
    # count and is not one.
    for _ in range(4):
        clock.advance(5.0)
        observe(live, clock, rssi_db=-15.0)

    await worker.process_pending()

    sighting = await only_sighting(database)
    assert sighting.msg_count == 0
    assert sighting.rssi_avg_db == -15.0


async def test_position_time_is_the_share_of_the_sighting_with_positions(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """Half a sighting tracked, half of it Mode S only.

    The live record's position is *sticky* — an aircraft that stops reporting
    keeps its last known one — so a naive "did it have a position" test would
    answer 100% for this stream. The figure has to follow the reports.
    """
    for index in range(10):
        clock.advance(10.0)
        observe(live, clock, position=offset_from(SEATTLE, 5.0 + index, 0.0))
    for _ in range(10):
        clock.advance(10.0)
        observe(live, clock, altitude_ft=20_000.0)

    await worker.process_pending()

    sighting = await only_sighting(database)
    assert sighting.pos_count == 10
    # Nine of the nineteen inter-observation intervals carried a new position.
    assert sighting.pos_time_pct == pytest.approx(9 / 19 * 100.0, rel=1e-6)


async def test_a_fully_tracked_aircraft_reports_full_position_time(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    for index in range(8):
        clock.advance(5.0)
        observe(live, clock, position=offset_from(SEATTLE, 5.0 + index, 0.0))

    await worker.process_pending()

    assert (await only_sighting(database)).pos_time_pct == pytest.approx(100.0)


async def test_a_never_positioned_aircraft_reports_none(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    for _ in range(4):
        clock.advance(5.0)
        observe(live, clock, altitude_ft=3_000.0)

    await worker.process_pending()

    sighting = await only_sighting(database)
    assert sighting.pos_count == 0
    assert sighting.pos_time_pct == 0.0


async def test_a_single_observation_leaves_position_time_unanswerable(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # No elapsed time, no share of it: NULL is the honest answer, not 0 or 100.
    observe(live, clock, position=offset_from(SEATTLE, 5.0, 0.0))

    await worker.process_pending()

    assert (await only_sighting(database)).pos_time_pct is None


async def test_a_replayed_observation_is_not_counted_twice(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """The resync path re-observes records the worker may already have folded in.

    Counting a message or an RSSI sample again would make the statistics depend
    on how often the event queue overflowed, which is not a fact about the
    aircraft.
    """
    for index in range(5):
        clock.advance(5.0)
        observe(live, clock, position=offset_from(SEATTLE, 5.0 + index, 0.0), messages=index * 10)
    await worker.process_pending()
    before = await only_sighting(database)
    counts = (before.msg_count, before.pos_count, before.rssi_avg_db)

    accumulator = worker.sighting_for("ae1463")
    assert accumulator is not None
    for record in live.snapshot():
        accumulator.observe(record)
    await worker.process_pending()

    after = await only_sighting(database)
    assert (after.msg_count, after.pos_count, after.rssi_avg_db) == counts


async def test_statistics_survive_a_restart_mid_sighting(
    worker: PersistenceWorker,
    live: LiveStore,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """A restart continues the sighting, so it must continue its statistics.

    Counts and extremes come back exactly; the mean comes back as a
    ``pos_count``-weighted prior, since no column carries its sample count
    (see ``OpenSightingRow.to_accumulator``). What must never happen is a
    restart resetting a sighting's totals to zero.
    """
    for index in range(6):
        clock.advance(5.0)
        observe(
            live,
            clock,
            position=offset_from(SEATTLE, 5.0 + index, 0.0),
            messages=(index + 1) * 20,
            rssi_db=-14.0,
        )
    await worker.process_pending()
    await worker.stop()

    async with worker_on(database, live, clock) as restarted:
        clock.advance(5.0)
        observe(live, clock, position=offset_from(SEATTLE, 12.0, 0.0), messages=200, rssi_db=-14.0)
        await restarted.process_pending()

        sighting = await only_sighting(database)
        assert sighting.msg_count == 200
        assert sighting.pos_count == 7
        assert sighting.rssi_peak_db == -14.0
        assert sighting.rssi_avg_db == pytest.approx(-14.0)
        assert sighting.pos_time_pct == pytest.approx(100.0)


async def test_the_statistics_are_final_at_close(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The close is the last write of the row, and the signal-distribution chart
    # (DATA_MODEL §6.2) reads these columns over closed sightings.
    updates = stream(random.Random(7), 30)
    apply(live, clock, updates)
    await worker.process_pending()

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(601.0)
    await worker.process_pending()

    expected = brute_force(updates)
    sighting = await only_sighting(database)
    assert sighting.ended_ms is not None
    assert sighting.msg_count == expected["msg_count"]
    assert sighting.rssi_avg_db == pytest.approx(expected["rssi_avg_db"])
