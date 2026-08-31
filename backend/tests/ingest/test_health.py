"""The connected / degraded / down state machine and its reconnect backoff."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from flightsite.ingest.health import (
    BACKOFF_INITIAL_S,
    BACKOFF_JITTER_RATIO,
    BACKOFF_MAX_S,
    DOWN_AFTER_CONSECUTIVE_FAILURES,
    AdapterHealth,
    HealthState,
    HealthTracker,
)


class StepClock:
    """A clock that advances one second per reading."""

    def __init__(self) -> None:
        self.moment = datetime(2025, 9, 17, 16, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


def tracker(**kwargs: object) -> HealthTracker:
    defaults: dict[str, object] = {"rng": random.Random(1234), "now": StepClock()}
    defaults.update(kwargs)
    return HealthTracker(**defaults)  # type: ignore[arg-type]


def test_a_tracker_that_has_never_polled_reports_down() -> None:
    health = tracker().health

    # There is no fourth "unknown" state in the vocabulary, and an adapter that
    # has produced nothing is, from the user's point of view, down.
    assert health.state is HealthState.DOWN
    assert health.has_ever_connected is False
    assert health.last_success is None
    assert health.next_retry_delay_s is None


def test_first_success_connects() -> None:
    health = tracker().record_success()

    assert health.state is HealthState.CONNECTED
    assert health.is_connected
    assert health.has_ever_connected
    assert health.total_successes == 1
    assert health.last_success is not None


def test_one_failure_degrades_rather_than_downs() -> None:
    subject = tracker()
    subject.record_success()

    health = subject.record_failure("timeout")

    # A single dropped poll is not an outage.
    assert health.state is HealthState.DEGRADED
    assert health.consecutive_failures == 1
    assert health.last_error == "timeout"


def test_consecutive_failures_reach_down_at_the_threshold() -> None:
    subject = tracker()
    subject.record_success()

    states = [
        subject.record_failure(f"failure {index}").state
        for index in range(DOWN_AFTER_CONSECUTIVE_FAILURES)
    ]

    assert states[:-1] == [HealthState.DEGRADED] * (DOWN_AFTER_CONSECUTIVE_FAILURES - 1)
    assert states[-1] is HealthState.DOWN


def test_recovery_clears_the_failure_run_without_a_restart() -> None:
    subject = tracker()
    for index in range(DOWN_AFTER_CONSECUTIVE_FAILURES + 3):
        subject.record_failure(f"failure {index}")
    assert subject.health.state is HealthState.DOWN

    health = subject.record_success()

    assert health.state is HealthState.CONNECTED
    assert health.consecutive_failures == 0
    assert health.failures_since_success == 0
    assert health.last_error is None
    assert health.next_retry_delay_s is None
    # Lifetime totals survive recovery; they are diagnostics, not state.
    assert health.total_failures == DOWN_AFTER_CONSECUTIVE_FAILURES + 3


def test_transitions_are_reported_once_each() -> None:
    seen: list[tuple[HealthState, HealthState]] = []
    subject = tracker(
        on_transition=lambda previous, current, _health: seen.append((previous, current))
    )

    subject.record_success()
    subject.record_success()  # no transition: still connected
    for index in range(DOWN_AFTER_CONSECUTIVE_FAILURES):
        subject.record_failure(f"failure {index}")
    subject.record_failure("still gone")  # no transition: still down
    subject.record_success()

    assert seen == [
        (HealthState.DOWN, HealthState.CONNECTED),
        (HealthState.CONNECTED, HealthState.DEGRADED),
        (HealthState.DEGRADED, HealthState.DOWN),
        (HealthState.DOWN, HealthState.CONNECTED),
    ]


def test_backoff_grows_exponentially_and_is_capped() -> None:
    subject = tracker()

    # Compare against the undelayed schedule: jitter only ever shortens the
    # delay, and never below half of it.
    for failures in range(1, 12):
        undelayed = min(BACKOFF_INITIAL_S * 2 ** (failures - 1), BACKOFF_MAX_S)
        delay = subject.retry_delay_s(failures)
        assert undelayed * (1.0 - BACKOFF_JITTER_RATIO) <= delay <= undelayed


def test_backoff_never_exceeds_the_cap_even_after_a_very_long_outage() -> None:
    subject = tracker()

    assert subject.retry_delay_s(10_000) <= BACKOFF_MAX_S


def test_backoff_is_jittered_not_lockstepped() -> None:
    subject = tracker()

    delays = {subject.retry_delay_s(6) for _ in range(20)}

    # Identical delays every time would let a fleet of retries resonate with a
    # decoder that restarts on a timer.
    assert len(delays) > 1


def test_backoff_is_deterministic_for_a_seeded_rng() -> None:
    expected = random.Random(99)
    subject = HealthTracker(rng=random.Random(99), now=StepClock())

    delay = subject.retry_delay_s(3)

    undelayed = BACKOFF_INITIAL_S * 4
    fixed = undelayed * (1.0 - BACKOFF_JITTER_RATIO)
    assert delay == pytest.approx(fixed + expected.random() * (undelayed - fixed))


def test_recorded_failure_publishes_the_next_delay() -> None:
    subject = tracker()

    health = subject.record_failure("boom")

    assert health.next_retry_delay_s is not None
    assert 0.0 < health.next_retry_delay_s <= BACKOFF_INITIAL_S


def test_snapshots_are_immutable_values() -> None:
    subject = tracker()
    before = subject.record_success()

    subject.record_failure("later")

    # A caller holding a snapshot is not racing the tracker that made it.
    assert before.state is HealthState.CONNECTED
    assert isinstance(before, AdapterHealth)
    with pytest.raises(AttributeError):
        before.state = HealthState.DOWN  # type: ignore[misc]


def test_down_after_must_be_positive() -> None:
    with pytest.raises(ValueError, match="down_after"):
        HealthTracker(down_after=0)
