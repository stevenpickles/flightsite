"""The entry-kind vocabulary, and normalization/validation per kind.

SPEC §42 lists five reference kinds a watchlist entry may take: ICAO hex,
registration, aircraft type, operator, category/tag. :class:`WatchlistEntryKind`
is that list, spelled to agree with
``docs/DATA_MODEL.md`` §4.1's ``watchlist_entries.kind`` ``CHECK`` constraint —
:data:`flightsite.db.models.WATCHLIST_ENTRY_KIND_CHECK` is generated from a
literal copy of these values (``db`` cannot import this package, the same
constraint every other cross-checked vocabulary in this codebase is under), and
a test asserts the two agree.

Every kind has one normalization rule and one validation rule, both applied
once, at write time (`create`/`add_entry`), never at match time. Storing
already-normalized values is what lets
:mod:`flightsite.watchlists.matcher` compare a live aircraft's own normalized
fields against the index with plain dict lookups rather than re-normalizing
on every one of a few hundred aircraft, a few times a second.

* ``icao24`` — six lower-case hex digits, the same shape the live picture's
  own ``icao`` field takes (``docs/API.md`` §3.3).
* ``registration``/``type_code`` — upper-cased tail numbers and ICAO type
  designators. The regexes are deliberately permissive (worldwide registration
  formats vary a great deal, from ``N12345`` to ``G-ABCD`` to ``VH-ABC``) —
  the goal is to catch obviously-wrong input (blank, punctuation-only,
  absurdly long), not to enumerate every national scheme.
* ``operator`` — free text, matched against the resolved operator name
  (:attr:`~flightsite.metadata.precedence.ResolvedMetadata.operator_name`)
  case-insensitively by upper-casing both sides. Not restricted to a closed
  vocabulary — an operator name is whatever a metadata source spells it as.
* ``category`` — must be one of
  :class:`~flightsite.classification.vocabulary.MissionCategory`'s values,
  excluding ``unknown``: watchlisting "every aircraft classification could not
  place" is not a meaningful membership rule, and it would silently swallow
  every aircraft with no evidence at all rather than naming a real category.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from flightsite.classification.vocabulary import MissionCategory


class WatchlistEntryKind(StrEnum):
    """Which live-aircraft field one entry matches against (SPEC §42)."""

    ICAO24 = "icao24"
    REGISTRATION = "registration"
    TYPE_CODE = "type_code"
    OPERATOR = "operator"
    CATEGORY = "category"


class WatchlistValueError(ValueError):
    """Raised when an entry's ``value`` fails its kind's format rule.

    A plain :class:`ValueError` subclass rather than a bespoke hierarchy: the
    internal API's request schemas (:mod:`flightsite.watchlists.schemas`)
    raise it from a Pydantic field validator, which Pydantic re-wraps into its
    own ``ValidationError`` — the caller never sees this type directly, but it
    is what makes the message kind-specific rather than a generic "invalid
    value".
    """


#: Six lower-case hex digits — ``docs/API.md`` §3.3's own ``icao`` pattern.
_ICAO24_RE: Final = re.compile(r"^[0-9a-f]{6}$")

#: Permissive tail-number shape: alphanumerics and hyphens, 2-10 characters,
#: not starting or ending on a hyphen. Covers ``N12345``, ``G-ABCD``,
#: ``D-ABCD``, ``VH-ABC``, ``C-FABC`` and similar worldwide schemes.
_REGISTRATION_RE: Final = re.compile(r"^[A-Z0-9](?:[A-Z0-9-]{0,8}[A-Z0-9])?$")

#: ICAO type designators are 2-4 alphanumerics in practice (``B738``,
#: ``A320``, ``C172``, ``EC35``, ``H60``); a slightly wider ceiling absorbs
#: any designator this codebase has not seen without accepting free text.
_TYPE_CODE_RE: Final = re.compile(r"^[A-Z0-9]{2,6}$")

#: Every mission category except ``unknown`` — see the module docstring.
VALID_CATEGORY_VALUES: Final[frozenset[str]] = frozenset(
    category.value for category in MissionCategory if category is not MissionCategory.UNKNOWN
)

#: Longest ``value`` any kind accepts, after normalization. Generous for
#: ``operator`` (the only free-text kind) and far above what any real value of
#: the other four kinds needs; it exists to reject paste-a-paragraph input
#: rather than to constrain a real operator name.
MAX_VALUE_LENGTH: Final = 100

#: Longest ``note`` a caller may attach to an entry.
MAX_NOTE_LENGTH: Final = 500

#: Longest a watchlist ``name`` may be.
MAX_NAME_LENGTH: Final = 100

#: Longest a watchlist ``description`` may be.
MAX_DESCRIPTION_LENGTH: Final = 500


def normalize_and_validate(kind: WatchlistEntryKind, raw_value: str) -> str:
    """Normalize ``raw_value`` for ``kind`` and validate its format.

    Returns the normalized value to store. Raises :class:`WatchlistValueError`
    with a message naming what was wrong — the internal API surfaces it
    verbatim in its ``422`` response (``docs/API.md`` §5).
    """
    stripped = raw_value.strip()
    if not stripped:
        raise WatchlistValueError(f"a {kind.value} value must not be blank")
    if len(stripped) > MAX_VALUE_LENGTH:
        raise WatchlistValueError(
            f"a {kind.value} value must be at most {MAX_VALUE_LENGTH} characters"
        )

    if kind is WatchlistEntryKind.ICAO24:
        value = stripped.lower()
        if not _ICAO24_RE.match(value):
            raise WatchlistValueError(
                "an icao24 value must be exactly six hex digits (e.g. 'ae1463')"
            )
        return value

    if kind is WatchlistEntryKind.REGISTRATION:
        value = stripped.upper()
        if not _REGISTRATION_RE.match(value):
            raise WatchlistValueError(
                "a registration value must look like a tail number (e.g. 'N12345', 'G-ABCD')"
            )
        return value

    if kind is WatchlistEntryKind.TYPE_CODE:
        value = stripped.upper()
        if not _TYPE_CODE_RE.match(value):
            raise WatchlistValueError(
                "a type_code value must be an ICAO type designator (e.g. 'B738', 'A320')"
            )
        return value

    if kind is WatchlistEntryKind.OPERATOR:
        # Free text: any non-blank string within the length ceiling above is
        # accepted, upper-cased so matching is case-insensitive (see the
        # module docstring).
        return stripped.upper()

    # kind is CATEGORY (the enum has no other member, but mypy cannot see
    # that from a chain of `is` checks over a StrEnum).
    value = stripped.lower()
    if value not in VALID_CATEGORY_VALUES:
        allowed = ", ".join(sorted(VALID_CATEGORY_VALUES))
        raise WatchlistValueError(f"a category value must be one of: {allowed}")
    return value


def normalize_optional_text(raw: str | None, *, field_name: str, max_length: int) -> str | None:
    """A trimmed, length-checked optional field, or ``None`` for a blank one.

    Shared by a watchlist's ``description`` and an entry's ``note`` — both are
    optional free text with nothing else to validate, so one function is both
    implementations rather than two copies of the same three lines.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if len(stripped) > max_length:
        raise WatchlistValueError(f"a {field_name} must be at most {max_length} characters")
    return stripped


