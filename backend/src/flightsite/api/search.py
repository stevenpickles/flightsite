"""List-scoped prefix search — the ``q`` parameter on ``/aircraft`` and ``/sightings``.

Roadmap slice 083 (issue #226): find an aircraft or a sighting from its own
list page by the identifier you remember. This is deliberately **not** a
global search. SPEC §37 scopes search to filtering the list a user is already
looking at, and a cross-entity search box (one query answering aircraft,
sightings, alerts and places at once) is a deferred §79 non-goal. Each list
endpoint therefore owns its own ``q`` and decides which of *its* columns it
matches; this module only supplies the shared rules for what a query means.

What a query means
------------------

* **Trimmed, and empty means absent.** ``" "`` is not a request to match
  every row that starts with a space; :func:`normalize_query` returns
  ``None`` for it, and the endpoint behaves exactly as if ``q`` had been left
  off.
* **A prefix, not a substring.** ``BAW`` finds ``BAW123``; ``123`` does not.
  A prefix is what a person remembers of an identifier (the start of a
  registration, the airline part of a callsign), and it is the only shape of
  match an ordinary B-tree index can answer without reading the whole table.
* **ASCII case-insensitive.** ``g-ab`` finds ``G-ABCD``. SQLite's ``LIKE``
  and its ``NOCASE`` collation both fold ASCII letters only, and every
  identifier this searches is ASCII in practice, so the two agree.
* **Literal.** ``%`` and ``_`` in the query match themselves, never "any
  run" or "any character" — :func:`like_prefix` escapes them. A user typing
  ``N_1`` is looking for an underscore, not asking for a pattern language.
* **Bounded.** :data:`MAX_QUERY_LENGTH` characters. No identifier this
  matches is longer (operator names are the longest, and a prefix of one is
  enough), and the cap keeps a query parameter from becoming a payload.

Why a range *and* a ``LIKE``
----------------------------

:func:`prefix_match` emits both ``column >= term AND column < term || U+10FFFF``
and ``column LIKE 'term%' ESCAPE '\\'``. The ``LIKE`` is the exact
definition of the match. The range is what lets SQLite answer it from an
index: it is the same rewrite SQLite's own LIKE optimization performs, spelled
out so it does not depend on which SQLite release the runtime image links
(the optimization's handling of an ``ESCAPE`` clause has changed across
releases, and the container's Debian SQLite is older than a developer's).
The range is a superset of the ``LIKE`` — every string with the prefix sorts
between the two bounds — so adding it can narrow what is read but never
change what matches.

The range has to be taken in the same collation as the index it is meant to
use. :data:`Fold` names the three this codebase needs: ``nocase`` for a
column indexed ``COLLATE NOCASE`` (rev 0018), and ``lower``/``upper`` for a
column whose stored values are already case-normalized and whose ordinary
``BINARY`` index is therefore usable once the *query* is folded the same way —
``aircraft.icao24`` (always lowercase hex) and the resolved ICAO type
designator (always upper case, :mod:`flightsite.metadata.records`).
"""

from __future__ import annotations

from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, and_

#: Longest accepted ``q``, in characters. Validated by the endpoints'
#: ``Query(max_length=...)``, so an over-long query is a 422, not a truncation
#: that would silently search for something the user did not type.
MAX_QUERY_LENGTH: Final = 32

#: The ``LIKE`` escape character :func:`like_prefix` uses.
LIKE_ESCAPE: Final = "\\"

#: The highest Unicode code point: appended to a prefix, it gives an upper
#: bound every string starting with that prefix sorts below.
_TOP: Final = "\U0010ffff"

#: How :func:`prefix_match` folds the query to meet the column's index.
Fold = Literal["nocase", "lower", "upper"]


def normalize_query(raw: str | None) -> str | None:
    """``q`` trimmed, or ``None`` when absent or only whitespace."""
    if raw is None:
        return None
    term = raw.strip()
    return term or None


def like_prefix(term: str) -> str:
    """A ``LIKE`` pattern matching strings that start with ``term``, literally.

    The escape character is escaped first, so a backslash in ``term`` cannot
    turn the escape of a following ``%`` or ``_`` back into a wildcard.
    """
    escaped = (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )
    return f"{escaped}%"


def prefix_match(column: Any, term: str, *, fold: Fold) -> ColumnElement[bool]:
    """``column`` starts with ``term``, case-insensitively — index-served.

    Args:
        column: the column (or mapped attribute) to match.
        term: an already :func:`normalize_query`-ed, non-empty query.
        fold: which index the range should reach — see the module docstring.
            ``nocase`` compares under ``COLLATE NOCASE``; ``lower`` and
            ``upper`` fold the query to the column's stored case and compare
            under the column's own ``BINARY`` collation.
    """
    pattern = like_prefix(term)
    if fold == "nocase":
        keyed: Any = column.collate("NOCASE")
        low = term
    else:
        keyed = column
        low = term.lower() if fold == "lower" else term.upper()
    return and_(
        keyed >= low,
        keyed < low + _TOP,
        column.like(pattern, escape=LIKE_ESCAPE),
    )


__all__ = [
    "LIKE_ESCAPE",
    "MAX_QUERY_LENGTH",
    "Fold",
    "like_prefix",
    "normalize_query",
    "prefix_match",
]
