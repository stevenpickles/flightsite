"""The hour-of-week message-rate baseline — slice 088's "what is normal now?".

A receiver's message rate is not one number. Traffic follows the week: a
Tuesday 03:00 is a fraction of a Friday 17:00, and a rate that would be a
collapse at five in the afternoon is simply night at three in the morning. So
the self-alert that asks *"has the message rate collapsed?"*
(:mod:`flightsite.alerts.self_alerts`) compares a sample against **the same
hour of the same weekday** in the weeks before it, never against a daily or
global average — which is the roadmap's acceptance criterion *"a quiet night
hour does not trip the rate alert when it matches that hour's baseline"*
stated as a data structure.

Where the numbers come from
---------------------------

``receiver_metrics_hourly`` (``docs/DATA_MODEL.md`` §6.2), which ADR-0009
keeps indefinitely and slice 033 already maintains. Each row's
``msgs_per_sec_avg`` is that hour's mean message rate; this module reads the
last :data:`BASELINE_WEEKS` weeks of rows, keeps the ones whose hour falls on
the same weekday and hour as *now*, and takes their **median**. The median
rather than the mean because the history it summarizes includes the very
outages this baseline exists to detect: one week with a dead antenna drags a
mean down by an eighth and leaves a median where it was.

Which "hour of the week"
------------------------

The receiver's local one (``docs/DATA_MODEL.md`` §10), resolved from the live
timezone setting, because traffic follows local life rather than UTC. Hourly
rows are keyed on a UTC hour boundary, so a row's hour-of-week is the local
weekday and hour *of its start*; the current sample is classified the same way
(by the start of the UTC hour it falls in), so the comparison is like for like
even in a zone whose offset is not a whole number of hours. A DST change moves
one hour's comparison by an hour, twice a year — well inside the slack the
threshold share already gives.

When there is no baseline
-------------------------

Three states, and only one of them lets the condition fire:

* :attr:`BaselineState.READY` — at least :data:`MIN_BASELINE_WEEKS` weeks of
  this hour, each with at least :data:`MIN_BUCKET_SAMPLES` samples behind it.
* :attr:`BaselineState.LEARNING` — fewer weeks than that. A new install, or a
  receiver that has only recently started keeping this hour. The condition
  stays silent: comparing against one week is comparing against an anecdote.
* :attr:`BaselineState.QUIET` — enough weeks, but a median below
  :data:`MIN_BASELINE_MSGS_PER_SEC`. An hour this empty has no "collapse" to
  detect — its normal is a handful of messages from one distant aircraft,
  and 40 % of almost nothing is a threshold the next quiet minute crosses.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from flightsite.db.clock import MS_PER_SECOND
from flightsite.receiver_metrics.aggregate import MS_PER_HOUR, hour_start_ms
from flightsite.receiver_metrics.model import MetricSummary
from flightsite.receiver_metrics.repository import MetricsRepository

#: How many weeks of history the baseline is drawn from. Eight: enough that a
#: median is a median, recent enough that a receiver whose antenna was moved
#: two months ago is compared against the antenna it has now.
BASELINE_WEEKS: Final = 8

#: Weeks of this hour needed before the baseline is trusted (the "learning"
#: state below it). Two is the least that is not a single anecdote.
MIN_BASELINE_WEEKS: Final = 2

#: Samples an hourly row needs to count towards the baseline — half an hour at
#: the 15-second cadence. An hour the process was only up for five minutes of
#: is a sample of five minutes, not of the hour.
MIN_BUCKET_SAMPLES: Final = 120

#: Below this median rate an hour is "quiet" and never evaluated (see the
#: module docstring).
MIN_BASELINE_MSGS_PER_SEC: Final = 1.0

MS_PER_WEEK: Final = 7 * 24 * MS_PER_HOUR
HOURS_PER_WEEK: Final = 7 * 24


class BaselineState(StrEnum):
    """Whether a baseline exists that a sample may be judged against."""

    READY = "ready"
    LEARNING = "learning"
    QUIET = "quiet"


@dataclass(frozen=True, slots=True)
class RateBaseline:
    """The message-rate baseline for one hour of the week.

    ``msgs_per_sec`` is the median over :attr:`weeks` hourly rows, and is
    reported in every state (``None`` only when there are no rows at all), so
    diagnostics can show a learning baseline's figure while the condition
    ignores it.
    """

    #: ``weekday * 24 + hour`` in the receiver's zone, Monday 00:00 = 0.
    hour_of_week: int
    state: BaselineState
    msgs_per_sec: float | None = None
    #: How many weekly rows the median is drawn from.
    weeks: int = 0

    @property
    def ready(self) -> bool:
        """True when a sample may be judged against this baseline."""
        return self.state is BaselineState.READY


def hour_of_week(ts_ms: int, zone: ZoneInfo) -> int:
    """``weekday * 24 + hour`` of the UTC hour ``ts_ms`` falls in, locally.

    Classified by the start of the UTC hour rather than by the instant itself,
    so a sample and the hourly row it will be folded into always agree — see
    "Which hour of the week" above.
    """
    local = datetime.fromtimestamp(hour_start_ms(ts_ms) / MS_PER_SECOND, zone)
    return local.weekday() * 24 + local.hour


def rate_baseline(
    hours: Mapping[int, MetricSummary],
    *,
    at_ms: int,
    zone: ZoneInfo,
    min_weeks: int = MIN_BASELINE_WEEKS,
    min_samples: int = MIN_BUCKET_SAMPLES,
    min_rate: float = MIN_BASELINE_MSGS_PER_SEC,
) -> RateBaseline:
    """The baseline for the hour of the week ``at_ms`` falls in.

    Pure: ``hours`` is whatever window of ``receiver_metrics_hourly`` the
    caller read, keyed by UTC hour start. Rows from the current hour itself —
    this week's, still being written — are excluded, so the baseline never
    includes the rate it is about to judge.
    """
    target = hour_of_week(at_ms, zone)
    current_hour = hour_start_ms(at_ms)
    values = [
        summary.msgs_per_sec_avg
        for start, summary in hours.items()
        if start < current_hour
        and summary.msgs_per_sec_avg is not None
        and summary.sample_count >= min_samples
        and hour_of_week(start, zone) == target
    ]
    if not values:
        return RateBaseline(hour_of_week=target, state=BaselineState.LEARNING)
    median = float(statistics.median(values))
    if len(values) < min_weeks:
        state = BaselineState.LEARNING
    elif median < min_rate:
        state = BaselineState.QUIET
    else:
        state = BaselineState.READY
    return RateBaseline(hour_of_week=target, state=state, msgs_per_sec=median, weeks=len(values))


async def load_rate_baseline(
    repository: MetricsRepository,
    *,
    at_ms: int,
    zone: ZoneInfo,
    weeks: int = BASELINE_WEEKS,
) -> RateBaseline:
    """Read the last ``weeks`` weeks of hourly rows and compute the baseline.

    One indexed range read of at most ``weeks * 168`` rows. The caller caches
    the answer per hour, so this runs once an hour rather than once a sample.
    """
    current_hour = hour_start_ms(at_ms)
    rows = await repository.hourly_between(current_hour - weeks * MS_PER_WEEK, current_hour)
    return rate_baseline(rows, at_ms=at_ms, zone=zone)


__all__ = [
    "BASELINE_WEEKS",
    "HOURS_PER_WEEK",
    "MIN_BASELINE_MSGS_PER_SEC",
    "MIN_BASELINE_WEEKS",
    "MIN_BUCKET_SAMPLES",
    "MS_PER_WEEK",
    "BaselineState",
    "RateBaseline",
    "hour_of_week",
    "load_rate_baseline",
    "rate_baseline",
]
