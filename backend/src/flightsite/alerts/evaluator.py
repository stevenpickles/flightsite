"""The rule evaluator: a subject and a rule set in, the matches out.

Pure by construction — no session, no clock, no configuration beyond the alert
radius it is told — so the roadmap's headline criterion for this slice, *"each
condition type + AND combinations verified"*, is checked as a table of cases
against a function rather than as behaviour of a running service. That is the
same split :mod:`flightsite.classification.engine` and
:mod:`flightsite.analytics.rollup` take, and it is what makes a
critical-coverage domain (SPEC §84) reviewable as data.

How a condition answers "unknown"
---------------------------------

Every condition is a *requirement*, so an unknown input fails it. An aircraft
whose distance FlightSite cannot compute does not satisfy "within 50 nm"; one
with no resolved type does not satisfy "type C17"; one the metadata cache has
not reached yet satisfies no classification condition. This is
``docs/API.md`` §2.7 applied to a predicate: unknown is not a quiet yes.

The consequence is that a rule can only fire once the facts it needs have
arrived, and the engine handles that by re-evaluating an aircraft whose
metadata was still unresolved (see :mod:`flightsite.alerts.engine`) rather than
by letting this function guess.

The two bounds that are not conditions
--------------------------------------

Ground state and the configured alert radius are applied here, before any
condition is examined, because neither is something a user writes into a rule:

* **Ground traffic** is excluded unless the rule opts in
  (``applies_on_ground``, SPEC §40). Applying it as a gate rather than as an
  implicit ``max_alt``-style condition is what makes the opt-in mean exactly
  one thing.
* **The alert radius** (``alert_radius_nm``, SPEC §66) bounds *every* rule when
  it is configured, because §66 makes it a property of the installation rather
  than of a rule. An aircraft whose distance is unknown is **not** excluded by
  it: FlightSite cannot place it, so it cannot place it outside — and §66's
  own instruction is not to discard what the receiver actually sees.

Built-in emergency matches bypass both gates and this function entirely; see
:mod:`flightsite.alerts.builtins`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from flightsite.alerts.builtins import emergency_match
from flightsite.alerts.model import (
    AlertSubject,
    ClassificationCondition,
    CompiledRule,
    MatchProposal,
    RuleConditions,
)
from flightsite.classification.model import Classification


def _classification_holds(
    condition: ClassificationCondition, classification: Classification
) -> bool:
    """Whether every claim the condition requires is actually asserted."""
    if condition.military and not classification.military:
        return False
    if condition.government and not classification.government:
        return False
    if condition.law_enforcement and not classification.law_enforcement:
        return False
    return not (condition.mission is not None and classification.mission is not condition.mission)


def _watchlist_holds(
    conditions: RuleConditions, rule: CompiledRule, matched: Sequence[str]
) -> bool:
    """Whether the watchlist conditions hold for this aircraft's matches."""
    if conditions.watchlist_any and not matched:
        return False
    if conditions.watchlist_id is None:
        return True
    # An id that resolved to no watchlist can never hold — see CompiledRule.
    return rule.watchlist_name is not None and rule.watchlist_name in matched


def _distance_holds(conditions: RuleConditions, distance_nm: float | None) -> bool:
    """Whether the distance window holds. An unknown distance holds neither bound."""
    if conditions.max_distance_nm is None and conditions.min_distance_nm is None:
        return True
    if distance_nm is None:
        return False
    if conditions.max_distance_nm is not None and distance_nm > conditions.max_distance_nm:
        return False
    return not (conditions.min_distance_nm is not None and distance_nm < conditions.min_distance_nm)


def _altitude_holds(conditions: RuleConditions, altitude_ft: float | None) -> bool:
    """Whether the altitude window holds. Barometric altitude, per SPEC §57.

    An aircraft the decoder reports on the ground has no barometric altitude
    (:mod:`flightsite.live.aircraft` clears it), so an altitude condition
    cannot hold for one — which is consistent with the ground gate that
    normally excludes it anyway.
    """
    if conditions.max_alt_ft is None and conditions.min_alt_ft is None:
        return True
    if altitude_ft is None:
        return False
    if conditions.max_alt_ft is not None and altitude_ft > conditions.max_alt_ft:
        return False
    return not (conditions.min_alt_ft is not None and altitude_ft < conditions.min_alt_ft)


