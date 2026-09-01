"""Operator normalization: what counts as the same operator, and what does not.

SPEC §38 asks for two things that pull in opposite directions — preserve the
exact operator string, and group operators that are the same organisation
spelled differently. The resolution is a normalized *comparison* key that is
never stored, and these tests are mostly about where that key's tolerance
stops.
"""

from __future__ import annotations

import pytest

from flightsite.classification.operators import (
    OperatorDirectory,
    default_directory,
    group_names,
    match_key,
    slugs,
)
from flightsite.classification.specs import OperatorGroupSpec, OperatorPattern
from flightsite.classification.vocabulary import Confidence, EvidenceBasis, GroupKind

# ------------------------------------------------------------------ the key


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Delta Air Lines", "delta air lines"),
        ("DELTA AIR LINES", "delta air lines"),
        ("Delta Air Lines, Inc.", "delta air lines"),
        ("  Delta   Air  Lines  ", "delta air lines"),
        ("Delta Air Lines LLC", "delta air lines"),
        ("Aeroméxico", "aeromexico"),
        ("Türk Hava Yolları", "turk hava yollari"),  # noqa: RUF001
        ("easyJet", "easyjet"),
        ("Jet2.com", "jet2 com"),
        ("", ""),
        ("   ", ""),
        ("...", ""),
    ],
)
def test_the_comparison_key_folds_only_spelling(written: str, expected: str) -> None:
    assert match_key(written) == expected


def test_stripping_a_legal_suffix_never_empties_the_key() -> None:
    """An operator whose whole name is a suffix word keeps it.

    Otherwise every such operator would normalize to ``""`` and collide with
    every other one — which is the failure mode that turns a normalization into
    a wrong answer.
    """
    assert match_key("SAS") == "sas"
    assert match_key("Co") == "co"


def test_two_spellings_of_one_operator_are_one_key_but_two_strings() -> None:
    """The whole of SPEC §38 in one assertion."""
    spellings = ("Delta Air Lines, Inc.", "DELTA AIR LINES INC")

    assert match_key(spellings[0]) == match_key(spellings[1])
    assert len(set(spellings)) == 2


# ------------------------------------------------------------------ matching


def test_an_exact_name_match_is_high_confidence(toy_directory: OperatorDirectory) -> None:
    match = toy_directory.match("Toy Airline Inc")

    assert match is not None
    assert match.group.slug == "toy-airline"
    assert match.basis is EvidenceBasis.OPERATOR_NAME
    assert match.confidence is Confidence.HIGH


def test_a_phrase_match_is_one_band_lower(toy_directory: OperatorDirectory) -> None:
    match = toy_directory.match("Clark County Sheriff's Office")

    assert match is not None
    assert match.group.slug == "toy-police"
    assert match.basis is EvidenceBasis.OPERATOR_PATTERN
    assert match.confidence is Confidence.MEDIUM
    assert match.matched == "sheriff"


def test_a_phrase_matches_whole_words_and_not_substrings() -> None:
    """The mistake that gives a classifier confident nonsense.

    ``"police"`` inside ``"Policentro"`` is a substring and not a word, and a
    substring match here would put a charter company in the law-enforcement
    filter.
    """
    directory = OperatorDirectory(
        (
            OperatorGroupSpec(
                slug="police", name="Police", kind=GroupKind.LAW_ENFORCEMENT, law_enforcement=True
            ),
        ),
        (OperatorPattern("police", "police"),),
    )

    assert directory.match("Policentro Aviation") is None
    assert directory.match("Kent Police") is not None


def test_an_unmatched_operator_is_simply_ungrouped(toy_directory: OperatorDirectory) -> None:
    assert toy_directory.match("Nobody In Particular") is None
    assert toy_directory.match(None) is None
    assert toy_directory.match("   ") is None


def test_an_exact_name_wins_over_a_phrase_that_also_applies() -> None:
    directory = OperatorDirectory(
        (
            OperatorGroupSpec(
                slug="named",
                name="Named",
                kind=GroupKind.OTHER,
                operators=("City Police Air Support",),
            ),
            OperatorGroupSpec(slug="generic", name="Generic", kind=GroupKind.LAW_ENFORCEMENT),
        ),
        (OperatorPattern("police", "generic"),),
    )

    match = directory.match("City Police Air Support")

    assert match is not None
    assert match.group.slug == "named"


# ------------------------------------------------------------------ callsigns


@pytest.mark.parametrize("callsign", ["TOY1", "TOY1234", "toy42", " TOY42 ", "TOY42A"])
def test_a_flight_identification_yields_its_designator(
    toy_directory: OperatorDirectory, callsign: str
) -> None:
    match = toy_directory.match_callsign(callsign)

    assert match is not None
    assert match.group.slug == "toy-airline"
    assert match.basis is EvidenceBasis.CALLSIGN
    assert match.confidence is Confidence.LOW


