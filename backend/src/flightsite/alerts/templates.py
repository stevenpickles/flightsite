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
rewritten.

Startup is not the only edge, though, and slice 055 added the other one.
``AlertService.start`` runs before the setup wizard has written anything, so on
a genuinely fresh install the list it reads is empty and the templates the user
is about to choose are instantiated by nothing at all — the install has no
alert rules until the backend is restarted (issue #110). The other edge is the
config save itself:
:meth:`flightsite.alerts.service.AlertService.apply_enabled_templates`, called
from the config apply path with the list as it was and the list as it now is.
Its semantics are documented there; the short version is that it instantiates
the keys *this save added*, which is why it can add the wizard's choice without
ever resurrecting a rule the user deleted.

Key spellings, and the one alias
--------------------------------

The catalogue key is the contract: it is what ``alerts.enabled_templates``
names, what ``alert_rules.template_key`` records, and what the setup wizard has
to send. ``police`` is that key for the law-enforcement template — SPEC §45
writes the template as "police/law enforcement", and the catalogue took the
first half.

The wizard sent ``law_enforcement`` instead, and because an unrecognized key is
skipped, the selection vanished with no rule and no complaint (issue #111). The
wizard is fixed to send ``police``; :data:`TEMPLATE_KEY_ALIASES` covers the
installs whose ``config.yaml`` already records the wrong spelling, mapping it to
``police`` on *read* only. Nothing rewrites the file: the alias is one entry in
a table, the config layer stays ignorant of the catalogue (its validator checks
shape, not names), and the next time the user saves the wizard's answer the
stored spelling corrects itself. An unknown key that is *not* an alias is still
skipped rather than fatal — but it is now warned about, which is what would
have made #111 visible on the first boot rather than in an E2E suite.
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


#: Spellings that are not catalogue keys but unambiguously mean one, mapped to
#: the key they mean. Read-only compatibility, never a second name a new client
#: may use: the alias exists so an install whose ``config.yaml`` was written by
#: the wizard that shipped with issue #111 keeps the templates its user chose,
#: and adding to this table is a migration substitute, not an API.
TEMPLATE_KEY_ALIASES: Final[MappingProxyType[str, str]] = MappingProxyType(
    {"law_enforcement": "police"}
)


def normalize_template_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """``keys`` with aliases resolved and duplicates dropped, in the given order.

    Order-preserving and de-duplicating because an alias can collide with the
    key it resolves to: a ``config.yaml`` naming both ``law_enforcement`` and
    ``police`` means the police template once, not twice, and the caller uses
    this result to decide what a save *added*.

    A key that is neither a catalogue key nor an alias passes through unchanged
    — recognizing it is :func:`unknown_template_keys`' job, and reporting it in
    the spelling the file actually contains is what makes that warning useful.
    """
    normalized: list[str] = []
    for key in keys:
        resolved = TEMPLATE_KEY_ALIASES.get(key, key)
        if resolved not in normalized:
            normalized.append(resolved)
    return tuple(normalized)


def aliased_template_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """The alias spellings present in ``keys``, in order.

    Separate from :func:`normalize_template_keys` so the caller can say which
    deprecated spelling it accepted and what it took it to mean, rather than
    silently repairing the configuration and leaving the user's file quietly
    wrong.
    """
    return tuple(key for key in keys if key in TEMPLATE_KEY_ALIASES)


def enabled_templates(keys: Sequence[str]) -> tuple[AlertTemplate, ...]:
    """The shipped templates ``keys`` names, in catalogue order.

    Aliases are resolved first (:func:`normalize_template_keys`), so a
    configuration written by a client that used a superseded spelling selects
    the template its user meant.

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
    wanted = set(normalize_template_keys(keys))
    return tuple(template for template in SHIPPED_TEMPLATES if template.key in wanted)


def unknown_template_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """The names in ``keys`` this build's catalogue does not have, in order.

    An alias is *not* unknown — it resolves to a catalogue key — so the result
    is exactly the keys that will select nothing, which is what the caller
    warns about.
    """
    return tuple(key for key in normalize_template_keys(keys) if key not in TEMPLATES_BY_KEY)


__all__ = [
    "SHIPPED_TEMPLATES",
    "TEMPLATES_BY_KEY",
    "TEMPLATE_KEY_ALIASES",
    "TEMPLATE_RARE_MAX_SIGHTINGS",
    "TEMPLATE_RARE_MAX_TYPE_AIRCRAFT",
    "AlertTemplate",
    "aliased_template_keys",
    "enabled_templates",
    "normalize_template_keys",
    "unknown_template_keys",
]
