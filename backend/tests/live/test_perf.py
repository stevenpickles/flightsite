"""Perf sanity: a 500-aircraft 1 Hz batch applies in well under one poll.

The slice acceptance criterion is *"500-aircraft 1 Hz batch applies in <=100 ms
on dev hardware"*, and ``docs/ARCHITECTURE.md`` §3.3 states the budget it
protects: the adapter loop normalizes and applies a batch between polls, so an
apply that approaches the polling interval turns the live picture into a
backlog.

Marked ``perf`` so it can be selected (``-m perf``) or excluded
(``-m "not perf"``), but it runs in the normal suite: a regression that doubles
the cost of applying a batch should fail a routine test run, not wait for
someone to remember the marker. The measurement is deliberately generous about
the machine — the median of several steady-state batches, not a single cold
one — so it fails on an algorithmic regression rather than on a busy laptop.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position, PositionSource
from flightsite.live import LiveStore

from .conftest import BASE_TIME, SEATTLE

AIRCRAFT_COUNT = 500
BUDGET_MS = 100.0
BATCHES = 9


def synthetic_batch(sequence: int) -> AircraftStateBatch:
    """A batch of 500 aircraft, most positioned and moving, some Mode S-only.

    Every field a decoder can report is populated for the positioned majority,
    because the cost being measured is the full merge, derive and track-append
    path — not a stripped-down update that skips most of it.
    """
    timestamp = BASE_TIME + timedelta(seconds=sequence)
    updates: list[AircraftStateUpdate] = []
    for index in range(AIRCRAFT_COUNT):
        icao = f"{index:06x}"
        # Every tenth aircraft is tracked without a position (Mode S only),
        # roughly the proportion a real receiver sees.
        if index % 10 == 0:
            updates.append(
                AircraftStateUpdate(
                    icao=icao,
                    timestamp=timestamp,
                    callsign=f"FS{index:04d}",
                    squawk="1200",
                    rssi_db=-21.4,
                    messages=100 + sequence,
                    seen_s=0.3,
                )
            )
            continue
        source: PositionSource = "mlat" if index % 7 == 0 else "adsb"
        updates.append(
            AircraftStateUpdate(
                icao=icao,
                timestamp=timestamp,
                position=Position(
                    latitude=46.0 + (index % 200) * 0.01 + sequence * 0.001,
                    longitude=-123.0 + (index % 150) * 0.01 + sequence * 0.001,
                ),
                position_source=source,
                callsign=f"FS{index:04d}",
                squawk="4521",
                altitude_ft=1_000.0 + (index % 380) * 100.0,
                altitude_geometric_ft=1_050.0 + (index % 380) * 100.0,
                ground_speed_kt=120.0 + (index % 300),
                track_deg=float(index % 360),
                vertical_rate_fpm=-640.0,
                on_ground=False,
                rssi_db=-12.1,
                messages=1_000 + sequence,
                seen_s=0.2,
                seen_pos_s=0.4,
            )
        )
    return AircraftStateBatch(timestamp=timestamp, updates=tuple(updates))


@pytest.mark.perf
def test_a_500_aircraft_batch_applies_inside_the_budget() -> None:
    store = LiveStore(receiver_location=SEATTLE)
    subscription = store.subscribe("perf")

    # Warm up: the first batch is all appearances, which is the cheap case and
    # not what a running receiver does every second.
    store.apply(synthetic_batch(0))
    subscription.drain()

    elapsed_ms: list[float] = []
    for sequence in range(1, BATCHES + 1):
        batch = synthetic_batch(sequence)
        started = time.perf_counter()
        store.apply(batch)
        elapsed_ms.append((time.perf_counter() - started) * 1_000.0)
        # Drain outside the measured window: a real consumer runs on its own
        # task, and an unbounded backlog would distort later batches.
        subscription.drain()

    elapsed_ms.sort()
    median_ms = elapsed_ms[len(elapsed_ms) // 2]

    assert len(store) == AIRCRAFT_COUNT
    assert median_ms <= BUDGET_MS, (
        f"applying {AIRCRAFT_COUNT} aircraft took {median_ms:.1f} ms "
        f"(budget {BUDGET_MS:.0f} ms); samples: "
        + ", ".join(f"{sample:.1f}" for sample in elapsed_ms)
    )


@pytest.mark.perf
def test_a_sweep_over_a_full_live_set_is_cheap() -> None:
    # The lifecycle timer runs every second over the whole live set, so its
    # cost belongs in the same budget as applying a batch.
    store = LiveStore(receiver_location=SEATTLE)
    store.apply(synthetic_batch(0))

    started = time.perf_counter()
    store.sweep()
    elapsed_ms = (time.perf_counter() - started) * 1_000.0

    assert elapsed_ms <= BUDGET_MS
