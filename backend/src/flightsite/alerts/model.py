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
rather than by guessing at an untagged blob. This build writes version 2 and
reads versions 1 and 2, refusing anything else — the same refusal
:func:`flightsite.sightings.track_codec.unpack_track` applies to an unknown
encoding version and for the same reason: decoding a newer format by guessing
is worse than saying so.

Version 2 (slice 089, issue #232)
---------------------------------

Version 2 adds seven optional conditions — a squawk set, callsign and
registration globs, ground-speed and vertical-rate windows, an emitter-category
set and a drawn area — still combined with the same flat ``AND`` (SPEC §43; OR
and nesting stay out, §79). Every one of them defaults to absent, so the v1
condition set is a strict subset of v2's and the upgrade is *only* the version
number: :meth:`RuleConditions._upgrade` rewrites ``"version": 1`` to ``2`` on
read, and a v1 rule therefore parses to exactly the conditions it always had
and evaluates identically. No migration rewrites ``alert_rules``: a stored v1
document stays v1 text until the rule is next saved, when it is written back as
v2 — a lazy rewrite that is a side effect of saving, not a separate pass.

A document that says ``"version": 1`` but carries a v2 condition is refused
rather than upgraded: it claims a schema that could not have contained what it
holds, which is a client bug worth surfacing rather than guessing past. A
document with no ``version`` at all is read as the current version, exactly as
it was when version 1 was current.

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
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    field_validator,
    model_validator,
)

from flightsite.alerts.area import (
    MAX_AREA_VERTICES,
    MIN_AREA_VERTICES,
    CompiledArea,
    normalize_ring,
)
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.classification.model import Classification
from flightsite.classification.vocabulary import MissionCategory
from flightsite.live.aircraft import GroundState

#: Schema version of the conditions document this build writes
#: (``docs/DATA_MODEL.md`` §4.2). See "Version 2" in the module docstring.
CONDITIONS_VERSION: Final = 2

#: Every version this build reads. Version 1 is upgraded on read.
READABLE_CONDITIONS_VERSIONS: Final = frozenset({1, 2})

#: The condition keys version 2 introduced. A document claiming version 1 may
#: not carry any of them (see the module docstring).
V2_CONDITION_KEYS: Final = frozenset(
    {
        "squawk_in",
        "callsign_glob",
        "registration_glob",
        "min_ground_speed_kt",
        "max_ground_speed_kt",
        "min_vertical_rate_fpm",
        "max_vertical_rate_fpm",
        "emitter_category_in",
        "within_area",
    }
)

#: Most squawk codes one ``squawk_in`` set may name. Sixteen covers every
#: real use — a block of conspicuity codes, a local listening-squawk range —
#: and a longer list is better written as several rules a user can name.
MAX_SQUAWK_CODES: Final = 16

#: Most emitter categories one ``emitter_category_in`` set may name: all 32
#: of A0 to D7, so the bound only exists to make the list finite.
MAX_EMITTER_CATEGORIES: Final = 32

#: Longest a callsign or registration glob may be. A callsign is at most
#: eight characters and a registration about ten; 32 leaves room for
#: wildcards without admitting an essay.
MAX_GLOB_LENGTH: Final = 32

#: Upper bound on a ground-speed condition, in knots. Faster than anything
#: with a transponder, so — like the altitude bounds — it exists to catch a
#: typo (km/h, a stray digit) rather than to state an aviation limit.
MAX_GROUND_SPEED_KT: Final = 2_000.0

#: Bound on the magnitude of a vertical-rate condition, in feet per minute.
#: Negative is descending. Typo-catching again: no aircraft sustains this.
MAX_VERTICAL_RATE_FPM: Final = 20_000.0

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


def _times(count: int) -> str:
    """``1`` as "once", anything else as "N times".

    English, not a template with the plural bolted on in brackets. The rule
    card is prose a user reads — "seen at most 1 time(s) here" is the shape
    of a string that was never finished, and the builder's own field label
    for the same idea ("At most this many sightings here") already reads
    properly. ``max_sightings`` is ``ge=1``, so there is no zero case to
    word.
    """
    return "once" if count == 1 else f"{count} times"


