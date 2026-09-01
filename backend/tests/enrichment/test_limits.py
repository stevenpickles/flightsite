"""The token bucket and the circuit breaker, on a hand-driven clock.

Every rule here is measured in minutes. With an injected clock the proofs are
exact and run in microseconds; with a wall clock they would take minutes and
flake on a loaded machine (``docs/TEST_STRATEGY.md`` §3).
"""

from __future__ import annotations

import pytest

from flightsite.enrichment.limits import (
    DEFAULT_BURST,
    DEFAULT_RATE_PER_MINUTE,
    CircuitBreaker,
    TokenBucket,
)


class FakeClock:
    """Monotonic seconds the test advances by hand."""

    def __init__(self) -> None:
        self.seconds = 100.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


# ------------------------------------------------------------- token bucket


def test_a_fresh_bucket_holds_its_full_burst(fake_clock: FakeClock) -> None:
    bucket = TokenBucket(rate_per_minute=10.0, burst=4, clock=fake_clock)

    assert [bucket.take() for _ in range(4)] == [True] * 4


def test_the_burst_is_the_bound(fake_clock: FakeClock) -> None:
    """A fifth request in the same instant is refused, not queued."""
    bucket = TokenBucket(rate_per_minute=10.0, burst=4, clock=fake_clock)
    for _ in range(4):
        bucket.take()

    assert bucket.take() is False


def test_tokens_accrue_continuously(fake_clock: FakeClock) -> None:
    """Six a minute is one every ten seconds, not six at each minute mark."""
    bucket = TokenBucket(rate_per_minute=6.0, burst=1, clock=fake_clock)
    assert bucket.take() is True

    fake_clock.advance(9.0)
    assert bucket.take() is False

    fake_clock.advance(1.0)
    assert bucket.take() is True


def test_accrual_stops_at_the_burst(fake_clock: FakeClock) -> None:
    """An hour idle does not buy an hour's worth of requests at once."""
    bucket = TokenBucket(rate_per_minute=60.0, burst=3, clock=fake_clock)
    fake_clock.advance(3_600.0)

    assert [bucket.take() for _ in range(4)] == [True, True, True, False]


def test_a_clock_that_went_backwards_does_not_drain_the_bucket(
    fake_clock: FakeClock,
) -> None:
    bucket = TokenBucket(rate_per_minute=60.0, burst=2, clock=fake_clock)
    fake_clock.advance(-30.0)

    assert bucket.take() is True


def test_the_shipped_default_is_ten_a_minute() -> None:
    """The constant the service uses, asserted so a change is deliberate."""
    assert DEFAULT_RATE_PER_MINUTE == 10.0
    assert DEFAULT_BURST == 10


@pytest.mark.parametrize(
    ("rate", "burst"),
    [pytest.param(0.0, 1, id="zero-rate"), pytest.param(10.0, 0, id="zero-burst")],
)
def test_a_meaningless_limiter_is_refused(rate: float, burst: int, fake_clock: FakeClock) -> None:
    with pytest.raises(ValueError, match="must be"):
        TokenBucket(rate_per_minute=rate, burst=burst, clock=fake_clock)


# ---------------------------------------------------------- circuit breaker


def test_a_fresh_circuit_allows(fake_clock: FakeClock) -> None:
    assert CircuitBreaker(clock=fake_clock).allow() is True


def test_the_threshold_opens_the_circuit(fake_clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_s=300.0, clock=fake_clock)
    for _ in range(2):
        breaker.record_failure()
    assert breaker.is_open is False

    breaker.record_failure()

    assert breaker.is_open is True
    assert breaker.allow() is False


def test_a_success_resets_the_run(fake_clock: FakeClock) -> None:
    """Consecutive failures, not cumulative ones: an outage, not a tally."""
    breaker = CircuitBreaker(failure_threshold=3, cooldown_s=300.0, clock=fake_clock)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.is_open is False
    assert breaker.failures == 2


def test_the_circuit_refuses_for_the_whole_cooldown(fake_clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_s=300.0, clock=fake_clock)
    breaker.record_failure()

    fake_clock.advance(299.0)

    assert breaker.allow() is False


def test_one_probe_is_allowed_when_the_cooldown_expires(fake_clock: FakeClock) -> None:
    """Exactly one. A full reopen would throw the queue at a host still down."""
    breaker = CircuitBreaker(failure_threshold=1, cooldown_s=300.0, clock=fake_clock)
    breaker.record_failure()
    fake_clock.advance(300.0)

    assert breaker.allow() is True
    assert breaker.allow() is False


def test_a_successful_probe_closes_the_circuit(fake_clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_s=300.0, clock=fake_clock)
    breaker.record_failure()
    fake_clock.advance(300.0)
    assert breaker.allow() is True

    breaker.record_success()

    assert breaker.is_open is False
    assert breaker.allow() is True


def test_a_failed_probe_reopens_for_another_cooldown(fake_clock: FakeClock) -> None:
    """The probe was the test; failing it re-opens whatever the run length."""
    breaker = CircuitBreaker(failure_threshold=5, cooldown_s=300.0, clock=fake_clock)
    for _ in range(5):
        breaker.record_failure()
    fake_clock.advance(300.0)
    assert breaker.allow() is True

    breaker.record_failure()

    assert breaker.is_open is True
    fake_clock.advance(299.0)
    assert breaker.allow() is False
    fake_clock.advance(1.0)
    assert breaker.allow() is True


@pytest.mark.parametrize(
    ("threshold", "cooldown"),
    [pytest.param(0, 1.0, id="zero-threshold"), pytest.param(1, 0.0, id="zero-cooldown")],
)
def test_a_meaningless_breaker_is_refused(
    threshold: int, cooldown: float, fake_clock: FakeClock
) -> None:
    with pytest.raises(ValueError, match="must be"):
        CircuitBreaker(failure_threshold=threshold, cooldown_s=cooldown, clock=fake_clock)
