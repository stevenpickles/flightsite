"""What a rule is, what it is evaluated against, and what a match says.

The conditions document
-----------------------

``docs/DATA_MODEL.md`` §4.2 stores a rule's conditions as *one embedded,
Pydantic-validated JSON document* rather than a child table, and names this
module as the owner of its shape. :class:`RuleConditions` is that shape: a flat
record of optional conditions, every one of which must hold for the rule to
match (SPEC §43's ``AND``, with no nested boolean trees in v1).

Two properties are load-bearing and both are enforced here rather than by
convention:

* **A rule with no conditions is not a rule.** An empty document would match
  every aircraft in the sky at whatever severity it declared, which is the one
  configuration a user can never have meant. :meth:`RuleConditions.describe`
  would have nothing to say about it either — a rule whose reason cannot be
  written is a rule whose behaviour cannot be explained.
* **Every threshold has bounds.** ``max_sightings`` of zero can never match,
  a negative distance can never match, and an altitude window whose floor is
  above its ceiling can never match. Each is a rule that silently does nothing,
  so each is a validation error at the point the rule is written instead of a
  mystery at the point it fails to fire.

``version`` is §4.2's forward door: the document carries the schema it was
written against, so a future nested-expression feature migrates explicitly
rather than by guessing at an untagged blob. This build reads and writes
version 1 and refuses anything else, which is the same refusal
:func:`flightsite.sightings.track_codec.unpack_track` applies to an unknown
encoding version and for the same reason — decoding a newer format by guessing
is worse than saying so.

Two condition keys are not in §4.2's list and are named here because §4.2's
document, not its SQL, is where the closed set actually lives:

* ``watchlist_any`` — "on any watchlist at all". SPEC §45 ships a *watchlist
  match* template, and a template instantiated at first run cannot name a
  watchlist id, because on a first run there are no watchlists yet. Without
  this the shipped template would be uninstantiable.
* ``applies_on_ground`` — SPEC §40 requires ground traffic to be excludable
  from *relevant* alerts, and the honest default is to exclude it: a rule about
  military aircraft means military aircraft flying, not one parked on a ramp
  that the receiver hears all day. A rule that genuinely wants the ramp says
  so.

What the engine is given
------------------------

:class:`AlertSubject` is the whole of what a rule may reason from, and it is
deliberately a flat record of already-known values rather than a handle on the
live store, the metadata cache or a session. That is what makes
:func:`flightsite.alerts.evaluator.evaluate` a pure function checkable against
a matrix of cases — the roadmap's *"each condition type + AND combinations
verified"* — and it is also what makes the ``docs/ARCHITECTURE.md`` §3.1
invariant structural: a subject is assembled from in-memory lookups only, so
there is no code path from evaluation to SQLite to accidentally take.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.classification.model import Classification
from flightsite.classification.vocabulary import MissionCategory
from flightsite.live.aircraft import GroundState

#: Schema version of the conditions document (``docs/DATA_MODEL.md`` §4.2).
CONDITIONS_VERSION: Final = 1

#: Upper bound on a rarity threshold. A receiver-relative "rare" count in the
#: thousands is not rarity, it is every aircraft — and 031's own rarity surface
#: bounds its ``max_sightings`` query parameter the same way.
MAX_RARITY_THRESHOLD: Final = 1_000

#: Upper bound on a distance condition, in nautical miles. Matches the bound
#: :class:`flightsite.config.Settings` puts on ``alert_radius_nm``, so a rule
#: cannot express a distance the configuration could not.
MAX_DISTANCE_NM: Final = 10_000.0

#: Bounds on an altitude condition, in feet. The floor is below the Dead Sea's
#: surface and the ceiling above any transponder-equipped aircraft, so both
#: exist to catch a typo (a user meaning metres, or a stray digit) rather than
#: to express a real aviation limit.
MIN_ALTITUDE_FT: Final = -2_000.0
MAX_ALTITUDE_FT: Final = 100_000.0

#: Longest a rule name or description may be. Rule names are shown in the
#: interesting panel, in notifications and in the alert history, all of which
#: are one line.
MAX_NAME_LENGTH: Final = 120
MAX_DESCRIPTION_LENGTH: Final = 500


class _Document(BaseModel):
    """Base for the stored condition models: no extra keys, no silent coercion.

    ``extra="forbid"`` matters more here than in a request body: this document
    round-trips through a ``TEXT`` column, so a key that a future build stops
    reading would otherwise sit in storage looking like a condition that is
    being applied.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ClassificationCondition(_Document):
    """Require SPEC §39 classification claims (``docs/DATA_MODEL.md`` §4.2).

    The three flags are *requirements*, never negations: ``military=True``
    means "must be military" and ``military=False`` means "do not care". There
    is deliberately no way to say "must not be military" — that is a boolean
    ``NOT``, and SPEC §43 limits v1 to ``AND`` over positive conditions.

    ``mission`` is an exact match on the resolved mission category, and it
    cannot be ``unknown``: a rule that fired on every airframe nobody has
    metadata for would be a rule about FlightSite's ignorance rather than about
    aircraft. That is the same exclusion
    :mod:`flightsite.watchlists.vocabulary` applies to a ``category`` entry.
    """

    military: bool = False
    government: bool = False
    law_enforcement: bool = False
    mission: MissionCategory | None = None

    @model_validator(mode="after")
    def _asserts_something(self) -> Self:
        if not (self.military or self.government or self.law_enforcement or self.mission):
            raise ValueError(
                "a classification condition must require at least one of "
                "military, government, law_enforcement or mission"
            )
        if self.mission is MissionCategory.UNKNOWN:
            raise ValueError(
                "mission 'unknown' is not a condition: it would match every airframe "
                "no metadata source has heard of"
            )
        return self

    def describe(self) -> str:
        """A phrase naming what this requires, for the rule's own description."""
        parts = [
            name
            for name, wanted in (
                ("military", self.military),
                ("government", self.government),
                ("law enforcement", self.law_enforcement),
            )
            if wanted
        ]
        if self.mission is not None:
            parts.append(f"mission {self.mission.value}")
        return " and ".join(parts)