def _plural(count: int, noun: str) -> str:
    """``count`` and ``noun``, with the noun pluralised by a trailing ``s``.

    Only ever applied to nouns whose plural really is ``+s`` (``airframe``);
    this is not a general inflector and must not become one — a
    codebase-wide pluralisation problem is a localisation problem, and the
    honest fix for that is a library rather than a growing table of
    exceptions here.
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _either(values: Iterable[str]) -> str:
    """``A``, ``A or B``, ``A, B or C`` — a set read as the alternative it is.

    A set condition is an alternative *within* one condition ("squawking 1200
    or 7000"), which is not the boolean ``OR`` SPEC §43 keeps out of v1: the
    rule is still one flat ``AND`` of conditions, one of which is membership.
    """
    items = list(values)
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} or {items[-1]}"


def compile_glob(pattern: str) -> re.Pattern[str]:
    """A case-insensitive whole-string matcher for a ``*``/``?`` glob.

    Only the two wildcards mean anything: ``*`` is any run of characters
    (including none) and ``?`` exactly one. Every other character is escaped,
    so a ``.``, ``[`` or ``-`` in a registration is that character and never
    regex or ``fnmatch`` syntax — :func:`fnmatch.translate` would treat
    ``[AB]`` as a class, which is a third wildcard nobody documented. Runs of
    ``*`` collapse to one, which keeps the compiled pattern linear.
    """
    parts: list[str] = []
    for char in pattern:
        if char == "*":
            if not parts or parts[-1] != ".*":
                parts.append(".*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


#: A transponder code: four octal digits, as a string so ``0020`` keeps its
#: leading zero.
SquawkCode = Annotated[str, StringConstraints(pattern=r"^[0-7]{4}$")]

#: An ADS-B emitter category (DO-260B): set A to D, number 0 to 7. The same
#: spelling the live payload's ``emitter_category`` uses (slice 086).
EmitterCategory = Annotated[str, StringConstraints(pattern=r"^[A-D][0-7]$")]

#: A glob over a callsign or registration: no whitespace, at least one
#: character, at most :data:`MAX_GLOB_LENGTH`.
IdentityGlob = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_GLOB_LENGTH, pattern=r"^\S+$")
]


class AreaCondition(_Document):
    """A drawn polygon the aircraft's live position must be inside (slice 089).

    Spelled as a GeoJSON ``Polygon`` geometry (RFC 7946 §3.1.6) —
    ``{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}`` — so a shape
    drawn in the builder, exported from a GIS tool or pasted from geojson.io
    is the same document. Exactly one ring: GeoJSON's second ring is a hole,
    and holes are refused. The ring rules (3 to 64 vertices, auto-closed, no
    antimeridian crossing, no self-intersection) are
    :func:`flightsite.alerts.area.normalize_ring`'s.

    The ring is compiled into a :class:`~flightsite.alerts.area.CompiledArea`
    once, when the document is parsed, so evaluating it is a bounding-box
    check and at most one ray cast per aircraft with nothing built per call.
    """

    type: Literal["Polygon"] = "Polygon"
    coordinates: tuple[tuple[tuple[float, float], ...], ...]

    _compiled: CompiledArea = PrivateAttr()

    @field_validator("coordinates")
    @classmethod
    def _one_valid_ring(
        cls, rings: tuple[tuple[tuple[float, float], ...], ...]
    ) -> tuple[tuple[tuple[float, float], ...], ...]:
        if len(rings) == 0:
            raise ValueError("an area needs one ring of [longitude, latitude] vertices")
        if len(rings) > 1:
            raise ValueError(
                "an area may not have holes: give exactly one ring "
                f"(got {len(rings)} rings; GeoJSON's later rings are holes)"
            )
        return (normalize_ring(rings[0]),)

    def model_post_init(self, context: Any, /) -> None:
        self._compiled = CompiledArea.from_ring(self.coordinates[0])

    @property
    def compiled(self) -> CompiledArea:
        """The ring, pre-arranged for :meth:`CompiledArea.contains`."""
        return self._compiled

    @property
    def vertex_count(self) -> int:
        """Distinct vertices — the closing repeat is not counted."""
        return len(self.coordinates[0]) - 1


class RuleConditions(_Document):
    """The ``AND``-combined condition set of one rule (§4.2, SPEC §43).

    Every member defaults to "not a condition", so the document a user writes
    names only what they care about, and adding a condition kind in a later
    version cannot change what an existing stored rule means.
    """

    version: Literal[2] = CONDITIONS_VERSION

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

    # ------------------------------------------------ version 2 (slice 089)

    #: The live squawk is one of these codes. Sorted and de-duplicated on the
    #: way in so equal sets store as equal text. 7500/7600/7700 are allowed —
    #: a user may want a rule of their own about them — but the built-in
    #: emergency alert (SPEC §47) fires regardless, so this is never needed
    #: for them.
    squawk_in: tuple[SquawkCode, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_SQUAWK_CODES
    )
    #: Case-insensitive glob (``*``, ``?``) over the whole live callsign.
    callsign_glob: IdentityGlob | None = None
    #: Case-insensitive glob (``*``, ``?``) over the whole registration the
    #: metadata cache resolved. No metadata, no registration, no match.
    registration_glob: IdentityGlob | None = None
    min_ground_speed_kt: float | None = Field(default=None, ge=0.0, le=MAX_GROUND_SPEED_KT)
    max_ground_speed_kt: float | None = Field(default=None, gt=0.0, le=MAX_GROUND_SPEED_KT)
    #: Feet per minute, negative descending — the decoder's sign convention.
    min_vertical_rate_fpm: float | None = Field(
        default=None, ge=-MAX_VERTICAL_RATE_FPM, le=MAX_VERTICAL_RATE_FPM
    )
    max_vertical_rate_fpm: float | None = Field(
        default=None, ge=-MAX_VERTICAL_RATE_FPM, le=MAX_VERTICAL_RATE_FPM
    )
    #: The decoder-reported ADS-B emitter category (slice 086) is one of
    #: these. Sorted and de-duplicated like ``squawk_in``.
    emitter_category_in: tuple[EmitterCategory, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_EMITTER_CATEGORIES
    )
    #: The live position is inside this drawn area (or on its boundary).
    within_area: AreaCondition | None = None

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data: Any) -> Any:
        """Read a version 1 document as version 2. See the module docstring."""
        if not isinstance(data, dict):
            return data
        version = data.get("version")
        # `type(...) is int`: JSON `true` is a Python `True`, and `True == 1`.
        if type(version) is not int or version != 1:
            return data
        carried = sorted(V2_CONDITION_KEYS.intersection(data))
        if carried:
            raise ValueError(
                "a version 1 conditions document cannot carry conditions introduced "
                f"in version {CONDITIONS_VERSION}: {', '.join(carried)}"
            )
        return {**data, "version": CONDITIONS_VERSION}

    @field_validator("squawk_in", "emitter_category_in")
    @classmethod
    def _as_sorted_set(cls, values: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if values is None else tuple(sorted(set(values)))

    @property
    def extended(self) -> bool:
        """True when any version 2 condition is present (never for a v1 rule)."""
        return any(getattr(self, key) is not None for key in V2_CONDITION_KEYS)

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
        if (
            self.min_ground_speed_kt is not None
            and self.max_ground_speed_kt is not None
            and self.min_ground_speed_kt >= self.max_ground_speed_kt
        ):
            raise ValueError(
                "min_ground_speed_kt must be less than max_ground_speed_kt "
                f"(got {self.min_ground_speed_kt} and {self.max_ground_speed_kt})"
            )
        if (
            self.min_vertical_rate_fpm is not None
            and self.max_vertical_rate_fpm is not None
            and self.min_vertical_rate_fpm >= self.max_vertical_rate_fpm
        ):
            raise ValueError(
                "min_vertical_rate_fpm must be less than max_vertical_rate_fpm "
                f"(got {self.min_vertical_rate_fpm} and {self.max_vertical_rate_fpm})"
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

        Counts are worded, not templated — see :func:`_times` and
        :func:`_plural`. These phrases are read by a person on the Rules tab,
        and "1 time(s)" is a string that was never finished.
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
            phrases.append(f"seen at most {_times(self.rare_aircraft.max_sightings)} here")
        if self.rare_type is not None:
            phrases.append(
                f"type seen on at most {_plural(self.rare_type.max_sightings, 'airframe')} here"
            )
        if self.min_distance_nm is not None:
            phrases.append(f"at least {self.min_distance_nm:g} nm away")
        if self.max_distance_nm is not None:
            phrases.append(f"within {self.max_distance_nm:g} nm")
        if self.min_alt_ft is not None:
            phrases.append(f"at or above {self.min_alt_ft:g} ft")
        if self.max_alt_ft is not None:
            phrases.append(f"at or below {self.max_alt_ft:g} ft")
        # Version 2 phrases come after every v1 phrase, so a v1 rule's
        # description is unchanged by the upgrade, word for word.
        if self.squawk_in is not None:
            phrases.append(f"squawking {_either(self.squawk_in)}")
        if self.callsign_glob is not None:
            phrases.append(f"callsign matching {self.callsign_glob!r}")
        if self.registration_glob is not None:
            phrases.append(f"registration matching {self.registration_glob!r}")
        if self.emitter_category_in is not None:
            phrases.append(f"emitter category {_either(self.emitter_category_in)}")
        if self.min_ground_speed_kt is not None:
            phrases.append(f"ground speed at least {self.min_ground_speed_kt:g} kt")
        if self.max_ground_speed_kt is not None:
            phrases.append(f"ground speed at most {self.max_ground_speed_kt:g} kt")
        # Signed explicitly, because the sign is the meaning: "+500" is a
        # climb and "-500" a descent, and a bare "500" would leave a reader
        # guessing which way a "-500 ft/min" floor points.
        if self.min_vertical_rate_fpm is not None:
            phrases.append(f"vertical rate at or above {self.min_vertical_rate_fpm:+g} ft/min")
        if self.max_vertical_rate_fpm is not None:
            phrases.append(f"vertical rate at or below {self.max_vertical_rate_fpm:+g} ft/min")
        if self.within_area is not None:
            # `vertex` does not pluralise with +s, and a ring always has at
            # least three, so the plural is written out (see `_plural`).
            phrases.append(f"inside a drawn area of {self.within_area.vertex_count} vertices")
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
class ExtendedConditions:
    """A rule's version 2 conditions, compiled for the evaluator (slice 089).

    Built once per :class:`CompiledRule` — once per rule per rule-set reload —
    and never per aircraft: the squawk and category sets become frozensets,
    the globs compiled patterns, and the area the
    :class:`~flightsite.alerts.area.CompiledArea` its document already holds.
    A plain slotted dataclass rather than private state on the Pydantic
    model, because the evaluator reads these for every aircraft and a slot
    read is the cheapest attribute access Python has. (Private attributes on
    the model were tried first: they resolve through ``__getattr__``, and the
    version 2 rules in ``tests/alerts/test_perf.py`` cost about three times
    as much that way.)
    """

    squawks: frozenset[str] | None = None
    categories: frozenset[str] | None = None
    min_ground_speed_kt: float | None = None
    max_ground_speed_kt: float | None = None
    min_vertical_rate_fpm: float | None = None
    max_vertical_rate_fpm: float | None = None
    callsign: re.Pattern[str] | None = None
    registration: re.Pattern[str] | None = None
    area: CompiledArea | None = None

    @classmethod
    def compile(cls, conditions: RuleConditions) -> ExtendedConditions | None:
        """The compiled form, or ``None`` when no version 2 condition is set."""
        if not conditions.extended:
            return None
        callsign, registration = conditions.callsign_glob, conditions.registration_glob
        return cls(
            squawks=None if conditions.squawk_in is None else frozenset(conditions.squawk_in),
            categories=(
                None
                if conditions.emitter_category_in is None
                else frozenset(conditions.emitter_category_in)
            ),
            min_ground_speed_kt=conditions.min_ground_speed_kt,
            max_ground_speed_kt=conditions.max_ground_speed_kt,
            min_vertical_rate_fpm=conditions.min_vertical_rate_fpm,
            max_vertical_rate_fpm=conditions.max_vertical_rate_fpm,
            callsign=None if callsign is None else compile_glob(callsign),
            registration=None if registration is None else compile_glob(registration),
            area=None if conditions.within_area is None else conditions.within_area.compiled,
        )


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
    #: The rule's version 2 conditions, compiled — ``None`` when it has none,
    #: which is every v1 rule. Derived, never passed: see
    #: :class:`ExtendedConditions`.
    extended: ExtendedConditions | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extended", ExtendedConditions.compile(self.rule.conditions))

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
    #: The decoder's current emergency state (slice 086) — the second built-in
    #: emergency source beside the squawk.
    decoder_emergency: str | None = None
    distance_nm: float | None = None
    altitude_ft: float | None = None
    ground_state: GroundState = GroundState.UNKNOWN

    #: Live kinematics and identity for the version 2 conditions (slice 089),
    #: all straight from the live record: the decoder's ground speed (kt),
    #: vertical rate (ft/min, negative descending), emitter category
    #: (slice 086), position in decimal degrees, and transmitted callsign.
    ground_speed_kt: float | None = None
    vertical_rate_fpm: float | None = None
    emitter_category: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    callsign: str | None = None

    classification: Classification = field(default_factory=Classification)
    type_code: str | None = None
    model: str | None = None
    #: The registration the metadata cache resolved (never transmitted by
    #: ADS-B itself), for ``registration_glob``.
    registration: str | None = None
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
    #: For a built-in emergency match (slice 086): what declared it —
    #: ``squawk`` or ``decoder`` — and the emergency kind, in the decoder's
    #: emergency-state vocabulary. ``None`` for every rule match.
    emergency_source: str | None = None
    emergency_kind: str | None = None

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

    The identity block — ``callsign``, ``registration``, ``type_code`` — and
    the two sighting records are joined for the same reason and answer a
    different question. SPEC §48 says a notification carries "callsign/tail,
    aircraft type, classification, altitude, distance, match reason", and the
    history is exactly where someone goes when they *missed* the
    notification; a bare six-hex address is not something a person
    recognises. Every one of them is ``None``-able and means §2.7's absence:
    no callsign was ever transmitted, no metadata source knows this airframe,
    the sighting never had a position.

    ``closest_approach_nm`` and ``lowest_alt_ft`` are the *sighting's*
    records, not a snapshot taken at the instant of the match —
    ``alert_matches`` stores no position, and inventing one now would be
    worse than naming what is actually known. On a sighting still open they
    keep moving; the field names are the ones §3.5/§3.7 already use for the
    same facts, so nothing suggests otherwise.
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
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    closest_approach_nm: float | None = None
    lowest_alt_ft: int | None = None


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
    "MAX_AREA_VERTICES",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_DISTANCE_NM",
    "MAX_EMITTER_CATEGORIES",
    "MAX_GLOB_LENGTH",
    "MAX_GROUND_SPEED_KT",
    "MAX_NAME_LENGTH",
    "MAX_RARITY_THRESHOLD",
    "MAX_SQUAWK_CODES",
    "MAX_VERTICAL_RATE_FPM",
    "MIN_ALTITUDE_FT",
    "MIN_AREA_VERTICES",
    "READABLE_CONDITIONS_VERSIONS",
    "V2_CONDITION_KEYS",
    "AlertRuleRecord",
    "AlertSubject",
    "AreaCondition",
    "ClassificationCondition",
    "CompiledRule",
    "ExtendedConditions",
    "InterestingState",
    "MatchProposal",
    "RarityCondition",
    "RuleConditions",
    "StoredAlertMatch",
    "compile_glob",
]
