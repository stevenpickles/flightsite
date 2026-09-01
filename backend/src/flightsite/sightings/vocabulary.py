"""Canonical sighting vocabulary (``docs/API.md`` §2.8).

The API document is authoritative for these spellings; the SQL ``CHECK``
predicates in :mod:`flightsite.db.models` carry the same list, and
``tests/sightings/test_vocabulary.py`` asserts the two never drift apart.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final

from flightsite.ingest import PositionSource


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

#: ``docs/API.md`` §2.8's severity ladder, lowest first — the ordering behind
#: ``sightings.max_alert_severity`` (slice 038's column on this slice's table).
#:
#: Spelled here rather than imported from
#: :class:`flightsite.alerts.vocabulary.AlertSeverity`, which owns the domain
#: enum, because the dependency runs one way: :mod:`flightsite.alerts` consumes
#: the persistence worker, so this package must not reach back into it.
#: ``tests/alerts/test_vocabulary.py`` asserts the two agree, which is the same
#: answer this module already gives for :data:`EMERGENCY_SQUAWKS` and the
#: ``CHECK`` predicates in :mod:`flightsite.db.models`.
ALERT_SEVERITIES: Final[tuple[str, ...]] = ("info", "interesting", "high", "critical")


def alert_severity_rank(severity: str) -> int:
    """Position of ``severity`` on the ladder, ``0`` lowest.

    Raises:
        ValueError: on a value outside the ladder. Guessing an order for an
            unrecognized severity would let a bad value silently outrank — or
            be outranked by — a real one, and the column's ``CHECK`` means such
            a value can only have come from a caller, never from storage.
    """
    try:
        return ALERT_SEVERITIES.index(severity)
    except ValueError:
        raise ValueError(f"unknown alert severity: {severity!r}") from None


def outranks_severity(candidate: str, current: str | None) -> bool:
    """Whether ``candidate`` is *strictly* higher on the ladder than ``current``.

    ``None`` means nothing is standing yet, which anything outranks. A tie does
    not: SPEC §48 allows a further notification for a *higher*-priority
    condition, so equal severities must not read as an upgrade.
    """
    if current is None:
        return True
    return alert_severity_rank(candidate) > alert_severity_rank(current)


class SightingEventType(StrEnum):
    """A meaningful change within a sighting (``docs/DATA_MODEL.md`` §2.5).

    The first four are emitted by this slice, from values the live stream
    already carries. The rest belong to the slices that produce the facts they
    describe — route enrichment (026), classification (024) and alert
    evaluation (038) — and are listed here, and in the schema's ``CHECK``, so
    the vocabulary is fixed before the code that writes it lands.

    What is deliberately *not* here: one event per decoder snapshot. SPEC §52
    asks for meaningful changes, and a table that grew with the update rate
    would be a second track table with none of the packing.
    """

    #: The flight began transmitting a different callsign.
    CALLSIGN_CHANGE = "callsign_change"
    #: The transponder code changed.
    SQUAWK_CHANGE = "squawk_change"
    #: An emergency squawk (:data:`EMERGENCY_SQUAWKS`) appeared.
    EMERGENCY_START = "emergency_start"
    #: The squawk left the emergency set again.
    EMERGENCY_END = "emergency_end"
    #: Route enrichment answered for this sighting (slice 026).
    ROUTE_ENRICHED = "route_enriched"
    #: Classification became available for the airframe (slice 024).
    CLASSIFICATION_AVAILABLE = "classification_available"
    #: An alert rule matched (slice 038).
    ALERT_MATCHED = "alert_matched"
    #: A matched alert was upgraded to a higher severity (slice 038).
    ALERT_SEVERITY_UPGRADED = "alert_severity_upgraded"


class PositionSourceCode(IntEnum):
    """Integer codes for ``position_source`` on the hot track structures.

    ``docs/DATA_MODEL.md`` §Conventions puts ``TEXT`` enums on low-volume
    tables and **integer codes** on the high-volume ones — the checkpoint table
    and the packed track encoding, where the difference is bytes per point
    multiplied by a multi-year history. The string forms in ``docs/API.md``
    §2.8 stay the API's vocabulary; these codes never leave storage.

    The numbering is part of the on-disk format: a packed track written today
    is decoded by every later version, so codes are appended, never
    renumbered.
    """

    ADSB = 0
    MLAT = 1
    NONE = 2
    OTHER = 3


_CODE_BY_SOURCE: Final[MappingProxyType[str, PositionSourceCode]] = MappingProxyType(
    {
        "adsb": PositionSourceCode.ADSB,
        "mlat": PositionSourceCode.MLAT,
        "none": PositionSourceCode.NONE,
        "other": PositionSourceCode.OTHER,
    }
)

_SOURCE_BY_CODE: Final[MappingProxyType[int, PositionSource]] = MappingProxyType(
    {
        PositionSourceCode.ADSB.value: "adsb",
        PositionSourceCode.MLAT.value: "mlat",
        PositionSourceCode.NONE.value: "none",
        PositionSourceCode.OTHER.value: "other",
    }
)


def position_source_code(source: PositionSource) -> int:
    """The stored integer code for a canonical ``position_source`` string."""
    code = _CODE_BY_SOURCE.get(source)
    if code is None:  # pragma: no cover - unreachable while the Literal holds
        raise ValueError(f"unknown position source: {source!r}")
    return code.value


def position_source_name(code: int) -> PositionSource:
    """The canonical ``position_source`` string for a stored integer code.

    Raises:
        ValueError: on a code this build does not know. A track written by a
            newer FlightSite is not decoded by guessing — the same refusal the
            packed encoding applies to an unknown ``encoding_version``.
    """
    source = _SOURCE_BY_CODE.get(code)
    if source is None:
        raise ValueError(f"unknown position source code: {code!r}")
    return source


__all__ = [
    "ALERT_SEVERITIES",
    "EMERGENCY_SQUAWKS",
    "ClosureReason",
    "PositionSourceCode",
    "SightingEventType",
    "alert_severity_rank",
    "outranks_severity",
    "position_source_code",
    "position_source_name",
]
