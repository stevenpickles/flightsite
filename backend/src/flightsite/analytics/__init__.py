"""Analytics: the ``docs/DATA_MODEL.md`` §6.5 daily rollups and their API.

Four moving parts, and the seam between them is a pure function:

* :mod:`~flightsite.analytics.bucketing` — receiver-local day arithmetic and
  ``docs/API.md`` §3.7's presets, DST-correct by construction (§10).
* :mod:`~flightsite.analytics.rollup` — the fold from a day's sightings to the
  row §6.5 stores. No database, no clock; property-tested against brute force.
* :mod:`~flightsite.analytics.backfill` — rebuild any day from ground truth.
  Called both by the incremental maintainer and by the startup repair, which is
  why the two cannot disagree.
* :mod:`~flightsite.analytics.service` — the lifespan-managed maintainer,
  driven by the persistence worker's sighting-lifecycle seam.

:mod:`~flightsite.analytics.repository` holds the maintenance SQL and
:mod:`~flightsite.analytics.queries` the read SQL the API serves.
"""

from __future__ import annotations

from flightsite.analytics.backfill import (
    DEFAULT_MAX_BACKFILL_DAYS,
    AnalyticsBackfill,
    BackfillResult,
)
from flightsite.analytics.bucketing import (
    MAX_WINDOW_DAYS,
    Preset,
    Window,
    day_bounds_ms,
    day_start_ms,
    days_in_range,
    explicit_window,
    local_day,
    local_hour,
    resolve_window,
)
from flightsite.analytics.model import DayRollup, GroupCount, SightingFact, TypeStat
from flightsite.analytics.queries import (
    DEFAULT_RARE_MAX_SIGHTINGS,
    DEFAULT_TOP_LIMIT,
    MAX_TOP_LIMIT,
    AircraftRank,
    AnalyticsQueries,
    ClassificationActivity,
    DailyRow,
    GroupRank,
    RareType,
    Rarity,
    Summary,
)
from flightsite.analytics.repository import META_KEY_ROLLUP_THROUGH_DAY, AnalyticsRepository
from flightsite.analytics.rollup import busiest_hour, fold_day
from flightsite.analytics.service import (
    DEFAULT_FLUSH_INTERVAL_S,
    AnalyticsService,
    FlushResult,
)

__all__ = [
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_MAX_BACKFILL_DAYS",
    "DEFAULT_RARE_MAX_SIGHTINGS",
    "DEFAULT_TOP_LIMIT",
    "MAX_TOP_LIMIT",
    "MAX_WINDOW_DAYS",
    "META_KEY_ROLLUP_THROUGH_DAY",
    "AircraftRank",
    "AnalyticsBackfill",
    "AnalyticsQueries",
    "AnalyticsRepository",
    "AnalyticsService",
    "BackfillResult",
    "ClassificationActivity",
    "DailyRow",
    "DayRollup",
    "FlushResult",
    "GroupCount",
    "GroupRank",
    "Preset",
    "RareType",
    "Rarity",
    "SightingFact",
    "Summary",
    "TypeStat",
    "Window",
    "busiest_hour",
    "day_bounds_ms",
    "day_start_ms",
    "days_in_range",
    "explicit_window",
    "fold_day",
    "local_day",
    "local_hour",
    "resolve_window",
]
