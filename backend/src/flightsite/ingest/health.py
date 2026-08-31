"""Decoder connection health and reconnect backoff.

The state machine is the one named in
[ADR-0003](../../../../docs/adr/0003-decoder-adapter-abstraction.md) and
``docs/ARCHITECTURE.md`` §7: **connected / degraded / down**, with automatic
reconnect. It is deliberately transport-agnostic — it counts successes and
failures and hands back a delay — so a future Beast or SBS adapter can reuse
it without change.

State meaning:

* ``connected`` — the most recent poll succeeded.
* ``degraded``  — polls are failing, but not yet often enough in a row to call
  the decoder gone. Live aircraft are still aging out normally and the UI can
  say "we are missing updates" without crying wolf over one dropped packet.
* ``down``      — :data:`DOWN_AFTER_CONSECUTIVE_FAILURES` polls in a row have
  failed. Reconnect keeps running; nothing is torn down.

A tracker that has never completed a poll reports ``down``, which is the
truthful answer for a freshly started adapter pointed at an unreachable
decoder and for one that has simply not polled yet. The vocabulary has no
fourth "unknown" value and inventing one would leak into the API.

Readiness is deliberately *not* wired to this: see
:mod:`flightsite.ingest.service`.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final


class HealthState(StrEnum):
    """Decoder connection state (``docs/ARCHITECTURE.md`` §7)."""

    CONNECTED = "connected"
    DEGRADED = "degraded"
    DOWN = "down"


#: Consecutive failures before the decoder is declared ``down``. Four failed
#: polls at the default 1 Hz interval is roughly five seconds of silence —
#: long enough that a single dropped request or a decoder restart does not
#: raise the alarm, short enough that a real outage is visible immediately.
DOWN_AFTER_CONSECUTIVE_FAILURES: Final = 4

#: First reconnect delay, in seconds.
BACKOFF_INITIAL_S: Final = 1.0

#: Multiplier applied per consecutive failure.
BACKOFF_FACTOR: Final = 2.0

#: Ceiling on the reconnect delay. A decoder that comes back after an hour
#: should be picked up within a minute, not after another hour of doubling.
BACKOFF_MAX_S: Final = 60.0

#: Equal jitter: the delay is half the computed backoff plus a random share of
#: the other half. This keeps retries from lockstepping with a decoder that
#: restarts on a timer, without ever collapsing the delay to zero.
BACKOFF_JITTER_RATIO: Final = 0.5


@dataclass(frozen=True, slots=True)
class AdapterHealth:
    """An immutable snapshot of a decoder connection's health.

    Snapshots are values, so a caller can hold one, compare it with a later
    one, or serialize it for diagnostics (slice 042) without racing the
    adapter that produced it.
    """

    state: HealthState = HealthState.DOWN
    consecutive_failures: int = 0
    failures_since_success: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None
    next_retry_delay_s: float | None = None

    @property
    def is_connected(self) -> bool:
        """True when the most recent poll succeeded."""
        return self.state is HealthState.CONNECTED

    @property
    def has_ever_connected(self) -> bool:
        """True once at least one poll has succeeded."""
        return self.total_successes > 0


class HealthTracker:
    """Turns a stream of poll outcomes into a :class:`AdapterHealth` snapshot.

    The tracker owns the transition rules and the reconnect delay, and nothing
    else: it performs no I/O, starts no tasks and never sleeps. The adapter
    reports ``record_success()`` / ``record_failure()`` and asks for
    :meth:`retry_delay_s`, which makes every rule here testable with a fake
    clock and a seeded RNG.

    Args:
        down_after: consecutive failures before the state becomes ``down``.
        rng: random source for backoff jitter; inject a seeded
            :class:`random.Random` to make reconnect tests deterministic.
        now: clock returning an aware UTC ``datetime``; injectable for tests.
        on_transition: called with ``(previous, current, health)`` whenever the
            state changes. The adapter uses it to log transitions once, rather
            than logging every poll.
    """

    def __init__(
        self,
        *,
        down_after: int = DOWN_AFTER_CONSECUTIVE_FAILURES,
        rng: random.Random | None = None,
        now: Callable[[], datetime] | None = None,
        on_transition: Callable[[HealthState, HealthState, AdapterHealth], None] | None = None,
    ) -> None:
        if down_after < 1:
            raise ValueError("down_after must be at least 1")
        self._down_after = down_after
        self._rng = rng if rng is not None else random.Random()
        self._now = now if now is not None else _utc_now
        self._on_transition = on_transition
        self._health = AdapterHealth()

    @property
    def health(self) -> AdapterHealth:
        """The current snapshot."""
        return self._health

    def record_success(self) -> AdapterHealth:
        """Record a successful poll, clearing the failure run."""
        return self._update(
            replace(
                self._health,
                state=HealthState.CONNECTED,
                consecutive_failures=0,
                failures_since_success=0,
                total_successes=self._health.total_successes + 1,
                last_success=self._now(),
                last_error=None,
                next_retry_delay_s=None,
            )
        )

    def record_failure(self, error: str) -> AdapterHealth:
        """Record a failed poll and compute the next reconnect delay.

        ``error`` is a short human-readable reason (an exception's message, an
        HTTP status). It is surfaced in diagnostics, so callers must keep it
        free of anything sensitive — decoder endpoints carry no credentials,
        which is why the URL itself is safe to include.
        """
        consecutive = self._health.consecutive_failures + 1
        state = HealthState.DOWN if consecutive >= self._down_after else HealthState.DEGRADED
        return self._update(
            replace(
                self._health,
                state=state,
                consecutive_failures=consecutive,
                failures_since_success=self._health.failures_since_success + 1,
                total_failures=self._health.total_failures + 1,
                last_failure=self._now(),
                last_error=error,
                next_retry_delay_s=self.retry_delay_s(consecutive),
            )
        )

    def retry_delay_s(self, consecutive_failures: int | None = None) -> float:
        """Return the reconnect delay for a failure run, with equal jitter.

        The undelayed backoff is ``initial * factor ** (n - 1)`` capped at
        :data:`BACKOFF_MAX_S`; the returned value is half of that plus a
        uniform random share of the remaining half.
        """
        failures = (
            self._health.consecutive_failures
            if consecutive_failures is None
            else consecutive_failures
        )
        exponent = max(failures - 1, 0)
        # Cap the exponent before exponentiating: a long outage would otherwise
        # compute an enormous float only to clamp it away.
        capped_exponent = min(exponent, 32)
        delay = min(BACKOFF_INITIAL_S * BACKOFF_FACTOR**capped_exponent, BACKOFF_MAX_S)
        fixed = delay * (1.0 - BACKOFF_JITTER_RATIO)
        return fixed + self._rng.random() * (delay - fixed)

    def _update(self, health: AdapterHealth) -> AdapterHealth:
        previous = self._health.state
        self._health = health
        if previous is not health.state and self._on_transition is not None:
            self._on_transition(previous, health.state, health)
        return health


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "BACKOFF_FACTOR",
    "BACKOFF_INITIAL_S",
    "BACKOFF_JITTER_RATIO",
    "BACKOFF_MAX_S",
    "DOWN_AFTER_CONSECUTIVE_FAILURES",
    "AdapterHealth",
    "HealthState",
    "HealthTracker",
]