class RarityCondition(_Document):
    """A receiver-relative rarity threshold (SPEC §44).

    ``max_sightings`` is inclusive — *at or below* — which is the same
    comparison ``GET /api/v1/analytics/rarity`` (slice 031) makes against
    ``aircraft.sighting_count`` and ``type_stats.unique_aircraft``. Two
    surfaces answering "is this rare here?" must not use different
    inequalities, or a user reads one number on the Analytics page and gets no
    alert about it.

    ``max_sightings=1`` is therefore exactly "never seen here before": the
    airframe's only sighting is the one happening now.
    """

    max_sightings: int = Field(ge=1, le=MAX_RARITY_THRESHOLD)


class RuleConditions(_Document):
    """The ``AND``-combined condition set of one rule (§4.2, SPEC §43).

    Every member defaults to "not a condition", so the document a user writes
    names only what they care about, and adding a condition kind in a later
    version cannot change what an existing stored rule means.
    """

    version: Literal[1] = CONDITIONS_VERSION

    classification: ClassificationCondition | None = None
    #: Exact match on the resolved ICAO type designator, case-insensitively.
    type_code: str | None = Field(default=None, min_length=1, max_length=16)
    #: Case-insensitive **substring** of the resolved model name. Exact
    #: matching would be unusable: the stored value is prose from a registry
    #: ("Boeing C-17A Globemaster III"), and a user writing a rule means
    #: "Globemaster", not that string character for character.
    model: str | None = Field(default=None, min_length=1, max_length=120)
    #: Membership of one specific watchlist, by id (§4.2's spelling).
    watchlist_id: int | None = Field(default=None, ge=1)
    #: Membership of *any* watchlist — see the module docstring for why this
    #: exists beside ``watchlist_id``.
    watchlist_any: bool = False
    rare_aircraft: RarityCondition | None = None
    rare_type: RarityCondition | None = None
    max_distance_nm: float | None = Field(default=None, gt=0.0, le=MAX_DISTANCE_NM)
    min_distance_nm: float | None = Field(default=None, ge=0.0, le=MAX_DISTANCE_NM)
    max_alt_ft: float | None = Field(default=None, ge=MIN_ALTITUDE_FT, le=MAX_ALTITUDE_FT)
    min_alt_ft: float | None = Field(default=None, ge=MIN_ALTITUDE_FT, le=MAX_ALTITUDE_FT)
    #: Whether this rule also applies to aircraft the decoder reports on the
    #: ground. ``False`` — the default — is SPEC §40's "excluded from relevant
    #: alerts".
    applies_on_ground: bool = False

    @model_validator(mode="after")
    def _is_a_rule(self) -> Self:
        if not self.describe():
            raise ValueError(
                "a rule must have at least one condition: an empty condition set "
                "would match every aircraft"
            )
        if (
            self.min_distance_nm is not None
            and self.max_distance_nm is not None
            and self.min_distance_nm >= self.max_distance_nm
        ):
            raise ValueError(
                "min_distance_nm must be less than max_distance_nm "
                f"(got {self.min_distance_nm} and {self.max_distance_nm})"
            )
        if (
            self.min_alt_ft is not None
            and self.max_alt_ft is not None
            and self.min_alt_ft >= self.max_alt_ft
        ):
            raise ValueError(
                f"min_alt_ft must be less than max_alt_ft (got {self.min_alt_ft} "
                f"and {self.max_alt_ft})"
            )
        return self

    def describe(self) -> tuple[str, ...]:
        """One readable phrase per condition, in a stable order.

        Used by the internal API to echo back what a rule actually says, and by
        the empty-rule validation above — a condition set nothing can be said
        about is a condition set that constrains nothing.

        Deliberately *not* the reason string a match carries: a match names the
        rule the user wrote (``docs/API.md`` §3.3's ``"Rule: Military
        aircraft"``), because the rule's name is the user's own description of
        what it detects and is what they want to read in a notification.
        """
        phrases: list[str] = []
        if self.classification is not None:
            phrases.append(self.classification.describe())
        if self.type_code is not None:
            phrases.append(f"type {self.type_code}")
        if self.model is not None:
            phrases.append(f"model containing {self.model!r}")
        if self.watchlist_id is not None:
            phrases.append(f"on watchlist {self.watchlist_id}")
        if self.watchlist_any:
            phrases.append("on any watchlist")
        if self.rare_aircraft is not None:
            phrases.append(f"seen at most {self.rare_aircraft.max_sightings} time(s) here")
        if self.rare_type is not None:
            phrases.append(f"type seen on at most {self.rare_type.max_sightings} airframe(s) here")
        if self.min_distance_nm is not None:
            phrases.append(f"at least {self.min_distance_nm:g} nm away")
        if self.max_distance_nm is not None:
            phrases.append(f"within {self.max_distance_nm:g} nm")
        if self.min_alt_ft is not None:
            phrases.append(f"at or above {self.min_alt_ft:g} ft")
        if self.max_alt_ft is not None:
            phrases.append(f"at or below {self.max_alt_ft:g} ft")
        return tuple(phrases)

    def to_json(self) -> str:
        """The compact JSON the ``conditions_json`` column stores.

        Sorted keys and no whitespace, for the same reason
        :meth:`flightsite.sightings.state.PendingEvent.payload_json` uses them:
        two equal documents must produce equal text, so a round trip through
        the column is comparable.
        """
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> RuleConditions:
        """Parse a stored document.

        Raises:
            ValueError: the text is not JSON, is not an object, or does not
                validate — including a ``version`` this build does not know.
                A rule that cannot be read is not silently treated as a rule
                that matches nothing; the caller decides, and
                :class:`flightsite.alerts.repository.AlertRepository` logs and
                skips it so one corrupt row cannot take the engine down.
        """
        decoded: Any = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("conditions document must be a JSON object")
        return cls.model_validate(decoded)


