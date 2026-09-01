"""The precedence matrix and the provenance it produces.

Metadata precedence is a critical-coverage domain (``docs/TEST_STRATEGY.md``
§"Critical domains", roadmap slice 021 notes), so these tests aim at the
decision table itself rather than at a happy path: every field, both source
orders, silence on either side, ties, unranked sources, and the provenance that
must accompany each outcome.
"""

from __future__ import annotations

import pytest

from flightsite.metadata.precedence import (
    DEFAULT_FIELD_PRIORITIES,
    PROVENANCE_KEYS,
    RESOLVED_FIELDS,
    SRC_COLUMNS,
    UNRANKED,
    FieldPriority,
    PrecedenceModel,
    ResolvedMetadata,
    SourceClaim,
)
from flightsite.metadata.records import normalize_record

ICAO = "a0b1c2"
AT_MS = 1_756_600_000_000


def claim(source: str, **fields: object) -> SourceClaim:
    return SourceClaim(source=source, record=normalize_record(icao24=ICAO, **fields))  # type: ignore[arg-type]


@pytest.fixture
def model() -> PrecedenceModel:
    return PrecedenceModel(dict(DEFAULT_FIELD_PRIORITIES))


def resolve(model: PrecedenceModel, *claims: SourceClaim) -> ResolvedMetadata:
    return model.resolve(ICAO, claims, updated_ms=AT_MS)


# ------------------------------------------------------- the declared matrix


@pytest.mark.parametrize(
    ("name", "winner"),
    [
        ("registration", "mictronics"),
        ("type_code", "mictronics"),
        ("model", "mictronics"),
        ("operator_name", "mictronics"),
        ("manufacture_year", "faa"),
        ("owner", "faa"),
    ],
)
def test_every_field_resolves_to_its_declared_winner(
    model: PrecedenceModel, name: str, winner: str
) -> None:
    """The whole declared table, one case per field, both sources claiming."""
    mictronics = claim("mictronics", **{name: _value(name, "mictronics")})
    faa = claim("faa", **{name: _value(name, "faa")})

    resolved = resolve(model, mictronics, faa)

    assert getattr(resolved, SRC_COLUMNS[name]) == winner
    assert getattr(resolved, name) == _value(name, winner)


def test_source_order_does_not_change_the_outcome(model: PrecedenceModel) -> None:
    """Rank decides, not the order rows came back from the database in."""
    mictronics = claim("mictronics", registration="N302DN", manufacture_year=1999)
    faa = claim("faa", registration="N999XX", manufacture_year=2015)

    forward = resolve(model, mictronics, faa)
    backward = resolve(model, faa, mictronics)

    assert forward == backward
    assert forward.registration == "N302DN"
    assert forward.manufacture_year == 2015


def test_a_higher_ranked_source_that_is_silent_does_not_win(model: PrecedenceModel) -> None:
    """Silence is not a claim: the lower-ranked source's value survives."""
    mictronics = claim("mictronics", type_code="B738")
    faa = claim("faa", type_code="B738", manufacture_year=2015, owner="Delta Air Lines Inc")

    resolved = resolve(model, mictronics, faa)

    assert resolved.manufacture_year == 2015
    assert resolved.year_src == "faa"
    assert resolved.owner == "Delta Air Lines Inc"
    assert resolved.owner_src == "faa"


def test_a_lower_ranked_source_fills_what_the_winner_left_blank(
    model: PrecedenceModel,
) -> None:
    """Mictronics wins registration but has no year; the FAA supplies it."""
    mictronics = claim("mictronics", registration="N302DN", type_code="B739")
    faa = claim("faa", manufacture_year=2016)

    resolved = resolve(model, mictronics, faa)

    assert (resolved.registration, resolved.registration_src) == ("N302DN", "mictronics")
    assert (resolved.manufacture_year, resolved.year_src) == (2016, "faa")


def test_one_source_alone_wins_everything_it_claims(model: PrecedenceModel) -> None:
    faa = claim("faa", registration="N12345", model="CESSNA 172", owner="Someone")

    resolved = resolve(model, faa)

    assert resolved.registration_src == "faa"
    assert resolved.model_src == "faa"
    assert resolved.owner_src == "faa"
    assert resolved.type_code is None
    assert resolved.type_code_src is None


def test_no_claims_at_all_resolve_to_an_empty_row(model: PrecedenceModel) -> None:
    resolved = resolve(model)

    assert resolved.is_empty
    assert resolved.provenance() == {}


def test_a_claim_with_nothing_but_an_address_is_empty(model: PrecedenceModel) -> None:
    """An airframe every source is silent about is absent, not blank-and-present."""
    resolved = resolve(model, claim("mictronics"), claim("faa"))

    assert resolved.is_empty


# ------------------------------------------------------------- tie-breaking


