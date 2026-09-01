"""Activity feed and milestones — SPEC §54/§55, ``docs/DATA_MODEL.md`` §5.

The package answers one question, *"what happened while I wasn't watching?"*,
in four layers that never reach past each other:

* :mod:`flightsite.activity.model` — the event vocabulary, the value types, and
  the dedupe keys that make recording an event exactly-once.
* :mod:`flightsite.activity.facts` — what a detection pass observed, as plain
  values.
* :mod:`flightsite.activity.producers` — pure functions from those facts to the
  events and milestones they justify, and nothing more.
* :mod:`flightsite.activity.repository` and
  :mod:`flightsite.activity.service` — the SQL, and the task that runs it.
"""

from __future__ import annotations

from flightsite.activity.facts import (
    AlertMatchFact,
    HealthEpisode,
    ImportOutcome,
    LongestSighting,
    MilitaryFirst,
    ReceiverRecords,
    SightingObservation,
)
from flightsite.activity.model import (
    MILESTONE_FIRST_MILITARY,
    UNIQUE_AIRCRAFT_THRESHOLDS,
    ActivityBatch,
    ActivityEventType,
    NewActivityEvent,
    NewMilestone,
    RecordKind,
    Severity,
    StoredActivityEvent,
)
from flightsite.activity.repository import (
    DEFAULT_SCAN_LIMIT,
    SCAN_WATERMARK_KEY,
    ActivityRepository,
)
from flightsite.activity.service import (
    DEFAULT_FLUSH_INTERVAL_S,
    DEFAULT_OFFLINE_DEBOUNCE_S,
    ActivityListener,
    ActivityService,
    HealthProbe,
    PassResult,
)

__all__ = [
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_OFFLINE_DEBOUNCE_S",
    "DEFAULT_SCAN_LIMIT",
    "MILESTONE_FIRST_MILITARY",
    "SCAN_WATERMARK_KEY",
    "UNIQUE_AIRCRAFT_THRESHOLDS",
    "ActivityBatch",
    "ActivityEventType",
    "ActivityListener",
    "ActivityRepository",
    "ActivityService",
    "AlertMatchFact",
    "HealthEpisode",
    "HealthProbe",
    "ImportOutcome",
    "LongestSighting",
    "MilitaryFirst",
    "NewActivityEvent",
    "NewMilestone",
    "PassResult",
    "ReceiverRecords",
    "RecordKind",
    "Severity",
    "SightingObservation",
    "StoredActivityEvent",
]
