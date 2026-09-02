"""``DemoAdapter`` — a deterministic, in-process ``DecoderAdapter`` (SPEC §76).

Implements the seam :mod:`flightsite.ingest.protocol` draws (ADR-0003): the
live store, sightings, alerts and analytics consume this exactly like a
polled readsb decoder, and never know the difference. There is no decoder to
lose, so :meth:`DemoAdapter.health` reports ``connected`` from the first
batch onward — that is the truthful state for a simulation, and it is what
lets the health endpoint show a healthy decoder with no hardware attached
(SPEC §76: "demo mode runs the full stack with no decoder and no internet").

All the scenario content lives in :mod:`flightsite.demo.roster` (who flies)
and :mod:`flightsite.demo.scenario` (what they are doing at any tick); this
module is only the ``DecoderAdapter`` plumbing around
:func:`~flightsite.demo.scenario.batch_at` — turning elapsed clock time into
a tick index and yielding the batch that tick produces.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

import structlog

from flightsite.demo.roster import AircraftProfile, build_roster
from flightsite.demo.scenario import batch_at
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.ingest.types import AircraftStateBatch, Position

logger = structlog.get_logger(__name__)

#: A busy central-US airspace crossroads, chosen only because it puts a
#: realistic amount of overflying traffic within a few hundred nm of some
#: point — not tied to any real receiver. Used when demo mode is active and
#: no receiver location has been configured (SPEC §76: demo mode works with
#: zero configuration).
DEFAULT_CENTER: Final = Position(latitude=39.8283, longitude=-98.5795)

#: Arbitrary but fixed: what matters for determinism is that it never
#: changes, not what it is.
DEFAULT_SEED: Final = 20260831

#: Target concurrent aircraft count — roadmap slice 011: "~40-80 concurrent".
DEFAULT_POPULATION: Final = 60

#: The product's 1 Hz decoder cadence.
TICK_INTERVAL_S: Final = 1.0


class DemoAdapter:
    """Deterministic simulated decoder traffic (SPEC §76, ADR-0003).

    Every batch is computed by :func:`flightsite.demo.scenario.batch_at` from
    the roster built at construction time and the *elapsed* tick index alone
    — nothing about a previous tick is remembered. Two adapters built with
    the same ``seed`` and the same ``epoch`` therefore produce identical
    batches for the same tick index, and the same adapter re-asked for an old
    tick gets the same answer back (roadmap acceptance criterion: "two runs
    with the same seed produce identical update sequences").

    Why the epoch defaults to the wall clock
    ----------------------------------------

    These timestamps are not decoration: a decoder is the authority on when an
    observation happened (:mod:`flightsite.live.aircraft`), so they become the
    ``first_seen``/``last_seen`` on ``aircraft`` and the ``started_ms`` on
    ``sightings``, and from there the day every analytics rollup buckets into.
    Anchored to :data:`~flightsite.demo.scenario.SCENARIO_EPOCH` they all
    landed on 2026-01-01, while the ``today`` window, the analytics rollup
    writer and the receiver-metrics service every one resolve against the real
    clock — so on a demo stack the Live Map Today panel and the Analytics
    ``today`` preset were empty, permanently and by construction (issue #107).

    Anchoring the scenario to "now" is the smaller of the two available fixes.
    The alternative — teaching the API to resolve ``today`` against a scenario
    clock when demo mode is on — would have to change every wall-clock read on
    the analytics path *and* the rollup writer, so that reader and writer agree
    on which day is "today"; and it could not fix the split anyway, because
    :mod:`flightsite.receiver_metrics` stamps its own rows from the real clock,
    which ``/analytics/summary`` reads alongside the sighting counts. That
    trades one inconsistency for a subtler one and spreads demo-awareness
    across the whole analytics stack. Moving the anchor puts every one of those
    subsystems back on a single clock and keeps the knowledge of demo mode
    inside this package.

    Determinism is unaffected: the epoch is an argument, and shifting it moves
    every timestamp by the same constant without changing which aircraft do
    what on which tick. Tests that compare two adapters pass an explicit epoch.

    Args:
        seed: seeds every random decision in the roster (aircraft identity,
            callsigns, flight parameters). The same seed always builds the
            same roster.
        population: target concurrent aircraft count; see
            :mod:`flightsite.demo.roster` for how the roster is sized from
            it. Scales from a handful up to several hundred for perf work.
        center: the point cruise and local traffic is generated around —
            normally the configured receiver location. Defaults to
            :data:`DEFAULT_CENTER` so demo mode works with no configuration
            at all.
        clock: monotonic seconds source the tick index is derived from;
            injectable so tests can drive many simulated ticks without real
            delay. Defaults to :func:`time.monotonic`.
        sleep: awaited between polls; injectable for the same reason.
        tick_interval_s: simulated seconds per tick — the 1 Hz product
            cadence by default.
        epoch: the instant tick 0 is stamped at. Defaults to now, truncated to
            the second, for the reason above; pass an explicit value to make a
            scenario reproducible across processes.
    """

    def __init__(
        self,
        *,
        seed: int = DEFAULT_SEED,
        population: int = DEFAULT_POPULATION,
        center: Position | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        tick_interval_s: float = TICK_INTERVAL_S,
        epoch: datetime | None = None,
    ) -> None:
        if tick_interval_s <= 0.0:
            raise ValueError("tick_interval_s must be greater than zero")
        # Truncated to the second so a demo stream looks like the 1 Hz decoder
        # it is imitating rather than carrying a startup microsecond forever.
        self._epoch = epoch if epoch is not None else datetime.now(UTC).replace(microsecond=0)
        self._seed = seed
        self._center = center if center is not None else DEFAULT_CENTER
        self._roster: tuple[AircraftProfile, ...] = build_roster(
            seed=seed, population=population, center=self._center
        )
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._tick_interval_s = tick_interval_s
        self._stopped = True
        self._start_clock = 0.0
        self._health = AdapterHealth()

    @property
    def seed(self) -> int:
        """The seed the roster was built from."""
        return self._seed

    @property
    def center(self) -> Position:
        """The point traffic is generated around."""
        return self._center

    @property
    def roster(self) -> tuple[AircraftProfile, ...]:
        """The deterministic aircraft roster this session is driving."""
        return self._roster

    @property
    def epoch(self) -> datetime:
        """The instant tick 0 is stamped at."""
        return self._epoch

    def batch_for_tick(self, tick_index: int) -> AircraftStateBatch:
        """The batch at ``tick_index`` — pure in ``(seed, tick_index, epoch)``.

        Exposed directly (not only through :meth:`updates`) so determinism
        and scenario-coverage tests can drive many ticks instantly, without
        running the async loop or a clock at all.
        """
        return batch_at(self._roster, tick_index, epoch=self._epoch)

    async def start(self) -> None:
        """Mark the scenario clock started. Does not yield anything by itself."""
        self._stopped = False
        self._start_clock = self._clock()
        logger.info(
            "demo_adapter_started",
            seed=self._seed,
            population=len(self._roster),
            center_lat=self._center.latitude,
            center_lon=self._center.longitude,
        )

    async def stop(self) -> None:
        """Stop the scenario. Idempotent."""
        self._stopped = True
        self._health = replace(self._health, state=HealthState.DOWN)
        logger.info("demo_adapter_stopped")

    def health(self) -> AdapterHealth:
        """Return the current (always-connected-once-started) health snapshot."""
        return self._health

    async def updates(self) -> AsyncIterator[AircraftStateBatch]:
        """Yield one batch per elapsed tick until stopped.

        The tick index is derived from ``clock() - start_clock``, not from a
        loop counter: a slow consumer that misses a tick's real-time window
        simply sees the scenario jump forward to the tick that elapsed time
        now maps to — the same way a real decoder poll would, and still an
        exact function of ``(seed, tick_index)`` for whatever tick is served.
        """
        last_tick_index = -1
        while not self._stopped:
            elapsed = max(0.0, self._clock() - self._start_clock)
            tick_index = int(elapsed / self._tick_interval_s)
            if tick_index != last_tick_index:
                last_tick_index = tick_index
                self._mark_connected()
                yield self.batch_for_tick(tick_index)
            await self._sleep(self._tick_interval_s)

    def _mark_connected(self) -> None:
        self._health = replace(
            self._health,
            state=HealthState.CONNECTED,
            consecutive_failures=0,
            failures_since_success=0,
            total_successes=self._health.total_successes + 1,
            last_success=datetime.now(UTC),
            last_error=None,
            next_retry_delay_s=None,
        )


__all__ = [
    "DEFAULT_CENTER",
    "DEFAULT_POPULATION",
    "DEFAULT_SEED",
    "TICK_INTERVAL_S",
    "DemoAdapter",
]