def normalize_note(raw_note: str | None) -> str | None:
    """A trimmed, length-checked entry ``note``, or ``None`` for a blank one."""
    return normalize_optional_text(raw_note, field_name="note", max_length=MAX_NOTE_LENGTH)


def normalize_watchlist_name(raw_name: str) -> str:
    """A trimmed, length-checked, non-blank watchlist ``name``.

    Uniqueness is not this function's concern — that is a database-wide
    property :mod:`flightsite.watchlists.repository` enforces, not something
    a value on its own can validate.
    """
    stripped = raw_name.strip()
    if not stripped:
        raise WatchlistValueError("a watchlist name must not be blank")
    if len(stripped) > MAX_NAME_LENGTH:
        raise WatchlistValueError(f"a watchlist name must be at most {MAX_NAME_LENGTH} characters")
    return stripped


def normalize_description(raw_description: str | None) -> str | None:
    """A trimmed, length-checked watchlist ``description``, or ``None``."""
    return normalize_optional_text(
        raw_description, field_name="description", max_length=MAX_DESCRIPTION_LENGTH
    )


__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_NOTE_LENGTH",
    "MAX_VALUE_LENGTH",
    "VALID_CATEGORY_VALUES",
    "WatchlistEntryKind",
    "WatchlistValueError",
    "normalize_and_validate",
    "normalize_description",
    "normalize_note",
    "normalize_optional_text",
    "normalize_watchlist_name",
]
