"""The grid index: nearest is nearest, including at the seams.

A bucketed index is only as good as its edges. Three of them get their own
tests because each is a place where a plausible-looking implementation returns
a *wrong answer* rather than an obviously broken one:

* a cell boundary, where the true nearest airport is one cell over;
* the antimeridian, where 179.9°E and 179.9°W are six miles apart;
* the polar band, where a fixed longitude span in degrees stops covering a
  fixed distance.

Correctness is checked against a brute-force scan of the same records, which is
the only way to prove the bucketing did not silently lose a candidate.
"""

from __future__ import annotations

import pytest

from flightsite.airports.index import (
    CELL_DEG,
    LAT_CELLS,
    LON_CELLS,
    POLAR_LATITUDE_DEG,
    AirportIndex,
)
from flightsite.ingest import Position
from flightsite.live.geo import distance_nm
from tests.airports.conftest import (
    BOEING_FIELD,
    FIXTURE_AIRPORTS,
    airport,
    north_of,
)


def brute_force_nearest(records: tuple[object, ...], position: Position, within_nm: float):  # type: ignore[no-untyped-def]
    """The answer a full scan gives, for the index to be checked against."""
    best = None
    for record in records:
        distance = distance_nm(
            position,
            Position(latitude=record.lat, longitude=record.lon),  # type: ignore[attr-defined]
        )
        if distance > within_nm:
            continue
        key = (distance, record.ident)  # type: ignore[attr-defined]
        if best is None or key < best[0]:
            best = (key, record, distance)
    return None if best is None else (best[1], best[2])


def test_an_empty_index_answers_nothing() -> None:
    """The normal state until a user runs an update: one dict miss, no crash."""
    index = AirportIndex()

    assert len(index) == 0
    assert index.nearest(Position(latitude=47.5, longitude=-122.3), within_nm=30.0) is None
    assert index.get("KSEA") is None


def test_the_nearest_of_two_nearby_fields(index: AirportIndex) -> None:
    """Two miles north of Boeing Field, Boeing Field is nearer than Sea-Tac."""
    found = index.nearest(north_of(BOEING_FIELD, 2.0), within_nm=30.0)

    assert found is not None
    assert found.airport.ident == "KBFI"
    assert found.distance_nm == pytest.approx(2.0, abs=0.01)


def test_the_other_field_wins_when_it_is_closer(index: AirportIndex) -> None:
    """Well south of Boeing Field, Sea-Tac is the nearer of the two."""
    found = index.nearest(Position(latitude=47.44, longitude=-122.3088), within_nm=30.0)

    assert found is not None
    assert found.airport.ident == "KSEA"


def test_nothing_within_the_radius_is_an_honest_nothing(index: AirportIndex) -> None:
    """A hundred miles out to sea. §2.7: `None`, not the least-far airport."""
    found = index.nearest(Position(latitude=45.0, longitude=-127.0), within_nm=30.0)

    assert found is None


def test_the_radius_is_the_radius(index: AirportIndex) -> None:
    """Just inside answers; just outside does not."""
    inside = index.nearest(north_of(BOEING_FIELD, 9.9), within_nm=10.0)
    outside = index.nearest(north_of(BOEING_FIELD, 10.1), within_nm=10.0)

    assert inside is not None and inside.airport.ident == "KBFI"
    assert outside is None


@pytest.mark.parametrize("within_nm", [0.0, -1.0])
def test_a_non_positive_radius_asks_nothing(index: AirportIndex, within_nm: float) -> None:
    assert index.nearest(north_of(BOEING_FIELD, 0.1), within_nm=within_nm) is None


def test_lookup_by_ident_is_case_insensitive(index: AirportIndex) -> None:
    """How a caller holding a stored `inferred_airport_ident` gets a name back."""
    found = index.get("kbfi")

    assert found is not None
    assert found.name == "Boeing Field"


# ------------------------------------------------------------- grid edges