def test_equal_ranks_break_deterministically_by_source_name() -> None:
    """Two sources ranked the same must not resolve by row order."""
    model = PrecedenceModel(
        {
            "alpha": FieldPriority(ranks={"model": 5}),
            "zulu": FieldPriority(ranks={"model": 5}),
        }
    )
    alpha = claim("alpha", model="A")
    zulu = claim("zulu", model="Z")

    assert resolve(model, alpha, zulu).model_src == "alpha"
    assert resolve(model, zulu, alpha).model_src == "alpha"


def test_an_unranked_source_loses_to_a_ranked_one(model: PrecedenceModel) -> None:
    stranger = claim("stranger", type_code="A320")
    mictronics = claim("mictronics", type_code="B738")

    resolved = resolve(model, stranger, mictronics)

    assert (resolved.type_code, resolved.type_code_src) == ("B738", "mictronics")


def test_an_unranked_source_still_wins_a_field_nobody_else_claims(
    model: PrecedenceModel,
) -> None:
    """Unranked means last, not excluded — leftover rows still contribute."""
    resolved = resolve(model, claim("stranger", owner="Someone"))

    assert (resolved.owner, resolved.owner_src) == ("Someone", "stranger")


def test_an_unmentioned_field_falls_back_to_the_declared_default() -> None:
    priority = FieldPriority(ranks={"model": 0}, default=7)

    assert priority.rank("model") == 0
    assert priority.rank("owner") == 7


def test_a_source_with_no_priority_at_all_ranks_unranked(model: PrecedenceModel) -> None:
    assert model.rank_of("stranger", "model") == UNRANKED
    assert model.rank_of("mictronics", "model") == 0


# --------------------------------------------------------------- provenance


def test_provenance_names_a_source_for_every_resolved_field(
    model: PrecedenceModel,
) -> None:
    mictronics = claim(
        "mictronics",
        registration="N302DN",
        type_code="B739",
        model="Boeing 737-900",
        operator_name="Delta Air Lines",
    )
    faa = claim("faa", manufacture_year=2016, owner="Delta Air Lines Inc")

    provenance = resolve(model, mictronics, faa).provenance()

    assert provenance == {
        "registration": "mictronics",
        "type_code": "mictronics",
        "model": "mictronics",
        "operator": "mictronics",
        "manufacture_year": "faa",
        "owner": "faa",
    }


def test_provenance_omits_fields_nobody_supplied(model: PrecedenceModel) -> None:
    """A provenance entry for a null field would claim a source spoke."""
    provenance = resolve(model, claim("mictronics", type_code="B738")).provenance()

    assert provenance == {"type_code": "mictronics"}


def test_provenance_values_are_the_canonical_api_vocabulary(
    model: PrecedenceModel,
) -> None:
    """``docs/API.md`` §2.8 fixes the spelling of every provenance value."""
    resolved = resolve(model, claim("mictronics", type_code="B738"), claim("faa", owner="X"))

    assert set(resolved.provenance().values()) <= {"mictronics", "faa"}


def test_provenance_keys_use_the_api_field_names() -> None:
    """``operator_name`` is stored, but the API calls it ``operator``."""
    assert PROVENANCE_KEYS["operator_name"] == "operator"
    assert set(PROVENANCE_KEYS) == set(RESOLVED_FIELDS)


# --------------------------------------------------------------- row shape


def test_src_columns_cover_every_resolved_field_with_the_data_model_names() -> None:
    """``docs/DATA_MODEL.md`` §3.3 spells two of these irregularly."""
    assert set(SRC_COLUMNS) == set(RESOLVED_FIELDS)
    assert SRC_COLUMNS["manufacture_year"] == "year_src"
    assert SRC_COLUMNS["operator_name"] == "operator_src"


def test_as_row_carries_every_column_the_resolved_table_declares(
    model: PrecedenceModel,
) -> None:
    from flightsite.db.models import AircraftMetadataResolved

    row = resolve(model, claim("mictronics", type_code="B738")).as_row()

    assert set(row) == {column.name for column in AircraftMetadataResolved.__table__.columns}


def test_a_src_column_is_set_exactly_when_its_field_is(model: PrecedenceModel) -> None:
    resolved = resolve(model, claim("faa", registration="N1", owner="Someone"))

    for name in RESOLVED_FIELDS:
        has_value = getattr(resolved, name) is not None
        has_source = getattr(resolved, SRC_COLUMNS[name]) is not None
        assert has_value == has_source, name


def _value(name: str, source: str) -> object:
    """A distinguishable per-source value of the right type for ``name``.

    Already in canonical form (integer year, upper-case type designator) so
    these assertions test precedence rather than re-testing normalization.
    """
    if name == "manufacture_year":
        return 1999 if source == "mictronics" else 2015
    if name == "type_code":
        return "B738" if source == "mictronics" else "A320"
    return f"{source}-{name}"