def _rarity_holds(conditions: RuleConditions, subject: AlertSubject) -> bool:
    """Whether both rarity thresholds hold (SPEC §44).

    Both are *at or below*, matching slice 031's ``GET
    /api/v1/analytics/rarity`` exactly — see
    :class:`~flightsite.alerts.model.RarityCondition` for why the two surfaces
    must not use different inequalities.
    """
    rare_aircraft = conditions.rare_aircraft
    if rare_aircraft is not None and subject.sightings_here > rare_aircraft.max_sightings:
        return False
    rare_type = conditions.rare_type
    if rare_type is None:
        return True
    # No resolved type means the question has no answer, and an unanswered
    # requirement fails — the same rule every other condition follows.
    here = subject.type_aircraft_here
    return here is not None and here <= rare_type.max_sightings


def matches(rule: CompiledRule, subject: AlertSubject, *, alert_radius_nm: float | None) -> bool:
    """Whether ``rule`` matches ``subject``. Every condition must hold (SPEC §43).

    Args:
        rule: the compiled rule, whose ``watchlist_id`` condition (if any) has
            already been resolved to a name.
        subject: the in-memory facts about one live aircraft.
        alert_radius_nm: the installation's configured alert radius, or
            ``None`` for unlimited (SPEC §66).
    """
    record = rule.rule
    if not record.enabled:
        return False
    conditions = record.conditions
    if subject.on_ground and not conditions.applies_on_ground:
        return False
    if (
        alert_radius_nm is not None
        and subject.distance_nm is not None
        and subject.distance_nm > alert_radius_nm
    ):
        return False

    classification = conditions.classification
    if classification is not None and not _classification_holds(
        classification, subject.classification
    ):
        return False
    if conditions.type_code is not None and (
        subject.type_code is None or subject.type_code.upper() != conditions.type_code.upper()
    ):
        return False
    if conditions.model is not None and (
        subject.model is None or conditions.model.casefold() not in subject.model.casefold()
    ):
        return False
    if not _watchlist_holds(conditions, rule, subject.watchlists):
        return False
    if not _rarity_holds(conditions, subject):
        return False
    if not _distance_holds(conditions, subject.distance_nm):
        return False
    return _altitude_holds(conditions, subject.altitude_ft)


def evaluate(
    subject: AlertSubject,
    rules: Iterable[CompiledRule],
    *,
    alert_radius_nm: float | None = None,
) -> tuple[MatchProposal, ...]:
    """Everything that matches this aircraft right now, built-ins included.

    Ordered highest severity first, then by rule id, so two evaluations of the
    same instant produce the same tuple — which is what lets the interesting
    block's ``reasons`` list and the alert history be compared as documents
    rather than as sets.

    The built-in emergency match is evaluated first and unconditionally: it
    does not consult ``rules``, ``alert_radius_nm`` or the ground state, which
    is SPEC §47's *"do not require an unrelated interesting-aircraft rule"*
    expressed as control flow rather than as a comment.
    """
    proposals: list[MatchProposal] = []
    builtin = emergency_match(subject)
    if builtin is not None:
        proposals.append(builtin)
    proposals.extend(
        MatchProposal(
            key=f"rule:{rule.rule.id}",
            severity=rule.rule.severity,
            reason=rule.rule.reason,
            rule_id=rule.rule.id,
        )
        for rule in rules
        if matches(rule, subject, alert_radius_nm=alert_radius_nm)
    )
    proposals.sort(key=lambda proposal: (-proposal.severity.rank, proposal.rule_id or 0))
    return tuple(proposals)


__all__ = ["evaluate", "matches"]