def test_a_field_one_cell_over_is_still_found(index: AirportIndex) -> None:
    """``CELLA`` and ``CELLB`` straddle the 47.5° cell boundary.

    Queried from just below the line, the *nearer* airport is the one just
    below it — but a query from just above must still see the one below, which
    is the neighbouring-cell walk this asserts.
    """
    below = index.nearest(Position(latitude=47.49985, longitude=-120.0), within_nm=5.0)
    above = index.nearest(Position(latitude=47.50015, longitude=-120.0), within_nm=5.0)

    assert below is not None and below.airport.ident == "CELLA"
    assert above is not None and above.airport.ident == "CELLB"


def test_a_query_exactly_on_a_cell_boundary_sees_both_sides(index: AirportIndex) -> None:
    """On the line, both cells are in reach and the full scan's answer wins.

    Which of the two is nearer at exactly 47.5° is a question about the last
    bit of a float, not about the index; what the index owes is that neither
    candidate was dropped, which is what agreeing with the scan proves.
    """
    position = Position(latitude=47.5, longitude=-120.0)

    found = index.nearest(position, within_nm=5.0)
    expected = brute_force_nearest(FIXTURE_AIRPORTS, position, 5.0)

    assert found is not None and expected is not None
    assert found.airport.ident == expected[0].ident


def test_an_exact_tie_is_broken_by_ident(index: AirportIndex) -> None:
    """Two fields at genuinely identical coordinates — a heliport on an airport.

    The answer must be stable across polls, or the panel would alternate
    between two names once a second.
    """
    tied = AirportIndex([airport("ZZZZ", 10.0, 10.0), airport("AAAA", 10.0, 10.0)])

    first = tied.nearest(Position(latitude=10.0, longitude=10.0), within_nm=1.0)
    second = tied.nearest(Position(latitude=10.0, longitude=10.0), within_nm=1.0)

    assert first is not None and first.airport.ident == "AAAA"
    assert second is not None and second.airport.ident == "AAAA"


def test_the_antimeridian_is_not_a_wall(index: AirportIndex) -> None:
    """179.95°E and 179.95°W are 6 nm apart, not 360 degrees apart."""
    from_east = index.nearest(Position(latitude=0.0, longitude=179.99), within_nm=20.0)
    from_west = index.nearest(Position(latitude=0.0, longitude=-179.99), within_nm=20.0)

    assert from_east is not None and from_east.airport.ident == "EASTX"
    assert from_west is not None and from_west.airport.ident == "WESTX"

    # And across it: standing on the seam, both are in reach.
    on_seam = index.nearest(Position(latitude=0.0, longitude=180.0), within_nm=20.0)
    assert on_seam is not None
    assert on_seam.airport.ident in {"EASTX", "WESTX"}


def test_a_query_east_of_the_seam_reaches_an_airport_west_of_it() -> None:
    """The case a clamped (rather than modular) longitude index would lose."""
    index = AirportIndex([airport("WESTX", 0.0, -179.95)])

    found = index.nearest(Position(latitude=0.0, longitude=179.98), within_nm=20.0)

    assert found is not None
    assert found.airport.ident == "WESTX"


def test_the_polar_band_scans_the_whole_latitude(index: AirportIndex) -> None:
    """Near the pole a fixed longitude span in degrees stops covering a distance.

    From 60 degrees of longitude away at 87°N the great-circle distance is only
    a few dozen miles, so a query that computed its longitude span the way it
    does at the equator would miss the airport entirely.
    """
    found = index.nearest(Position(latitude=87.0, longitude=-40.0), within_nm=200.0)

    assert found is not None
    assert found.airport.ident == "POLAR"


def test_a_wide_search_below_the_polar_band_still_scans_the_whole_band() -> None:
    """The other guard: the longitude span in degrees can exceed the world.

    Just below :data:`POLAR_LATITUDE_DEG` the meridians have converged far
    enough that a wide enough radius spans more than half the planet in
    longitude, so the span has to collapse to "every cell" without the polar
    check having fired. Wider than any radius the inference asks for — the
    index takes a radius from its caller and must survive one.
    """
    index = AirportIndex([airport("HIGHLAT", 84.0, 170.0)])

    found = index.nearest(Position(latitude=84.0, longitude=-170.0), within_nm=1_200.0)

    assert found is not None
    assert found.airport.ident == "HIGHLAT"


