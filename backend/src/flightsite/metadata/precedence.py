"""Field-level precedence: which source wins which field, and why.

``docs/DATA_MODEL.md`` §3.3 keeps every source's unmerged claim in
``aircraft_metadata`` and materializes one merged row per airframe in
``aircraft_metadata_resolved``, each field tagged with the source that supplied
it. This module is the merge rule, kept as a pure function over in-memory
claims so the whole precedence matrix is testable without a database.

Precedence is **per field, not per source**. A single source ranking would
force a false choice: Mictronics carries proper ICAO type designators and
operator names that the FAA registry does not, while the FAA registry is the
authority on U.S. manufacture years and owners that Mictronics leaves blank.
Ranking per field lets each source win where it is actually better, which is
what roadmap slice 023 means by *"supplements, does not clobber better data"*.

Three rules make the outcome deterministic and safe:

1. **Silence never wins.** A ``None`` is not a claim, so a sparse source can
   never blank a field a richer source filled. Only sources offering a value
   for a field compete for it.
2. **Lowest rank wins**, ties broken by source name. Two sources ranked equally
   would otherwise resolve differently depending on row order, and a resolved
   table that changes under re-import for no reason is indistinguishable from a
   bug.
3. **Unranked sources rank last.** A source registered without a declared
   priority still contributes what nobody else knows, but never displaces a
   source someone deliberately ranked.

Provenance falls out of the same pass: the winning source's name is recorded
beside the value, non-``NULL`` exactly when the value is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from flightsite.metadata.records import NormalizedAircraftRecord

#: The fields precedence resolves, named as they appear on
#: :class:`~flightsite.metadata.records.NormalizedAircraftRecord` and on the
#: ``aircraft_metadata`` row.
RESOLVED_FIELDS: Final[tuple[str, ...]] = (
    "registration",
    "type_code",
    "model",
    "manufacture_year",
    "operator_name",
    "owner",
)

#: Field name to its provenance column in ``aircraft_metadata_resolved``. Two
#: of them are not simply ``<field>_src`` — ``docs/DATA_MODEL.md`` §3.3 names
#: them ``year_src`` and ``operator_src`` — so the mapping is spelled out
#: rather than derived, and a test asserts it covers every resolved field.
SRC_COLUMNS: Final[Mapping[str, str]] = {
    "registration": "registration_src",
    "type_code": "type_code_src",
    "model": "model_src",
    "manufacture_year": "year_src",
    "operator_name": "operator_src",
    "owner": "owner_src",
}

#: Field name to the key it takes in an API ``provenance`` map
#: (``docs/API.md`` §2.6, where the operator's key is ``operator``).
PROVENANCE_KEYS: Final[Mapping[str, str]] = {
    "registration": "registration",
    "type_code": "type_code",
    "model": "model",
    "manufacture_year": "manufacture_year",
    "operator_name": "operator",
    "owner": "owner",
}

#: Rank given to a field a source declared no opinion about, and to a source
#: with no declared priority at all. Large enough that it always loses to a
#: declared rank, finite so such a source still wins a field nobody else has.
UNRANKED: Final = 1_000


@dataclass(frozen=True, slots=True)
class FieldPriority:
    """One source's per-field ranking. Lower is better.

    ``default`` covers fields the declaration does not mention, so adding a
    field to :data:`RESOLVED_FIELDS` later cannot silently promote a source
    above one that was ranked explicitly.
    """

    ranks: Mapping[str, int] = field(default_factory=dict)
    default: int = UNRANKED

    def rank(self, name: str) -> int:
        """This source's rank for ``name``."""
        return self.ranks.get(name, self.default)


