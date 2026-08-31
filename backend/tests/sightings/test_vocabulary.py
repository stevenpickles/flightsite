"""The runtime vocabulary and the schema's ``CHECK`` must say the same thing.

``docs/API.md`` §2.8 is authoritative for these spellings, and they appear
twice in the codebase: as :class:`~flightsite.sightings.ClosureReason` and as a
SQL predicate on ``sightings``. Two spellings of the same list drift; this test
is what stops them.
"""

from __future__ import annotations

import re

from flightsite.db.models import CLOSURE_REASON_CHECK
from flightsite.sightings import EMERGENCY_SQUAWKS, ClosureReason

#: The canonical list, copied from ``docs/API.md`` §2.8 by hand on purpose:
#: a test that derived it from the code could not detect the code being wrong.
CANONICAL_CLOSURE_REASONS = {"gap_timeout", "shutdown_recovery", "data_reset"}


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
