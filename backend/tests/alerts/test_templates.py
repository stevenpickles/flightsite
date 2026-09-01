"""The shipped catalogue: SPEC §45's seven, and what each one actually matches.

Two kinds of assertion here. The catalogue's *shape* — that it covers §45's
list, that every entry is evaluable, that its severities follow SPEC §46's
suggestion — and its *behaviour*, checked by evaluating each shipped rule
against an aircraft it should catch and one it should not. The second kind is
what stops a template from being a plausible-looking document that matches
nothing.
"""

from __future__ import annotations

import pytest

from flightsite.alerts.evaluator import matches
from flightsite.alerts.model import AlertSubject, CompiledRule, RuleConditions
from flightsite.alerts.templates import (
    SHIPPED_TEMPLATES,
    TEMPLATES_BY_KEY,
    AlertTemplate,
    enabled_templates,
    unknown_template_keys,
)
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.config import Settings

from .conftest import claimed, rule, subject

#: SPEC §45's list, with its "locally rare aircraft/type" entry split in two —
#: see :mod:`flightsite.alerts.templates` for why ``AND``-only rules force that.
EXPECTED_KEYS = (
    "military",
    "government",
    "police",
    "emergency_squawk",
    "first_ever",
    "locally_rare",
    "locally_rare_type",
    "watchlist",
)


def compiled(template: AlertTemplate, **kwargs: object) -> CompiledRule:
    conditions = template.conditions
    assert conditions is not None
    return rule(conditions, severity=template.severity, **kwargs)  # type: ignore[arg-type]


def test_the_catalogue_covers_exactly_spec_45s_list() -> None:
    assert tuple(template.key for template in SHIPPED_TEMPLATES) == EXPECTED_KEYS


def test_keys_are_unique_and_the_index_agrees_with_the_list() -> None:
    assert len(TEMPLATES_BY_KEY) == len(SHIPPED_TEMPLATES)
    assert all(TEMPLATES_BY_KEY[template.key] is template for template in SHIPPED_TEMPLATES)


@pytest.mark.parametrize(
    ("key", "severity"),
    [
        ("military", AlertSeverity.HIGH),
        ("government", AlertSeverity.HIGH),
        ("police", AlertSeverity.HIGH),
        ("emergency_squawk", AlertSeverity.CRITICAL),
        ("first_ever", AlertSeverity.INFO),
        ("locally_rare", AlertSeverity.INTERESTING),
        ("locally_rare_type", AlertSeverity.INTERESTING),
        ("watchlist", AlertSeverity.INTERESTING),
    ],
)
def test_the_severities_follow_spec_46s_suggestion(key: str, severity: AlertSeverity) -> None:
    assert TEMPLATES_BY_KEY[key].severity is severity


def test_only_the_emergency_template_is_a_builtin() -> None:
    """SPEC §47 makes it unconfigurable and ``docs/DATA_MODEL.md`` §4.2 gives
    it no condition kind, so it has nothing to instantiate."""
    builtins = [template.key for template in SHIPPED_TEMPLATES if template.builtin]

    assert builtins == ["emergency_squawk"]
    assert TEMPLATES_BY_KEY["emergency_squawk"].conditions is None
    assert not TEMPLATES_BY_KEY["emergency_squawk"].instantiable


def test_every_other_template_instantiates_a_real_rule() -> None:
    for template in SHIPPED_TEMPLATES:
        if template.builtin:
            continue
        assert template.instantiable
        assert isinstance(template.conditions, RuleConditions)
        assert template.conditions.describe()


@pytest.mark.parametrize(
    ("key", "hit", "miss"),
    [
        (
            "military",
            subject(classification=claimed(military=True)),
            subject(classification=claimed(government=True)),
        ),
        (
            "government",
            subject(classification=claimed(government=True)),
            subject(classification=claimed(military=True)),
        ),
        (
            "police",
            subject(classification=claimed(law_enforcement=True)),
            subject(classification=claimed(military=True)),
        ),
        ("first_ever", subject(sightings_here=1), subject(sightings_here=2)),
        ("locally_rare", subject(sightings_here=2), subject(sightings_here=3)),
        (
            "locally_rare_type",
            subject(type_aircraft_here=2),
            subject(type_aircraft_here=3),
        ),
        ("watchlist", subject(watchlists=("Locals",)), subject(watchlists=())),
    ],
)
def test_each_shipped_rule_catches_what_it_is_named_for(
    key: str, hit: AlertSubject, miss: AlertSubject
) -> None:
    template = compiled(TEMPLATES_BY_KEY[key])

    assert matches(template, hit, alert_radius_nm=None)
    assert not matches(template, miss, alert_radius_nm=None)


def test_the_first_ever_template_is_exactly_never_seen_here_before() -> None:
    """``max_sightings=1`` means the airframe's only sighting is the one
    happening now — see :class:`~flightsite.alerts.model.RarityCondition`."""
    conditions = TEMPLATES_BY_KEY["first_ever"].conditions
    assert conditions is not None
    assert conditions.rare_aircraft is not None
    assert conditions.rare_aircraft.max_sightings == 1


def test_the_watchlist_template_matches_any_list_rather_than_a_named_one() -> None:
    """A template instantiated at first run cannot name a watchlist id: on a
    first run there are no watchlists yet."""
    conditions = TEMPLATES_BY_KEY["watchlist"].conditions
    assert conditions is not None
    assert conditions.watchlist_any
    assert conditions.watchlist_id is None


def test_no_shipped_rule_opts_in_to_ground_traffic() -> None:
    """SPEC §40's default, and none of §45's templates is about the ramp."""
    for template in SHIPPED_TEMPLATES:
        if template.conditions is not None:
            assert not template.conditions.applies_on_ground


def test_enabled_templates_selects_in_catalogue_order() -> None:
    """Catalogue order rather than the caller's, so two installs with the same
    enabled set create rules in the same order and get the same ids."""
    selected = enabled_templates(["watchlist", "military"])

    assert [template.key for template in selected] == ["military", "watchlist"]


def test_enabled_templates_skips_a_key_this_build_does_not_have() -> None:
    """A key from a newer or older build is a normal upgrade artefact, and
    refusing to start over one would be a config typo taking the install
    down."""
    assert [template.key for template in enabled_templates(["military", "nope"])] == ["military"]
    assert unknown_template_keys(["military", "nope"]) == ("nope",)


def test_every_shipped_key_is_accepted_by_the_configuration_model() -> None:
    """``alerts.enabled_templates`` validates shape only — it deliberately does
    not know the catalogue — so this is the check that the two still fit."""
    settings = Settings(alerts={"enabled_templates": list(EXPECTED_KEYS)})  # type: ignore[arg-type]

    assert settings.alerts.enabled_templates == list(EXPECTED_KEYS)
