"""``ReplayAdapter`` — plays a captured fixture back as a ``DecoderAdapter``.

Implements :class:`~flightsite.ingest.protocol.DecoderAdapter` (ADR-0003), so
anything that consumes a live decoder — the ingestion service, its
downstream consumers, the app wiring — can be pointed at a fixture instead
without knowing the difference. This is what makes replay usable both as a
developer convenience (reproduce a real-world bug without the hardware that
saw it) and as regression-test fuel (drive the ingestion pipeline from a
committed fixture instead of a live decoder or a hand-built document).

Pacing
------

Three modes, chosen by ``speed``:

* ``speed=1.0`` (the default) — real-time: batches are yielded with the same
  gaps they were recorded with.
* ``speed=2.0`` (or any other positive factor) — accelerated: recorded gaps
  are divided by the factor.
* ``speed=None`` — as-fast-as-possible: no waiting between batches at all,
  which is what tests want.

Health
------

There is no connection to lose, so health tracks playback state rather than
transport state: :attr:`~flightsite.ingest.health.HealthState.CONNECTED`
whenever a batch has been yielded and playback has not stopped, and
:attr:`~flightsite.ingest.health.HealthState.DOWN` before playback starts,
after :meth:`~ReplayAdapter.stop`, and at end-of-fixture — unless ``loop`` is
set, in which case end-of-fixture simply restarts the recording and health
stays ``connected``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import structlog

from flightsite.devtools.fixture import Fixture, read_fixture
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.ingest.types import AircraftStateBatch

logger = structlog.get_logger(__name__)


class ReplayAdapter:
    """Replays a :class:`~flightsite.devtools.fixture.Fixture` as a decoder.

    Args:
        fixture: the recording to play. Use :meth:`from_path` to load one
            from a ``.fsrec.gz`` file.
        speed: pacing factor (see module docstring). Must be positive, or
            ``None`` for as-fast-as-possible.
        loop: replay the fixture repeatedly instead of stopping at the end.
        sleep: awaited between batches; injectable so pacing tests run
            without real delay.
        now: clock used to timestamp health transitions; injectable for
            deterministic tests.
    """

    def __init__(
        self,
        fixture: Fixture,
        *,
        speed: float | None = 1.0,
        loop: bool = False,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if speed is not None and speed <= 0:
            raise ValueError("speed must be positive, or None for as-fast-as-possible")
        self._fixture = fixture
        self._speed = speed
        self._loop = loop
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._now = now if now is not None else _utc_now
        self._stopped = True
        self._health = AdapterHealth()

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        speed: float | None = 1.0,
        loop: bool = False,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> ReplayAdapter:
        """Load a fixture from ``path`` and build a replay adapter for it."""
        return cls(read_fixture(path), speed=speed, loop=loop, sleep=sleep, now=now)

    @property
    def fixture(self) -> Fixture:
        """The fixture being replayed."""
        return self._fixture

    async def start(self) -> None:
        """Mark playback ready to begin. Does not yield anything by itself."""
        self._stopped = False
        logger.info(
            "replay_adapter_started",
            source=self._fixture.header.source,
            batches=self._fixture.header.batch_count,
            loop=self._loop,
        )

    async def stop(self) -> None:
        """Stop playback. Idempotent."""
        self._stopped = True
        self._set_down()
        logger.info("replay_adapter_stopped")

    def health(self) -> AdapterHealth:
        """Return the current playback health snapshot."""
        return self._health

    async def updates(self) -> AsyncIterator[AircraftStateBatch]:
        """Yield the fixture's batches, paced by ``speed``, until exhausted or stopped."""
        if not self._fixture.records:
            self._set_down()
            return

        while not self._stopped:
            previous_t = 0.0
            for record in self._fixture.records:
                if self._stopped:
                    return
                if self._speed is not None:
                    gap = (record.relative_s - previous_t) / self._speed
                    if gap > 0:
                        await self._sleep(gap)
                previous_t = record.relative_s
                self._mark_connected()
                yield record.batch
            if not self._loop:
                break

        self._set_down()

    def _mark_connected(self) -> None:
        self._health = replace(
            self._health,
            state=HealthState.CONNECTED,
            consecutive_failures=0,
            failures_since_success=0,
            total_successes=self._health.total_successes + 1,
            last_success=self._now(),
            last_error=None,
            next_retry_delay_s=None,
        )

    def _set_down(self) -> None:
        self._health = replace(self._health, state=HealthState.DOWN)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = ["ReplayAdapter"]
