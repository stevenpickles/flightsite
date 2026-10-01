"""A scripted decoder outage for the receiver self-alerts (SPEC §76, slice 088).

Demo mode's decoder is a simulation that cannot fail
(:class:`~flightsite.demo.DemoAdapter`), which would leave the self-alert
path — raise, notification, restore — with nothing to show on the demo stack.
So, in the same spirit as the FR24 outage :mod:`flightsite.demo.feeders`
scripts for the Feeders page, the self-alert monitor's view of the decoder
drops out for :data:`DECODER_OUTAGE_S` seconds of every
:data:`DECODER_CYCLE_S`, starting :data:`DECODER_OUTAGE_START_S` into the
cycle. With the default five-minute threshold that is exactly one
``self_alert_raised`` and one ``self_alert_restored`` — and one browser
notification of each — per hour.

**Only the self-alert monitor sees it.** The wrapper is handed to
:class:`~flightsite.alerts.self_alerts.SelfAlertMonitor` alone; the demo
traffic keeps flowing, and the Health page's decoder card, the activity feed's
``receiver_offline`` and the live map all keep reading the adapter's real,
healthy state. A demo whose aircraft vanished for seven minutes an hour would
break every other walkthrough and e2e flow for the sake of this one.

Like the rest of the demo, the schedule is a pure function of the wall clock,
so two processes agree about whether the outage is on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Final

from flightsite.db.clock import MS_PER_SECOND, utc_now_ms
from flightsite.ingest.health import (
    DOWN_AFTER_CONSECUTIVE_FAILURES,
    AdapterHealth,
    HealthState,
)

#: Length of the scripted outage — longer than the default five-minute
#: ``self_alerts.decoder_down_minutes``, so it raises, and short enough to end
#: well inside the cycle.
DECODER_OUTAGE_S: Final = 420

#: The outage recurs once per this many seconds.
DECODER_CYCLE_S: Final = 3_600

#: Offset of the outage into each cycle: half past the hour, clear of the
#: FR24 outage at the top of every twenty minutes.
DECODER_OUTAGE_START_S: Final = 1_800

#: The reason the scripted outage reports, so nobody mistakes it for a fault.
DEMO_OUTAGE_ERROR: Final = "Scripted demo outage"

HealthProbe = Callable[[], AdapterHealth | None]


def decoder_outage(now_ms: int) -> bool:
    """Whether the scripted decoder outage is in progress at ``now_ms``."""
    offset = (now_ms // MS_PER_SECOND) % DECODER_CYCLE_S
    return DECODER_OUTAGE_START_S <= offset < DECODER_OUTAGE_START_S + DECODER_OUTAGE_S


def scripted_decoder_health(
    probe: HealthProbe, *, clock: Callable[[], int] = utc_now_ms
) -> HealthProbe:
    """Wrap ``probe`` so it reads ``down`` during the scripted outage.

    Outside the outage the real reading passes through untouched; a probe
    that has nothing to report (``None``, before ingestion has started) stays
    ``None`` either way.
    """

    def scripted() -> AdapterHealth | None:
        health = probe()
        if health is None or not decoder_outage(clock()):
            return health
        return replace(
            health,
            state=HealthState.DOWN,
            consecutive_failures=max(health.consecutive_failures, DOWN_AFTER_CONSECUTIVE_FAILURES),
            last_error=DEMO_OUTAGE_ERROR,
        )

    return scripted


__all__ = [
    "DECODER_CYCLE_S",
    "DECODER_OUTAGE_S",
    "DECODER_OUTAGE_START_S",
    "DEMO_OUTAGE_ERROR",
    "decoder_outage",
    "scripted_decoder_health",
]
