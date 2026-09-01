"""The value objects nearest-airport context is expressed in.

Kept in their own module so the API serializer, the persistence worker and the
inference itself can share them without any of the three importing the service
that produces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InferredPhase(StrEnum):
    """A locally inferred flight phase relative to a nearby field.

    Two values and no third. ``docs/DATA_MODEL.md`` §2.3 constrains
    ``sightings.inferred_phase`` to exactly these, and the absence of a phase is
    represented by ``None`` rather than by an ``unknown`` member: SPEC §39's
    rule is that weak evidence produces *no* answer, and a vocabulary word for
    "no answer" invites it being displayed as one.

    The values are the storage and API vocabulary. The user-facing wording —
    *likely arriving*, and the "inferred" label SPEC §41 requires — belongs to
    the UI, which is where a heuristic's hedging is legible.
    """

    ARRIVING = "arriving"
    DEPARTING = "departing"


@dataclass(frozen=True, slots=True)
class AirportContext:
    """What FlightSite can say about the field an aircraft is near.

    Immutable, and produced whole: the service replaces an aircraft's context
    rather than mutating one, so a reader holding a context can never see it
    change under itself mid-serialization.

    ``phase`` is ``None`` far more often than not, and that is the design.
    Nearest-airport is a measurement — the aircraft is 4.1 nm from KBFI, which
    is either true or not — while a phase is an inference about intent, and it
    is only offered when the kinematics leave no reasonable second reading
    (:mod:`flightsite.airports.inference`).
    """

    ident: str
    name: str
    distance_nm: float
    phase: InferredPhase | None = None


__all__ = ["AirportContext", "InferredPhase"]
