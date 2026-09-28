"""The shared ``q`` rules in :mod:`flightsite.api.search` (slice 083).

The endpoint tests (:mod:`tests.api.test_list_search_api`) prove the rules
hold end to end; these pin the two pure functions they are built from, where
an edge case is cheaper to enumerate than to seed.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import column
from sqlalchemy.dialects import sqlite

from flightsite.api.search import like_prefix, normalize_query, prefix_match


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("\t\n", None),
        ("baw", "baw"),
        ("  G-EZ ", "G-EZ"),
        ("Delta Air", "Delta Air"),
    ],
)
def test_normalize_query(raw: str | None, expected: str | None) -> None:
    assert normalize_query(raw) == expected


@pytest.mark.parametrize(
    ("term", "pattern"),
    [
        ("BAW", "BAW%"),
        ("N_1", "N\\_1%"),
        ("50%", "50\\%%"),
        ("a\\b", "a\\\\b%"),
        ("\\_", "\\\\\\_%"),
    ],
)
def test_like_prefix_escapes_every_wildcard(term: str, pattern: str) -> None:
    assert like_prefix(term) == pattern


@pytest.mark.parametrize("term", ["N_", "N%", "N\\", "N\\_", "n_", "_", "%", "\\"])
def test_like_prefix_matches_exactly_the_literal_prefix(term: str) -> None:
    """Checked against SQLite itself, not against a model of it."""
    values = ["N_1", "N%2", "N\\3", "N\\_4", "NX5", "N6", "_7", "%8", "\\9"]
    with sqlite3.connect(":memory:") as connection:
        matched = {
            value
            for value in values
            if connection.execute(
                "SELECT ? LIKE ? ESCAPE '\\'", (value, like_prefix(term))
            ).fetchone()[0]
        }

    assert matched == {value for value in values if value.lower().startswith(term.lower())}


@pytest.mark.parametrize(
    ("fold", "low", "collated"),
    [
        ("nocase", "Ab", True),
        ("lower", "ab", False),
        ("upper", "AB", False),
    ],
)
def test_prefix_match_ranges_in_the_index_collation(fold: str, low: str, collated: bool) -> None:
    """The range folds the query for a BINARY index, or collates for a NOCASE one."""
    expression = prefix_match(column("x"), "Ab", fold=fold)  # type: ignore[arg-type]
    compiled = expression.compile(dialect=sqlite.dialect())
    sql = str(compiled)

    assert ("NOCASE" in sql) is collated
    assert "LIKE" in sql
    bounds = [value for value in compiled.params.values() if value != "Ab%"]
    assert bounds == [low, low + "\U0010ffff"]
