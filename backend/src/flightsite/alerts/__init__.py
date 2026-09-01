"""Interesting-aircraft alerting: rules, built-ins, evaluation (SPEC §43 to §48).

Reading order:

* :mod:`~flightsite.alerts.vocabulary` — the severity ladder and its ordering,
  and the built-in emergency detectors' keys.
* :mod:`~flightsite.alerts.model` — the conditions document, the rule record,
  the evaluation subject, and what a match says.
* :mod:`~flightsite.alerts.builtins` — SPEC §47's emergency squawks, which are
  evaluated always and cannot be configured away.
* :mod:`~flightsite.alerts.evaluator` — the pure function from a subject and a
  rule set to the matches they justify.
* :mod:`~flightsite.alerts.templates` — SPEC §45's shipped templates, as inert
  data.
* :mod:`~flightsite.alerts.repository` — every SQL statement.
* :mod:`~flightsite.alerts.engine` — the incremental evaluation task, the
  per-sighting dedupe, and the downstream writes a match implies.
* :mod:`~flightsite.alerts.service` — the one object the application wires up:
  rule CRUD, template instantiation, and the engine they configure.

The dependency direction is worth stating because it is what keeps this package
addable rather than invasive: alerts *consume* the live store, the metadata
cache, the watchlist matcher, the persistence worker and the activity feed, and
none of those five knows this package exists. The two seams that reach back into
another package —
:meth:`~flightsite.sightings.worker.PersistenceWorker.apply_alert_severity` and
:meth:`~flightsite.activity.service.ActivityService.record_alert_matches` —
were both defined by the packages that own the data they write, in the shape
those packages already used for route enrichment and for import outcomes.

Out of scope here (roadmap slice 038's ``out_of_scope``): notification delivery
(slice 040), the visual rule builder (slice 041), and nested boolean expression
trees, which SPEC §43 rules out of v1 entirely.
"""

from __future__ import annotations

from flightsite.alerts.builtins import emergency_match, emergency_reason
from flightsite.alerts.engine import (
    AircraftAlertState,
    AlertEngine,
    AlertListener,
    CycleResult,
    subject_for,
)
from flightsite.alerts.errors import (
    AlertError,
    AlertRuleNotFoundError,
    AlertRuleValueError,
)
from flightsite.alerts.evaluator import evaluate, matches
from flightsite.alerts.model import (
    CONDITIONS_VERSION,
    AlertRuleRecord,
    AlertSubject,
    ClassificationCondition,
    CompiledRule,
    InterestingState,
    MatchProposal,
    RarityCondition,
    RuleConditions,
    StoredAlertMatch,
)
from flightsite.alerts.repository import AlertRepository, NewAlertMatch
from flightsite.alerts.schemas import AlertRuleWriteRequest
from flightsite.alerts.service import AlertRadiusProbe, AlertService
from flightsite.alerts.templates import (
    SHIPPED_TEMPLATES,
    TEMPLATES_BY_KEY,
    AlertTemplate,
    enabled_templates,
    unknown_template_keys,
)
from flightsite.alerts.vocabulary import (
    EMERGENCY_BUILTIN_KEYS,
    EMERGENCY_MEANINGS,
    EMERGENCY_SEVERITY,
    AlertSeverity,
    emergency_builtin_key,
)

__all__ = [
    "CONDITIONS_VERSION",
    "EMERGENCY_BUILTIN_KEYS",
    "EMERGENCY_MEANINGS",
    "EMERGENCY_SEVERITY",
    "SHIPPED_TEMPLATES",
    "TEMPLATES_BY_KEY",
    "AircraftAlertState",
    "AlertEngine",
    "AlertError",
    "AlertListener",
    "AlertRadiusProbe",
    "AlertRepository",
    "AlertRuleNotFoundError",
    "AlertRuleRecord",
    "AlertRuleValueError",
    "AlertRuleWriteRequest",
    "AlertService",
    "AlertSeverity",
    "AlertSubject",
    "AlertTemplate",
    "ClassificationCondition",
    "CompiledRule",
    "CycleResult",
    "InterestingState",
    "MatchProposal",
    "NewAlertMatch",
    "RarityCondition",
    "RuleConditions",
    "StoredAlertMatch",
    "emergency_builtin_key",
    "emergency_match",
    "emergency_reason",
    "enabled_templates",
    "evaluate",
    "matches",
    "subject_for",
    "unknown_template_keys",
]