def test_a_query_at_the_pole_does_not_index_past_the_end() -> None:
    """Exactly 90° is the clamp `_lat_cell` exists for."""
    index = AirportIndex([airport("NORTH", 89.99, 0.0)])

    found = index.nearest(Position(latitude=90.0, longitude=0.0), within_nm=30.0)

    assert found is not None
    assert found.airport.ident == "NORTH"


def test_a_search_does_not_wrap_over_a_pole() -> None:
    """A band past 90° does not exist; it is not the far side of the world.

    Two airports at the same longitude, one just south of the north pole and
    one just north of the south pole. A query at the north pole must find the
    first and never the second, however wide the radius.
    """
    index = AirportIndex(
        [airport("NORTH", 89.5, 0.0), airport("SOUTH", -89.5, 0.0)],
    )

    found = index.nearest(Position(latitude=89.9, longitude=0.0), within_nm=200.0)

    assert found is not None
    assert found.airport.ident == "NORTH"


# ------------------------------------------------------- against brute force


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (47.53, -122.30),
        (47.49, -122.25),
        (47.4999, -120.0),
        (47.5001, -120.0),
        (0.0, 179.999),
        (0.0, -179.999),
        (87.0, 100.0),
        (39.0, -106.0),
        (10.0, 10.0),
    ],
)
def test_the_index_agrees_with_a_full_scan(index: AirportIndex, lat: float, lon: float) -> None:
    """The property that matters: bucketing changed the cost, not the answer."""
    position = Position(latitude=lat, longitude=lon)

    found = index.nearest(position, within_nm=200.0)
    expected = brute_force_nearest(FIXTURE_AIRPORTS, position, 200.0)

    if expected is None:
        assert found is None
    else:
        assert found is not None
        assert found.airport.ident == expected[0].ident
        assert found.distance_nm == pytest.approx(expected[1])


# ------------------------------------------------------------- book-keeping


def test_the_polar_band_starts_below_the_pole() -> None:
    """A guard that only fired at 90 degrees would never fire in practice."""
    assert 0.0 < POLAR_LATITUDE_DEG < 90.0


def test_the_grid_covers_the_world_exactly() -> None:
    """The cell counts and the cell size have to agree, or a band is missing."""
    assert LAT_CELLS * CELL_DEG == 180.0
    assert LON_CELLS * CELL_DEG == 360.0


def test_a_repeated_ident_collapses_to_one_airport() -> None:
    """The table's ``UNIQUE`` constraint, mirrored in memory."""
    index = AirportIndex(
        [airport("DUPE", 10.0, 10.0, name="First"), airport("DUPE", 11.0, 11.0, name="Second")]
    )

    found = index.get("DUPE")
    assert found is not None
    assert found.name == "Second"
    assert index.size == 1


# ---------------------------------------------------------- names by ident


def test_a_known_ident_names_its_field(index: AirportIndex) -> None:
    """The lookup behind ``route.origin_name`` (``docs/API.md`` §2.6)."""
    assert index.name_for("KBFI") == "Boeing Field"


def test_an_ident_the_dataset_does_not_carry_names_nothing(index: AirportIndex) -> None:
    assert index.name_for("ZZZZ") is None


def test_an_empty_index_names_nothing() -> None:
    """The state of every install until an airports import has run."""
    assert AirportIndex().name_for("KBFI") is None


def test_an_iata_code_is_a_fallback_key(index: AirportIndex) -> None:
    """A route ident is ICAO where the provider had one and IATA otherwise
    (:mod:`flightsite.enrichment.aerodatabox`), so both have to answer."""
    assert index.name_for("BFI") == "Boeing Field"


def test_an_ident_is_matched_case_insensitively(index: AirportIndex) -> None:
    assert index.name_for("kbfi") == "Boeing Field"


def test_a_duplicated_iata_code_resolves_to_the_first_row_loaded() -> None:
    """Deterministic across rebuilds — the repository loads in ident order."""
    duplicated = AirportIndex(
        [
            airport("AAAA", 10.0, 10.0, name="First", iata="DUP"),
            airport("BBBB", 11.0, 11.0, name="Second", iata="DUP"),
        ]
    )

    assert duplicated.name_for("DUP") == "First"
