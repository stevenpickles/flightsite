"""The runtime vocabulary and the schema's ``CHECK`` must say the same thing.

``docs/API.md`` §2.8 and ``docs/DATA_MODEL.md`` §2.5 are authoritative for
these spellings, and each appears twice in the codebase: as a ``StrEnum`` in
:mod:`flightsite.sightings.vocabulary`, and as a SQL predicate in
:mod:`flightsite.db.models` (which cannot import the enum — ``sightings``
depends on ``db``, not the reverse). Two spellings of the same list drift; this
test is what stops them.

The position-source codes are the same problem in a different shape: they are
an *on-disk format*, so a renumbering would silently reinterpret every packed
track already written.
"""

from __future__ import annotations

import re

import pytest

from flightsite.db.models import CLOSURE_REASON_CHECK, SIGHTING_EVENT_TYPE_CHECK
from flightsite.ingest import PositionSource
from flightsite.sightings import (
    EMERGENCY_SQUAWKS,
    ClosureReason,
    PositionSourceCode,
    SightingEventType,
)
from flightsite.sightings.vocabulary import position_source_code, position_source_name

#: The canonical lists, copied from the documents by hand on purpose: a test
#: that derived them from the code could not detect the code being wrong.
CANONICAL_CLOSURE_REASONS = {"gap_timeout", "shutdown_recovery", "data_reset"}

CANONICAL_EVENT_TYPES = {
    "callsign_change",
    "squawk_change",
    "emergency_start",
    "emergency_end",
    "route_enriched",
    "classification_available",
    "alert_matched",
    "alert_severity_upgraded",
}

#: ``docs/DATA_MODEL.md`` §2.4 states the numbering inline with the column.
CANONICAL_POSITION_SOURCE_CODES = {"adsb": 0, "mlat": 1, "none": 2, "other": 3}


def values_in(check: str) -> set[str]:
    """The quoted literals inside a SQL ``IN (...)`` predicate."""
    return set(re.findall(r"'([^']+)'", check))


def test_the_closure_reasons_are_the_canonical_ones() -> None:
    assert {reason.value for reason in ClosureReason} == CANONICAL_CLOSURE_REASONS


def test_the_schema_check_accepts_exactly_those_values() -> None:
    assert values_in(CLOSURE_REASON_CHECK) == CANONICAL_CLOSURE_REASONS


def test_the_emergency_squawks_are_the_three_international_codes() -> None:
    # 7500 unlawful interference, 7600 radio failure, 7700 general emergency.
    assert set(EMERGENCY_SQUAWKS) == {"7500", "7600", "7700"}


def test_the_sighting_event_types_are_the_canonical_ones() -> None:
    assert {event.value for event in SightingEventType} == CANONICAL_EVENT_TYPES


def test_the_event_schema_check_accepts_exactly_those_values() -> None:
    assert values_in(SIGHTING_EVENT_TYPE_CHECK) == CANONICAL_EVENT_TYPES


def test_the_position_source_codes_are_the_stored_numbering() -> None:
    # These numbers are a storage format, not an implementation detail: a
    # packed track written today is decoded by every later version.
    assert {source.name.lower(): source.value for source in PositionSourceCode} == {
        "adsb": 0,
        "mlat": 1,
        "none": 2,
        "other": 3,
    }


def test_position_sources_round_trip_through_their_codes() -> None:
    for name, code in CANONICAL_POSITION_SOURCE_CODES.items():
        source: PositionSource = name  # type: ignore[assignment]
        assert position_source_code(source) == code
        assert position_source_name(code) == name


def test_an_unknown_position_source_code_is_refused() -> None:
    # Guessing at a code a newer build wrote would mislabel the provenance of
    # a stored fix, which DATA_MODEL §8 makes a per-point fact.
    with pytest.raises(ValueError, match="unknown position source code"):
        position_source_name(99)