@pytest.mark.parametrize(
    "callsign",
    [
        "N738AB",  # a registration flown as the callsign
        "TOYOTA",  # letters all the way down: no flight number
        "TO42",  # two-letter prefix: an IATA code, not an ICAO designator
        "TOY",  # designator with nothing after it
        "1234",
        "",
        "   ",
    ],
)
def test_anything_but_a_flight_identification_matches_nothing(
    toy_directory: OperatorDirectory, callsign: str
) -> None:
    assert toy_directory.match_callsign(callsign) is None


def test_an_unknown_designator_matches_nothing(toy_directory: OperatorDirectory) -> None:
    assert toy_directory.match_callsign("ZZZ100") is None
    assert toy_directory.match_callsign(None) is None


# -------------------------------------------------------------- the directory


def test_group_ids_follow_the_slugs_not_the_file_order() -> None:
    """Ids are written into stored rows, so reordering the data file must not move them."""
    groups = (
        OperatorGroupSpec(slug="zulu", name="Zulu", kind=GroupKind.OTHER),
        OperatorGroupSpec(slug="alpha", name="Alpha", kind=GroupKind.OTHER),
    )

    forwards = OperatorDirectory(groups)
    backwards = OperatorDirectory(tuple(reversed(groups)))

    assert forwards.group_id("alpha") == backwards.group_id("alpha") == 1
    assert forwards.group_id("zulu") == backwards.group_id("zulu") == 2


def test_group_rows_are_id_ordered_and_complete(toy_directory: OperatorDirectory) -> None:
    rows = toy_directory.group_rows()

    assert [row["id"] for row in rows] == [1, 2, 3, 4]
    assert [row["slug"] for row in rows] == sorted(slugs(toy_directory.groups))


def test_curated_operator_rows_carry_the_exact_spellings(
    toy_directory: OperatorDirectory,
) -> None:
    """``operators.name`` is the exact string, never the comparison key."""
    names = {str(row["name"]) for row in toy_directory.curated_operator_rows()}

    assert "Toy Airline Inc" in names
    assert "toy airline" not in names


def test_group_names_map_ids_to_the_prose_the_api_publishes(
    toy_directory: OperatorDirectory,
) -> None:
    names = group_names(toy_directory)

    assert names[toy_directory.group_id("toy-police")] == "Toy Police"


def test_the_default_directory_is_built_once() -> None:
    """One id assignment per process: the import writes ids the cache reads back."""
    assert default_directory() is default_directory()


# ------------------------------------------------- inconsistent data is refused


def test_a_duplicate_slug_is_refused() -> None:
    group = OperatorGroupSpec(slug="same", name="One", kind=GroupKind.OTHER)

    with pytest.raises(ValueError, match="duplicate operator group slug"):
        OperatorDirectory((group, group))


def test_a_name_claimed_by_two_groups_is_refused() -> None:
    """A data bug that would otherwise resolve by dict-insertion order."""
    with pytest.raises(ValueError, match="operator name"):
        OperatorDirectory(
            (
                OperatorGroupSpec(
                    slug="one", name="One", kind=GroupKind.OTHER, operators=("Shared Air",)
                ),
                OperatorGroupSpec(
                    slug="two", name="Two", kind=GroupKind.OTHER, operators=("SHARED AIR INC",)
                ),
            )
        )


def test_a_designator_claimed_by_two_groups_is_refused() -> None:
    with pytest.raises(ValueError, match="callsign designator"):
        OperatorDirectory(
            (
                OperatorGroupSpec(slug="one", name="One", kind=GroupKind.OTHER, callsigns=("ABC",)),
                OperatorGroupSpec(slug="two", name="Two", kind=GroupKind.OTHER, callsigns=("ABC",)),
            )
        )


def test_a_pattern_naming_an_unknown_group_is_refused() -> None:
    with pytest.raises(ValueError, match="names unknown group"):
        OperatorDirectory(
            (OperatorGroupSpec(slug="one", name="One", kind=GroupKind.OTHER),),
            (OperatorPattern("sheriff", "nowhere"),),
        )


def test_two_spellings_in_one_group_are_not_a_conflict() -> None:
    """Listing both ``Aeroméxico`` and ``Aeromexico`` is documentation, not a bug."""
    directory = OperatorDirectory(
        (
            OperatorGroupSpec(
                slug="one",
                name="One",
                kind=GroupKind.OTHER,
                operators=("Aeroméxico", "Aeromexico"),
            ),
        )
    )

    assert directory.match("AEROMEXICO") is not None
