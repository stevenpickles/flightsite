"""Demo traffic must land inside the window the UI asks for (issue #107).

The bug this pins was not in either half on its own. The demo scenario stamped
every observation from a fixed epoch (2026-01-01) because that made runs
reproducible; ``today`` resolved against the real wall clock because that is
what "today" means. Both were reasonable, and together they guaranteed that a
demo install's Live Map Today panel and Analytics ``today`` preset read zero
forever — the two clocks could never meet.

So the assertion here is deliberately about the *join*: a batch the demo
adapter produces is checked against :func:`resolve_window`, the same resolver
:meth:`flightsite.api.context.ApiContext.analytics_window` funnels every §3.7
preset through. A unit test of either side alone would have passed throughout
the bug.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from flightsite.analytics.bucketing import Preset, local_day, resolve_window
from flightsite.db.clock import utc_now_ms
from flightsite.demo.adapter import DemoAdapter
from flightsite.demo.scenario import SCENARIO_EPOCH

#: A zone well away from UTC in both directions, so a test that only passes
#: because "today" happens to agree with the UTC day fails here.
ZONES = (ZoneInfo("UTC"), ZoneInfo("Pacific/Auckland"), ZoneInfo("America/Los_Angeles"))


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def test_the_default_epoch_is_now_not_the_scenario_constant() -> None:
    """The scenario constant remains the default for a *direct* ``batch_at``."""
    adapter = DemoAdapter(seed=42, population=10)

    assert adapter.epoch != SCENARIO_EPOCH
    assert abs((datetime.now(UTC) - adapter.epoch).total_seconds()) < 60


@pytest.mark.parametrize("zone", ZONES, ids=[str(zone) for zone in ZONES])
def test_demo_observations_fall_inside_the_today_window(zone: ZoneInfo) -> None:
    """The acceptance criterion, stated against the real window resolver.

    ``resolve_window`` ends the window at ``now``, so a batch is compared
    against a window resolved from that same batch's instant — which is what
    the API does on every request while a demo stack is running.
    """
    adapter = DemoAdapter(seed=42, population=60)

    batch = adapter.batch_for_tick(0)
    now_ms = _to_ms(batch.timestamp)
    window = resolve_window(Preset.TODAY, now_ms=now_ms, zone=zone)

    assert window.start_ms <= now_ms <= window.end_ms
    assert local_day(now_ms, zone) == window.first_day
    assert batch.updates, "a tick with no aircraft would prove nothing"


@pytest.mark.parametrize("zone", ZONES, ids=[str(zone) for zone in ZONES])
def test_the_old_fixed_epoch_would_not_have(zone: ZoneInfo) -> None:
    """The bug itself, pinned so the fix cannot be quietly reverted.

    Without this, restoring the constant epoch would leave every other test in
    this module passing on a technicality — they would still be comparing a
    batch against a window resolved from that batch's own instant.
    """
    adapter = DemoAdapter(seed=42, population=60, epoch=SCENARIO_EPOCH)

    batch_ms = _to_ms(adapter.batch_for_tick(0).timestamp)
    window = resolve_window(Preset.TODAY, now_ms=utc_now_ms(), zone=zone)

    assert batch_ms < window.start_ms


def test_an_hour_of_scenario_time_stays_within_the_day_it_started_in() -> None:
    """Ticks advance one second each, so a session does not outrun its day.

    Worth stating because the epoch is now "now" rather than a local midnight:
    a stack started just before midnight rolls into tomorrow, which is correct
    — the same thing a real receiver does — and a stack started at any other
    hour stays put for far longer than a demo session lasts.
    """
    started = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    adapter = DemoAdapter(seed=42, population=10, epoch=started)

    an_hour_in = adapter.batch_for_tick(3600).timestamp

    utc = ZoneInfo("UTC")
    assert an_hour_in == started + timedelta(hours=1)
    assert local_day(_to_ms(an_hour_in), utc) == local_day(_to_ms(started), utc)
