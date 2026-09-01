"""The shipped alert templates (SPEC §45).

SPEC §45 names seven: military; government; police/law enforcement; emergency
squawk; first-ever aircraft; locally rare aircraft/type; watchlist match. It
also states the rule this module exists to keep — *"during setup, the user
chooses which templates to enable. Do not silently enable every possible
notification."* — which is why the catalogue here is inert data and the
``alerts.enabled_templates`` list in the configuration is what turns any of it
into rows.

The severities follow SPEC §46's own suggestion, which is worth reading as the
product decision it is rather than as an arbitrary mapping: first-ever is
``info`` because it happens several times an hour on a new receiver; locally
rare is ``interesting`` because it is worth a glance; watchlist is
``interesting`` because the user asked for it but chose the terms;
military/government/police are ``high`` because they are the reason most people
install an ADS-B receiver; and emergency is ``critical``.

"Locally rare aircraft/type" is two templates
----------------------------------------------

§45 writes the sixth as one entry covering both halves of SPEC §44's rarity,
but a v1 rule combines its conditions with ``AND`` only (SPEC §43) — so a
single rule carrying both a ``rare_aircraft`` and a ``rare_type`` condition
would mean "a rare airframe **of** a rare type", which is a much narrower thing
than either half and would silently miss the common cases the template exists
for. The two halves are therefore two templates
(``locally_rare``/``locally_rare_type``), each enabled independently, which is
the decomposition §45's own "aircraft/type" slash asks for once ``AND`` is the
only combinator available.

The emergency template is not a rule
------------------------------------

Seven of the eight instantiate an ``alert_rules`` row. ``emergency_squawk``
cannot and must not: ``docs/DATA_MODEL.md`` §4.2's condition set has no squawk
kind, and SPEC §47 requires emergency detection to fire without any rule and
without being switchable off. It is listed here anyway — a user opening the
template gallery must see that emergency alerting exists — with
:attr:`AlertTemplate.builtin` set, which means *"this is already on; there is
nothing to instantiate and nothing to disable"*. Enabling or omitting it in
``alerts.enabled_templates`` changes nothing about whether 7500/7600/7700 fire,
and :mod:`flightsite.alerts.builtins` is where that is guaranteed.

Instantiation, and why it happens once
---------------------------------------

:class:`flightsite.alerts.service.AlertService` instantiates the enabled
templates at startup **only when ``alert_rules`` holds no template-provenance
row at all** — no row with a non-``NULL`` ``template_key``. That is the
idempotency rule, and it is the right one rather than a per-key check for two
reasons. A user who deletes a shipped rule must not have it silently return on
the next restart; and a user who changes ``alerts.enabled_templates`` after
first run is editing a wizard answer, not asking for their tuned rule set to be
rewritten. The setup wizard writes the list once; from then on the Alerts page
(slice 041) owns the rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from flightsite.alerts.model import (
    ClassificationCondition,
    RarityCondition,
    RuleConditions,
)
from flightsite.alerts.vocabulary import EMERGENCY_SEVERITY, AlertSeverity

#: Lifetime sightings at or below which the shipped "locally rare aircraft"
#: template calls an airframe rare. Two, matching
#: :data:`flightsite.analytics.queries.DEFAULT_RARE_MAX_SIGHTINGS`, so a rule a
#: user never touched agrees with the Analytics page's own rare list.
TEMPLATE_RARE_MAX_SIGHTINGS: Final = 2

#: Airframes of a type at or below which the shipped "locally rare type"
#: template calls the type rare. Matches
#: :data:`flightsite.analytics.queries.DEFAULT_RARE_MAX_TYPE_AIRCRAFT`.
TEMPLATE_RARE_MAX_TYPE_AIRCRAFT: Final = 2


@dataclass(frozen=True, slots=True)
class AlertTemplate:
    """One shipped template: what it is called, and the rule it becomes.

    ``conditions`` is ``None`` exactly for :attr:`builtin` templates, which
    become no rule at all — see the module docstring.
    """

    key: str
    name: str
    description: str
    severity: AlertSeverity
    conditions: RuleConditions | None = None
    #: True when this template describes behaviour that is built in and always
    #: on, rather than a rule to instantiate (SPEC §47's emergency squawks).
    builtin: bool = False

    @property
    def instantiable(self) -> bool:
        """Whether enabling this template creates an ``alert_rules`` row."""
        return self.conditions is not None and not self.builtin


#: Every template this build ships, in the order SPEC §45 lists them (with the
#: rarity entry split in two — see the module docstring) — which is also the
#: order a template gallery should show them.
SHIPPED_TEMPLATES: Final[tuple[AlertTemplate, ...]] = (
    AlertTemplate(
        key="military",
        name="Military aircraft",
        description="Any aircraft classified as military (SPEC §39).",
        severity=AlertSeverity.HIGH,
        conditions=RuleConditions(classification=ClassificationCondition(military=True)),
    ),
    AlertTemplate(
        key="government",
        name="Government aircraft",
        description="Any aircraft classified as a government operator.",
        severity=AlertSeverity.HIGH,
        conditions=RuleConditions(classification=ClassificationCondition(government=True)),
    ),
    AlertTemplate(
        key="police",
        name="Police and law enforcement",
        description="Any aircraft classified as law enforcement (SPEC §39).",
        severity=AlertSeverity.HIGH,
        conditions=RuleConditions(classification=ClassificationCondition(law_enforcement=True)),
    ),
    AlertTemplate(
        key="emergency_squawk",
        name="Emergency squawk",
        description=(
            "Squawk 7500, 7600 or 7700. Built in and always on: SPEC §47 requires "
            "emergency squawks to alert without a rule, so this template has no rule "
            "to enable or disable."
        ),
        severity=EMERGENCY_SEVERITY,
        builtin=True,
    ),
    AlertTemplate(
        key="first_ever",
        name="First-ever aircraft",
        description="An airframe this receiver has never recorded before (SPEC §44).",
        severity=AlertSeverity.INFO,
        conditions=RuleConditions(rare_aircraft=RarityCondition(max_sightings=1)),
    ),
    AlertTemplate(
        key="locally_rare",
        name="Locally rare aircraft",
        description=(
            f"An airframe recorded at most {TEMPLATE_RARE_MAX_SIGHTINGS} times "
            "here, this sighting included (SPEC §44)."
        ),
        severity=AlertSeverity.INTERESTING,
        conditions=RuleConditions(
            rare_aircraft=RarityCondition(max_sightings=TEMPLATE_RARE_MAX_SIGHTINGS)
        ),
    ),
    AlertTemplate(
        key="locally_rare_type",
        name="Locally rare type",
        description=(
            "An ICAO type designator recorded on at most "
            f"{TEMPLATE_RARE_MAX_TYPE_AIRCRAFT} airframes here (SPEC §44)."
        ),
        severity=AlertSeverity.INTERESTING,
        conditions=RuleConditions(
            rare_type=RarityCondition(max_sightings=TEMPLATE_RARE_MAX_TYPE_AIRCRAFT)
        ),
    ),
    AlertTemplate(
        key="watchlist",
        name="Watchlist match",
        description=(
            "Any aircraft on any watchlist (SPEC §42). Matches by membership rather "
            "than by a named list, because a template instantiated at first run has "
            "no watchlist to name yet."
        ),
        severity=AlertSeverity.INTERESTING,
        conditions=RuleConditions(watchlist_any=True),
    ),
)

#: The catalogue keyed by ``template_key``, which is what
#: ``alerts.enabled_templates`` names and what
#: ``alert_rules.template_key`` records.
TEMPLATES_BY_KEY: Final[MappingProxyType[str, AlertTemplate]] = MappingProxyType(
    {template.key: template for template in SHIPPED_TEMPLATES}
)


def enabled_templates(keys: Sequence[str]) -> tuple[AlertTemplate, ...]:
    """The shipped templates ``keys`` names, in catalogue order.

    An unrecognized key is skipped rather than raising: ``alerts.
    enabled_templates`` is validated for *shape* by the config model, which
    deliberately does not know the catalogue
    (:class:`flightsite.config.models.AlertSettings`), so a key from a newer or
    older build reaching this list is a normal outcome of an upgrade or a
    downgrade — and refusing to start over one would be a configuration typo
    taking the whole install down. The caller logs what it skipped.

    Catalogue order rather than the caller's, so two installs with the same set
    of enabled templates get rules created in the same order and therefore the
    same ids — which is what makes a fixture of shipped rules comparable.
    """
    wanted = set(keys)
    return tuple(template for template in SHIPPED_TEMPLATES if template.key in wanted)


def unknown_template_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """The names in ``keys`` this build's catalogue does not have, in order."""
    return tuple(key for key in keys if key not in TEMPLATES_BY_KEY)


__all__ = [
    "SHIPPED_TEMPLATES",
    "TEMPLATES_BY_KEY",
    "TEMPLATE_RARE_MAX_SIGHTINGS",
    "TEMPLATE_RARE_MAX_TYPE_AIRCRAFT",
    "AlertTemplate",
    "enabled_templates",
    "unknown_template_keys",
]
