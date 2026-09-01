"""Emergency squawks fire with zero configuration and cannot be switched off.

Roadmap slice 038's second acceptance criterion is *"emergency squawks alert
with zero user configuration"*, and SPEC §47 adds the harder half: they must
not require *any* rule, and nothing a user can write may suppress them. That
makes the interesting assertions negative ones — no rules, ground state,
distance, an empty install — so they are all here rather than folded into the
evaluator matrix.
"""

from __future__ import annotations

import pytest

from flightsite.alerts.builtins import emergency_match, emergency_reason
from flightsite.alerts.evaluator import evaluate
from flightsite.alerts.model import ClassificationCondition, RuleConditions
from flightsite.alerts.vocabulary import EMERGENCY_MEANINGS, AlertSeverity
from flightsite.live import GroundState

from .conftest import claimed, rule, subject


@pytest.mark.parametrize("squawk", sorted(EMERGENCY_MEANINGS))
def test_every_emergency_code_fires_at_critical_with_no_rules_at_all(squawk: str) -> None:
    """The acceptance criterion, stated as directly as it can be: an empty rule
    set, an ordinary aircraft, one squawk."""
    (proposal,) = evaluate(subject(squawk=squawk), [])

    assert proposal.severity is AlertSeverity.CRITICAL
    assert proposal.is_builtin
    assert proposal.builtin_key == f"emergency_{squawk}"
    assert proposal.key == f"builtin:emergency_{squawk}"


def test_an_ordinary_squawk_fires_nothing() -> None:
    assert evaluate(subject(squawk="1200"), []) == ()


def test_no_squawk_at_all_fires_nothing() -> None:
    """A decoder omitting a squawk is not a statement that an emergency ended —
    the live record keeps the last one it heard, so ``None`` here means the
    aircraft has never transmitted one."""
    assert emergency_match(subject(squawk=None)) is None


@pytest.mark.parametrize("squawk", sorted(EMERGENCY_MEANINGS))
def test_the_reason_names_the_code_and_what_it_means(squawk: str) -> None:
    """The code alone is jargon: a user should not need to know that 7600 is a
    radio failure to read the notification."""
    reason = emergency_reason(squawk)

    assert squawk in reason
    assert EMERGENCY_MEANINGS[squawk] in reason


def test_an_emergency_on_the_ground_still_fires() -> None:
    """SPEC §40 excludes ground traffic from *relevant* alerts, and this is the
    case where that exclusion would be most wrong: 7500 is unlawful
    interference, which happens at a gate."""
    on_ground = subject(squawk="7500", ground_state=GroundState.ON_GROUND, altitude_ft=None)

    (proposal,) = evaluate(on_ground, [])

    assert proposal.builtin_key == "emergency_7500"


def test_an_emergency_beyond_the_alert_radius_still_fires() -> None:
    """SPEC §66's radius exists so ordinary traffic at the edge of coverage is
    not noise. An aircraft squawking 7700 is not noise at any distance."""
    far = subject(squawk="7700", distance_nm=400.0)

    (proposal,) = evaluate(far, [], alert_radius_nm=50.0)

    assert proposal.builtin_key == "emergency_7700"


def test_a_disabled_rule_set_does_not_disable_the_builtin() -> None:
    """Anything expressible as a rule row is by construction something a user
    can turn off; §47 does not permit that for emergencies."""
    disabled = rule(
        RuleConditions(classification=ClassificationCondition(military=True)), enabled=False
    )

    (proposal,) = evaluate(subject(squawk="7600"), [disabled])

    assert proposal.builtin_key == "emergency_7600"


def test_the_builtin_sorts_above_a_matching_rule() -> None:
    """Critical outranks everything, so the interesting block's first reason —
    the one a one-line UI shows — is the emergency."""
    military = rule(
        RuleConditions(classification=ClassificationCondition(military=True)),
        severity=AlertSeverity.HIGH,
    )
    proposals = evaluate(subject(squawk="7700", classification=claimed(military=True)), [military])

    assert [proposal.severity for proposal in proposals] == [
        AlertSeverity.CRITICAL,
        AlertSeverity.HIGH,
    ]


def test_the_condition_document_cannot_express_a_squawk_at_all() -> None:
    """The structural reason emergencies are built in rather than a shipped
    rule: ``docs/DATA_MODEL.md`` §4.2's closed condition set has no squawk
    kind, so there is no document a user could write that would express it."""
    assert "squawk" not in RuleConditions.model_fields