#: Priorities for the two sources v1 ships (slices 022 and 023).
#:
#: Mictronics leads on identity and type: it is the primary offline source
#: (SPEC §25), worldwide, and carries ICAO type designators and operator names
#: in the form FlightSite groups by. The FAA registry leads on manufacture year
#: and owner: those are what a national registry actually holds, and Mictronics
#: mostly leaves them empty (SPEC §26). Where both know a registration the
#: values agree; ranking Mictronics first there simply keeps one source
#: authoritative for the identity triple rather than splitting it.
DEFAULT_FIELD_PRIORITIES: Final[Mapping[str, FieldPriority]] = {
    "mictronics": FieldPriority(
        ranks={
            "registration": 0,
            "type_code": 0,
            "model": 0,
            "operator_name": 0,
            "manufacture_year": 1,
            "owner": 1,
        }
    ),
    "faa": FieldPriority(
        ranks={
            "registration": 1,
            "type_code": 1,
            "model": 1,
            "operator_name": 1,
            "manufacture_year": 0,
            "owner": 0,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class SourceClaim:
    """What one source says about one airframe."""

    source: str
    record: NormalizedAircraftRecord

    def value(self, name: str) -> str | int | None:
        """This claim's value for ``name``, or ``None`` if it makes none."""
        value: str | int | None = getattr(self.record, name)
        return value


@dataclass(frozen=True, slots=True)
class ResolvedMetadata:
    """One airframe's merged metadata with per-field provenance.

    Mirrors ``aircraft_metadata_resolved`` column for column, so the importer
    writes it without a translation step and the cache reads it back into the
    same shape.
    """

    icao24: str
    updated_ms: int
    registration: str | None = None
    registration_src: str | None = None
    type_code: str | None = None
    type_code_src: str | None = None
    model: str | None = None
    model_src: str | None = None
    manufacture_year: int | None = None
    year_src: str | None = None
    operator_name: str | None = None
    operator_src: str | None = None
    operator_group_id: int | None = None
    owner: str | None = None
    owner_src: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when no source supplied any resolvable field.

        Such a row carries nothing a reader could use, so the importer does not
        store one — an airframe with no known metadata is simply absent from
        the resolved table, which is also how the cache reports it.
        """
        return all(getattr(self, name) is None for name in RESOLVED_FIELDS)

    def provenance(self) -> dict[str, str]:
        """Per-field provenance in the ``docs/API.md`` §2.6 shape.

        Only fields that actually have a value appear: a provenance entry for
        a ``null`` field would claim a source said something it did not.
        """
        result: dict[str, str] = {}
        for name in RESOLVED_FIELDS:
            source = getattr(self, SRC_COLUMNS[name])
            if getattr(self, name) is not None and source is not None:
                result[PROVENANCE_KEYS[name]] = str(source)
        return result

    def as_row(self) -> dict[str, str | int | None]:
        """Column values for an ``aircraft_metadata_resolved`` insert."""
        row: dict[str, str | int | None] = {
            "icao24": self.icao24,
            "operator_group_id": self.operator_group_id,
            "updated_ms": self.updated_ms,
        }
        for name in RESOLVED_FIELDS:
            row[name] = getattr(self, name)
            row[SRC_COLUMNS[name]] = getattr(self, SRC_COLUMNS[name])
        return row


@dataclass(frozen=True, slots=True)
class PrecedenceModel:
    """Resolves competing per-source claims into one row per airframe."""

    priorities: Mapping[str, FieldPriority] = field(
        default_factory=lambda: dict(DEFAULT_FIELD_PRIORITIES)
    )

    def rank_of(self, source: str, name: str) -> int:
        """Rank ``source`` claims for field ``name``. Lower wins."""
        priority = self.priorities.get(source)
        return UNRANKED if priority is None else priority.rank(name)

    def winner(self, name: str, claims: Iterable[SourceClaim]) -> SourceClaim | None:
        """The claim that wins ``name``, or ``None`` if nobody claims it."""
        best: SourceClaim | None = None
        best_key: tuple[int, str] | None = None
        for claim in claims:
            if claim.value(name) is None:
                continue
            key = (self.rank_of(claim.source, name), claim.source)
            if best_key is None or key < best_key:
                best, best_key = claim, key
        return best

    def resolve(
        self,
        icao24: str,
        claims: Sequence[SourceClaim],
        *,
        updated_ms: int,
        operator_group_id: int | None = None,
    ) -> ResolvedMetadata:
        """Merge ``claims`` for one airframe into a resolved row.

        Written out field by field rather than assembled by keyword expansion:
        this is the slice's critical decision, and spelling it explicitly is
        what lets the type checker confirm every resolved column is filled
        exactly once and from the right kind of value.
        """
        registration, registration_src = self._pick_text("registration", claims)
        type_code, type_code_src = self._pick_text("type_code", claims)
        model, model_src = self._pick_text("model", claims)
        manufacture_year, year_src = self._pick_int("manufacture_year", claims)
        operator_name, operator_src = self._pick_text("operator_name", claims)
        owner, owner_src = self._pick_text("owner", claims)
        return ResolvedMetadata(
            icao24=icao24,
            updated_ms=updated_ms,
            registration=registration,
            registration_src=registration_src,
            type_code=type_code,
            type_code_src=type_code_src,
            model=model,
            model_src=model_src,
            manufacture_year=manufacture_year,
            year_src=year_src,
            operator_name=operator_name,
            operator_src=operator_src,
            operator_group_id=operator_group_id,
            owner=owner,
            owner_src=owner_src,
        )

    def _pick_text(self, name: str, claims: Sequence[SourceClaim]) -> tuple[str | None, str | None]:
        winner = self.winner(name, claims)
        if winner is None:
            return None, None
        value = winner.value(name)
        return (None if value is None else str(value)), winner.source

    def _pick_int(self, name: str, claims: Sequence[SourceClaim]) -> tuple[int | None, str | None]:
        winner = self.winner(name, claims)
        if winner is None:
            return None, None
        value = winner.value(name)
        return (None if value is None else int(value)), winner.source


__all__ = [
    "DEFAULT_FIELD_PRIORITIES",
    "PROVENANCE_KEYS",
    "RESOLVED_FIELDS",
    "SRC_COLUMNS",
    "UNRANKED",
    "FieldPriority",
    "PrecedenceModel",
    "ResolvedMetadata",
    "SourceClaim",
]
