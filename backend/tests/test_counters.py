"""Unit tests for the internal counters registry."""

from __future__ import annotations

import threading

import pytest

from flightsite.counters import KNOWN_COUNTERS, CounterRegistry


def test_snapshot_starts_at_zero_for_all_known_counters() -> None:
    registry = CounterRegistry()

    snapshot = registry.snapshot()

    assert set(snapshot) == set(KNOWN_COUNTERS)
    assert all(value == 0 for value in snapshot.values())


def test_increment_default_amount_is_one() -> None:
    registry = CounterRegistry()

    registry.increment("db_errors")

    assert registry.snapshot()["db_errors"] == 1


def test_increment_custom_amount() -> None:
    registry = CounterRegistry()

    registry.increment("ws_disconnects", amount=5)

    assert registry.snapshot()["ws_disconnects"] == 5


def test_increment_unknown_counter_raises() -> None:
    registry = CounterRegistry()

    with pytest.raises(KeyError):
        registry.increment("not_a_real_counter")


def test_snapshot_is_independent_copy() -> None:
    registry = CounterRegistry()

    snapshot = registry.snapshot()
    snapshot["db_errors"] = 999

    assert registry.snapshot()["db_errors"] == 0


def test_concurrent_increments_are_thread_safe() -> None:
    registry = CounterRegistry()
    iterations = 1000
    thread_count = 8

    def worker() -> None:
        for _ in range(iterations):
            registry.increment("ingestion_failures")

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert registry.snapshot()["ingestion_failures"] == iterations * thread_count