@dataclass(frozen=True, slots=True)
class AlertRuleRecord:
    """One stored ``alert_rules`` row, with its conditions already parsed."""

    id: int
    name: str
    severity: AlertSeverity
    conditions: RuleConditions
    description: str | None = None
    enabled: bool = True
    #: ``None`` for a user-written rule; the template's key for a shipped one
    #: (``docs/DATA_MODEL.md`` §4.2's provenance column).
    template_key: str | None = None
    created_ms: int = 0
    updated_ms: int = 0

    @property
    def reason(self) -> str:
        """The match reason this rule produces — ``docs/API.md`` §3.3's shape.

        The rule's *name*, because that is the user's own one-line statement of
        what the rule detects, and it is what §3.3's example shows
        (``"Rule: Military aircraft"``). The same string reaches the
        interesting panel, the browser notification (slice 040) and the stored
        ``alert_matches.reason``, so all three say the same thing rather than
        three renderings that drift.
        """
        return f"Rule: {self.name}"


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """A rule with everything resolved that evaluation would otherwise look up.

    Only one thing needs resolving, and it is the reason this type exists at
    all: a ``watchlist_id`` condition has to become the watchlist *name*,
    because :meth:`flightsite.watchlists.matcher.WatchlistMatcher.matches`
    answers in names — names are unique, and a name is what the live payload
    already carries. Resolving it once per rule-set reload rather than once per
    aircraft per cycle is what keeps evaluation free of any lookup at all.

    ``watchlist_name`` is ``None`` when the condition names a watchlist that no
    longer exists, and the rule then matches nothing. That is the honest
    outcome: a rule about a deleted watchlist has no aircraft it can be true
    of, and silently promoting it to "any watchlist" would fire alerts the user
    never asked for.
    """

    rule: AlertRuleRecord
    watchlist_name: str | None = None

    @property
    def unresolved_watchlist(self) -> bool:
        """True when a ``watchlist_id`` condition resolved to no watchlist."""
        return self.rule.conditions.watchlist_id is not None and self.watchlist_name is None


