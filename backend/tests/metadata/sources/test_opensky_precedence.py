"""OpenSky's fill-gaps-only merge policy (slice 059, ADR-0013).

The guarantee under test is a negative one: **OpenSky can never overwrite a
value another source supplied.** It holds by construction, from two independent
mechanisms, and this file exercises both so that breaking either one fails a
test rather than quietly changing what a user sees:

1. **Rank.** ``opensky`` is ranked strictly below ``mictronics`` and ``faa`` on
   every field it contributes, so
   :meth:`~flightsite.metadata.precedence.PrecedenceModel.winner` never picks it
   over a competing claim.
2. **Silence.** The adapter emits ``None`` for ``registration`` and
   ``type_code`` at all, so those two fields cannot be influenced even if the
   ranking were misconfigured.
"""

from __future__ import annotations

import pytest

from flightsite.metadata.precedence import (
    DEFAULT_FIELD_PRIORITIES,
    RESOLVED_FIELDS,
    UNRANKED,
    PrecedenceModel,
    SourceClaim,
)
from flightsite.metadata.records import NormalizedAircraftRecord

#: The four fields ADR-0013 lets this source contribute.
CONTRIBUTED_FIELDS = ("model", "manufacture_year", "operator_name", "owner")

#: The two it must never influence.
WITHHELD_FIELDS = ("registration", "type_code")


def _model() -> PrecedenceModel:
    return PrecedenceModel(dict(DEFAULT_FIELD_PRIORITIES))


def _claim(source: str, **fields: object) -> SourceClaim:
    return SourceClaim(source=source, record=NormalizedAircraftRecord(icao24="abc123", **fields))  # type: ignore[arg-type]


def test_opensky_is_ranked_below_both_default_sources_on_every_field() -> None:
    """The ordering the whole policy rests on, asserted directly."""
    model = _model()

    for field in RESOLVED_FIELDS:
        opensky = model.rank_of("opensky", field)
        assert opensky > model.rank_of("mictronics", field), field
        assert opensky > model.rank_of("faa", field), field


def test_opensky_declares_no_rank_for_the_fields_it_withholds() -> None:
    model = _model()

    for field in WITHHELD_FIELDS:
        assert model.rank_of("opensky", field) == UNRANKED, field


@pytest.mark.parametrize("field", CONTRIBUTED_FIELDS)
@pytest.mark.parametrize("rival", ["mictronics", "faa"])
def test_opensky_never_wins_a_field_another_source_already_filled(field: str, rival: str) -> None:
    value = 1999 if field == "manufacture_year" else "from-rival"
    other = 1888 if field == "manufacture_year" else "from-opensky"

    winner = _model().winner(
        field, [_claim("opensky", **{field: other}), _claim(rival, **{field: value})]
    )

    assert winner is not None
    assert winner.source == rival
    assert winner.value(field) == value


@pytest.mark.parametrize("field", CONTRIBUTED_FIELDS)
def test_opensky_wins_a_field_both_other_sources_left_null(field: str) -> None:
    """The whole point of the source: it fills gaps, and only gaps."""
    value = 1999 if field == "manufacture_year" else "from-opensky"

    winner = _model().winner(
        field,
        [
            _claim("mictronics", registration="G-ABCD"),
            _claim("faa"),
            _claim("opensky", **{field: value}),
        ],
    )

    assert winner is not None
    assert winner.source == "opensky"
    assert winner.value(field) == value


def test_a_full_resolve_takes_only_the_gaps_from_opensky() -> None:
    """The realistic case, end to end through ``resolve``.

    Mictronics knows the identity and type but no owner or year; the FAA knows
    nothing about this (non-US) airframe; OpenSky supplies operator, owner and
    year, and would also overwrite the model if it were allowed to.
    """
    resolved = _model().resolve(
        "abc123",
        [
            _claim(
                "mictronics",
                registration="G-ABCD",
                type_code="B738",
                model="Boeing 737-800",
                operator_name="Example Air",
            ),
            _claim(
                "opensky",
                model="Something Else Entirely",
                operator_name="Wrong Operator",
                owner="Example Air Leasing Ltd",
                manufacture_year=2011,
            ),
        ],
        updated_ms=1_756_600_000_000,
    )

    # Held by the higher-precedence source, untouched.
    assert (resolved.model, resolved.model_src) == ("Boeing 737-800", "mictronics")
    assert (resolved.operator_name, resolved.operator_src) == ("Example Air", "mictronics")
    assert (resolved.registration, resolved.registration_src) == ("G-ABCD", "mictronics")
    assert (resolved.type_code, resolved.type_code_src) == ("B738", "mictronics")
    # The genuine gaps, filled and attributed.
    assert (resolved.owner, resolved.owner_src) == ("Example Air Leasing Ltd", "opensky")
    assert (resolved.manufacture_year, resolved.year_src) == (2011, "opensky")


def test_provenance_names_opensky_only_where_it_actually_won() -> None:
    resolved = _model().resolve(
        "abc123",
        [
            _claim("mictronics", registration="G-ABCD", model="Boeing 737-800"),
            _claim("opensky", model="Ignored", owner="Example Air Leasing Ltd"),
        ],
        updated_ms=1_756_600_000_000,
    )

    provenance = resolved.provenance()

    assert provenance["owner"] == "opensky"
    assert provenance["model"] == "mictronics"
    assert "opensky" not in {provenance[key] for key in provenance if key != "owner"}


def test_removing_opensky_restores_exactly_the_previous_resolution() -> None:
    """Turning the source off again costs nothing that was there before.

    ADR-0013 promises a user who opts out loses only OpenSky-sourced values.
    Resolving the same claims with and without OpenSky must therefore differ in
    exactly the fields it won, and nowhere else.
    """
    claims = [
        _claim("mictronics", registration="G-ABCD", type_code="B738", model="Boeing 737-800"),
        _claim("faa", manufacture_year=2011),
    ]
    without = _model().resolve("abc123", claims, updated_ms=1)
    with_opensky = _model().resolve(
        "abc123",
        [*claims, _claim("opensky", model="Ignored", manufacture_year=1999, owner="Owner Ltd")],
        updated_ms=1,
    )

    for field in RESOLVED_FIELDS:
        if field == "owner":
            continue
        assert getattr(with_opensky, field) == getattr(without, field), field
    assert without.owner is None
    assert with_opensky.owner == "Owner Ltd"


def test_an_unregistered_opensky_cannot_win_anything() -> None:
    """A registry without OpenSky ranks leftover rows unranked, not first.

    ``SourceRegistry.precedence()`` builds the model from what is *currently*
    registered, so rows left behind by a source the user has since disabled
    fall to :data:`UNRANKED` — they can still fill a field nobody else has, but
    they never displace a live source.
    """
    model = PrecedenceModel({"mictronics": DEFAULT_FIELD_PRIORITIES["mictronics"]})

    winner = model.winner(
        "owner", [_claim("opensky", owner="stale"), _claim("mictronics", owner="current")]
    )

    assert winner is not None and winner.source == "mictronics"
