"""Canonical sighting vocabulary (``docs/API.md`` §2.8).

The API document is authoritative for these spellings; the SQL ``CHECK``
predicates in :mod:`flightsite.db.models` carry the same list, and
``tests/sightings/test_vocabulary.py`` asserts the two never drift apart.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ClosureReason(StrEnum):
    """Why a sighting was closed.

    Only :attr:`GAP_TIMEOUT` is produced in this slice. The other two exist in
    the vocabulary — and in the schema's ``CHECK`` — because the value must be
    stable before the code that writes it lands: unclean-shutdown recovery
    writes :attr:`SHUTDOWN_RECOVERY` in slice 053, and the application reset
    writes :attr:`DATA_RESET` in slice 045.
    """

    #: The aircraft was absent for the configured closure gap (SPEC §18).
    GAP_TIMEOUT = "gap_timeout"
    #: Startup repaired a sighting left open by an unclean shutdown (slice 053).
    SHUTDOWN_RECOVERY = "shutdown_recovery"
    #: The user reset FlightSite's data while the sighting was open (slice 045).
    DATA_RESET = "data_reset"


#: Squawk codes that mean the flight declared an emergency: 7500 unlawful
#: interference, 7600 radio failure, 7700 general emergency. Seeing any of them
#: at any point in a sighting sets ``had_emergency`` — a fact about the flight
#: that must survive the squawk changing back, which ``squawk_last`` alone
#: would lose.
#:
#: This is the *record* of the emergency, not an alert: rule evaluation,
#: severities and notifications are slice 038's.
EMERGENCY_SQUAWKS: Final[frozenset[str]] = frozenset({"7500", "7600", "7700"})


__all__ = ["EMERGENCY_SQUAWKS", "ClosureReason"]