@dataclass(frozen=True, slots=True)
class AlertSubject:
    """Everything a rule may reason from about one live aircraft, right now.

    Assembled by :func:`flightsite.alerts.engine.subject_for` from four
    in-memory sources — the live record, the metadata cache's resolved view,
    the watchlist matcher, and the persistence worker's open accumulator — and
    nothing else. See the module docstring for why that is structural rather
    than a convention.
    """

    icao: str
    at_ms: int

    #: Ids of the aircraft's open sighting, ``None`` until the persistence
    #: worker's cycle has committed it (the first second or so of a new
    #: aircraft). A match cannot be *persisted* without them; it is still
    #: evaluated, and the engine holds it until they arrive.
    sighting_id: int | None = None
    aircraft_id: int | None = None

    squawk: str | None = None
    distance_nm: float | None = None
    altitude_ft: float | None = None
    ground_state: GroundState = GroundState.UNKNOWN

    classification: Classification = field(default_factory=Classification)
    type_code: str | None = None
    model: str | None = None
    watchlists: tuple[str, ...] = ()

    #: Lifetime sightings of this airframe *including the one happening now*
    #: (SPEC §44). ``1`` means never seen here before.
    sightings_here: int = 1
    #: Distinct airframes of this aircraft's type ever recorded here,
    #: including this one. ``None`` when no metadata source has resolved a
    #: type, in which case a ``rare_type`` condition cannot be satisfied.
    type_aircraft_here: int | None = None

    #: False while the metadata cache has not resolved this airframe yet. The
    #: engine re-evaluates such aircraft on later cycles: classification, type,
    #: model and rarity all arrive a fraction of a second after the aircraft
    #: does (``docs/API.md`` §2.7), and a rule about them must not be decided
    #: on the absence.
    metadata_resolved: bool = False

    @property
    def on_ground(self) -> bool:
        """Whether the decoder states this aircraft is on the ground (SPEC §40).

        ``unknown`` is not on the ground: FlightSite does not infer the ground
        from altitude and speed (:mod:`flightsite.live.aircraft`), so treating
        the unknown answer as "on the ground" would silently suppress alerts
        for every aircraft whose decoder is quiet about it.
        """
        return self.ground_state is GroundState.ON_GROUND


@dataclass(frozen=True, slots=True)
class MatchProposal:
    """One thing that matched, before anything has been deduplicated or stored.

    ``key`` is the dedupe identity within a sighting — ``rule:{id}`` or
    ``builtin:{key}`` — and it is what
    :class:`flightsite.alerts.engine.AlertEngine` compares against what this
    sighting has already fired. The two partial unique indexes on
    ``alert_matches`` enforce the same identity in storage, so the in-memory
    check is a cheap first pass and the constraint is the contract.
    """

    key: str
    severity: AlertSeverity
    reason: str
    rule_id: int | None = None
    builtin_key: str | None = None

    @property
    def is_builtin(self) -> bool:
        """True for a match no user rule produced (SPEC §47)."""
        return self.builtin_key is not None


@dataclass(frozen=True, slots=True)
class StoredAlertMatch:
    """One ``alert_matches`` row, as the history endpoint reports it.

    ``icao24`` and ``rule_name`` are joined rather than duplicated into the
    row, for the reason
    :class:`flightsite.activity.model.StoredActivityEvent` gives: they are the
    identities a client links on, and reading them from their own tables means
    a rename can never leave the history naming something that no longer
    exists. ``rule_name`` is ``None`` for a built-in match, which has no rule.
    """

    id: int
    matched_ms: int
    severity: str
    reason: str
    sighting_id: int
    aircraft_id: int
    icao24: str
    rule_id: int | None = None
    rule_name: str | None = None
    builtin_key: str | None = None
    notified: bool = False


@dataclass(frozen=True, slots=True)
class InterestingState:
    """The ``docs/API.md`` §3.3 ``interesting`` block for one live aircraft.

    Held in memory by the engine and read by the API serializer, so the REST
    live picture and every WebSocket frame carry the same answer without either
    of them re-evaluating anything.
    """

    severity: AlertSeverity
    reasons: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        """The §3.3 object: a severity and the reasons behind it."""
        return {"severity": self.severity.value, "reasons": list(self.reasons)}


__all__ = [
    "CONDITIONS_VERSION",
    "MAX_ALTITUDE_FT",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_DISTANCE_NM",
    "MAX_NAME_LENGTH",
    "MAX_RARITY_THRESHOLD",
    "MIN_ALTITUDE_FT",
    "AlertRuleRecord",
    "AlertSubject",
    "ClassificationCondition",
    "CompiledRule",
    "InterestingState",
    "MatchProposal",
    "RarityCondition",
    "RuleConditions",
    "StoredAlertMatch",
]
