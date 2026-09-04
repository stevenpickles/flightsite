"""The two guards between FlightSite and a third-party API it does not own.

SPEC §28 asks for provider rate limiting and a circuit breaker, and
``docs/ARCHITECTURE.md`` §"Degradation" states what they are for: *"enrichment
silently absent, counted in diagnostics"* rather than a receiver that hammers a
quota or blocks on a host that is down.

Both take their clock as an argument. Not for symmetry — because the rules
being enforced are measured in minutes, and a test that proved them with
``asyncio.sleep`` would take minutes and flake on a loaded machine
(``docs/TEST_STRATEGY.md`` §3). With an injected monotonic clock the same
proofs run in microseconds and are exact.

Neither class awaits anything. A limiter that *slept* until a token was
available would be a queue with no bound and no visibility; instead
:meth:`TokenBucket.take` answers now, and the caller — which owns a bounded
queue and knows what to drop — decides what to do about a refusal.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import structlog

logger = structlog.get_logger(__name__)

#: A source of monotonic seconds, injected so the rules can be tested exactly.
MonotonicClock = Callable[[], float]

#: Requests per minute FlightSite will make of the provider by default.
#:
#: Conservative against every published tier: AeroDataBox's slowest plan allows
#: one request a second, so ten a minute leaves an order of magnitude of
#: headroom and cannot itself trip a gateway limit. It is a *burst* bound, not
#: the monthly one — the free tier's quota is a few hundred flight lookups a
#: month, and what actually keeps FlightSite inside it is the date-bucketed
#: cache in :mod:`flightsite.enrichment.cache`, which asks about a given flight
#: once a day however many times it is seen.
DEFAULT_RATE_PER_MINUTE: Final = 10.0

#: Requests that may be spent at once after an idle period. One minute's worth:
#: a receiver coming up to a sky full of airliners should be allowed to work
#: through them briskly, and then settle to the sustained rate.
DEFAULT_BURST: Final = 10

#: Consecutive failures that open the circuit. Three, because the failures this
#: is protecting against arrive in runs — a host that is down is down for every
#: request — and because a single timeout is not evidence of anything.
DEFAULT_FAILURE_THRESHOLD: Final = 3

#: How long the circuit stays open. Five minutes: long enough that an outage
#: costs a handful of probes rather than a request per aircraft, short enough
#: that a receiver whose internet came back is enriching again within one
#: sighting.
DEFAULT_COOLDOWN_S: Final = 300.0

SECONDS_PER_MINUTE: Final = 60.0


class TokenBucket:
    """A rate limiter that refuses rather than waits.

    Tokens accrue continuously at ``rate_per_minute`` up to ``burst``, and
    :meth:`take` spends one if there is one. Continuous accrual rather than a
    per-window reset is what keeps the limit honest across a window boundary:
    a fixed window lets twice the rate through if the requests cluster either
    side of it.

    Args:
        rate_per_minute: sustained requests per minute.
        burst: tokens that may accumulate while idle.
        clock: monotonic seconds; injected for tests.
    """

    __slots__ = ("_burst", "_clock", "_last_s", "_rate_per_s", "_tokens")

    def __init__(
        self,
        *,
        rate_per_minute: float = DEFAULT_RATE_PER_MINUTE,
        burst: int = DEFAULT_BURST,
        clock: MonotonicClock,
    ) -> None:
        if rate_per_minute <= 0.0:
            raise ValueError("rate_per_minute must be greater than zero")
        if burst < 1:
            raise ValueError("burst must be at least one token")
        self._rate_per_s = rate_per_minute / SECONDS_PER_MINUTE
        self._burst = float(burst)
        self._clock = clock
        self._tokens = float(burst)
        self._last_s = clock()

    def take(self) -> bool:
        """Spend one token if one is available; never blocks."""
        self._refill()
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def _refill(self) -> None:
        now_s = self._clock()
        elapsed_s = now_s - self._last_s
        # A clock that went backwards (it should not, being monotonic) must not
        # drain the bucket: treat it as no time having passed.
        if elapsed_s > 0.0:
            self._tokens = min(self._burst, self._tokens + elapsed_s * self._rate_per_s)
        self._last_s = now_s


class CircuitBreaker:
    """Stops asking a provider that has stopped answering.

    Closed by default. ``failure_threshold`` consecutive failures open it for
    ``cooldown_s``, during which :meth:`allow` refuses without a request being
    made. When the cooldown expires the circuit becomes *half-open*: exactly one
    request is allowed through as a probe, and its outcome decides — success
    closes the circuit and resets the run, failure opens it for another
    cooldown.

    A single probe rather than a full reopen is the point. A provider that is
    still down would otherwise get the whole queue thrown at it the moment the
    timer expired, which is how a circuit breaker becomes a metronome for
    retry storms.

    Args:
        failure_threshold: consecutive failures that open the circuit.
        cooldown_s: how long it stays open.
        clock: monotonic seconds; injected for tests.
    """

    __slots__ = ("_clock", "_cooldown_s", "_failures", "_opened_at_s", "_probing", "_threshold")

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: MonotonicClock,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least one")
        if cooldown_s <= 0.0:
            raise ValueError("cooldown_s must be greater than zero")
        self._threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures = 0
        self._opened_at_s: float | None = None
        self._probing = False

    @property
    def is_open(self) -> bool:
        """True while requests are being refused."""
        return self._opened_at_s is not None and not self._cooled_down()

    @property
    def failures(self) -> int:
        """Length of the current run of consecutive failures."""
        return self._failures

    def allow(self) -> bool:
        """Whether a request may be made now.

        Returns ``True`` for the single half-open probe, and then ``False``
        again until that probe's outcome is recorded.
        """
        if self._opened_at_s is None:
            return True
        if not self._cooled_down():
            return False
        if self._probing:
            return False
        self._probing = True
        return True

    def record_success(self) -> None:
        """Close the circuit and forget the failure run."""
        self.reset()

    def reset(self) -> None:
        """Return to the closed, no-failures state without a success.

        For when the thing being protected is *replaced* rather than proved
        working: :meth:`~flightsite.enrichment.EnrichmentService.apply_provider`
        calls this after swapping a provider, because a run of failures earned
        by a rejected key says nothing about the key that replaced it. Without
        it a re-keyed install would begin life refusing every lookup for a
        cooldown the new key did not earn.
        """
        self._failures = 0
        self._opened_at_s = None
        self._probing = False

    def record_failure(self) -> None:
        """Count a failure, opening the circuit at the threshold.

        A failure recorded while half-open re-opens immediately, whatever the
        run length: the probe was the test, and it failed.
        """
        self._failures += 1
        if self._probing or self._failures >= self._threshold:
            was_open = self._opened_at_s is not None
            self._opened_at_s = self._clock()
            self._probing = False
            if not was_open:
                logger.warning(
                    "enrichment_circuit_opened",
                    failures=self._failures,
                    cooldown_s=self._cooldown_s,
                )

    def _cooled_down(self) -> bool:
        opened_at_s = self._opened_at_s
        return opened_at_s is not None and self._clock() - opened_at_s >= self._cooldown_s


__all__ = [
    "DEFAULT_BURST",
    "DEFAULT_COOLDOWN_S",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_RATE_PER_MINUTE",
    "SECONDS_PER_MINUTE",
    "CircuitBreaker",
    "MonotonicClock",
    "TokenBucket",
]
