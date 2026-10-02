"""Metadata for the demo scenario's special-interest airframes (issue #112).

Demo mode's decoder produces kinematics — an ICAO address, a callsign, a
position — and nothing else, because that is all a decoder ever produces. Every
classification FlightSite makes (SPEC §39) is computed instead from *metadata*:
the operator name and type designator an imported registry supplies, run
through :func:`flightsite.classification.engine.classify` and the curated
operator directory. A demo stack imports no registry, so before this module
every demo aircraft classified as unknown, and the shipped ``military``,
``government`` and ``police`` alert templates could never fire in a demo or an
e2e run however much military-looking traffic flew past.

What is added is the missing half, not a shortcut around it. A handful of the
scenario's military, government and police profiles are given a real airframe
identity — a genuine operator name from the curated directory, a real type
designator, a plausible registration — and those rows are written to
``aircraft_metadata`` through the same repository the importer writes through.
Everything downstream is then the ordinary path: precedence resolves the rows,
the promotion's resolution build classifies them, the metadata cache loads the
resolved view when the aircraft appears, and a rule matches on the
classification it finds. Nothing in :mod:`flightsite.classification` or
:mod:`flightsite.alerts` learns that demo mode exists.

Since slice 094 the ordinary categories carry a *type-only* identity as well:
a designator and a model, no operator and no registration — what a registry
knows about an airframe whose operator it does not. That is enough for the
map's type-level silhouette (a 737 is drawn as a 737, a Cessna as a Cessna)
while the classification stays exactly as honest as it would be on a real
receiver: an airliner type with no operator is ``unknown``, a business jet
type is ``business_jet`` at medium confidence, and so on — the real engine
deciding, from the real inputs. Ground traffic and the slice-086 helicopter
are left without any identity on purpose: the first keeps the generic ground
form visible in the demo, the second is the emitter-category fallback's
acceptance case.

Two deliberate choices:

* **The military flag is left unset.** It would be the blunter way to make
  ``military: true`` come out, but it would also publish a claim whose
  provenance is neither ``mictronics`` nor ``faa`` and would therefore be
  reported as ``heuristic``. Letting the curated operator directory make the
  claim is both more honest and a better exercise of the real code: what the
  demo proves is that an operator name classifies, which is what happens on a
  real receiver.
* **The mapping is positional, not random.** Profiles are matched to airframes
  by their order within their category, so the same seed still produces the
  same demo down to which aircraft is a C-17. No new draw is taken from the
  roster's :class:`random.Random`, so the roster itself is byte-for-byte what
  it was. New entries are *appended* to a table for the same reason.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

import structlog

from flightsite.db import Database
from flightsite.db.clock import utc_now_ms
from flightsite.demo.roster import AircraftProfile, Category
from flightsite.metadata.precedence import PrecedenceModel
from flightsite.metadata.records import NormalizedAircraftRecord, normalize_record
from flightsite.metadata.repository import MetadataRepository

logger = structlog.get_logger(__name__)

#: The source name the demo airframes are written under. It is a real row in
#: ``metadata_sources``, so the data is attributed rather than anonymous, and
#: it is deliberately *not* registered in
#: :func:`flightsite.app._build_metadata_registry`: nothing can fetch it, and
#: an ordinary metadata update leaves it alone.
DEMO_SOURCE: Final = "demo"

#: Recorded as the dataset version so the Settings page and diagnostics say
#: where these rows came from rather than showing a blank.
DEMO_DATASET_VERSION: Final = "demo-scenario"


@dataclass(frozen=True, slots=True)
class DemoAirframe:
    """One airframe identity handed to a scenario profile."""

    #: Must match the curated operator directory
    #: (:mod:`flightsite.classification.data.operators`) — either an exact
    #: name or a phrase pattern — or the aircraft will not classify at all.
    #: ``None`` for a type-only identity, which is meant not to.
    operator_name: str | None
    type_code: str
    model: str
    #: ``None`` for a type-only identity: the tables wrap around a category's
    #: profiles, and a shared tail number across several aircraft would look
    #: like a bug rather than a gap.
    registration: str | None


def _typed(type_code: str, model: str) -> DemoAirframe:
    """A type-only identity: what a registry knows when it does not know the
    operator."""
    return DemoAirframe(None, type_code, model, None)


#: Military operators, all of which the curated directory recognises with a
#: ``military`` group, so :func:`~flightsite.classification.engine.classify`
#: reports ``military=True`` at HIGH confidence from the operator alone.
#:
#: The first eight — what a default-population roster reaches — cover every
#: military silhouette the map draws: transport, tanker, an airliner-planform
#: patrol jet, tiltrotor, fighter, bomber and tandem rotor.
MILITARY_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    DemoAirframe("United States Air Force", "C17", "Boeing C-17A Globemaster III", "05-5153"),
    DemoAirframe("United States Air Force", "K35R", "Boeing KC-135R Stratotanker", "62-3552"),
    DemoAirframe("US Navy", "P8", "Boeing P-8A Poseidon", "169329"),
    DemoAirframe("Royal Air Force", "A400", "Airbus A400M Atlas", "ZM415"),
    DemoAirframe("United States Marine Corps", "V22", "Bell Boeing MV-22B Osprey", "168331"),
    DemoAirframe("United States Air Force", "F16", "Lockheed F-16C Fighting Falcon", "91-0352"),
    DemoAirframe("United States Air Force", "B52", "Boeing B-52H Stratofortress", "60-0059"),
    DemoAirframe("United States Army", "H47", "Boeing CH-47F Chinook", "13-08432"),
    DemoAirframe("United States Marine Corps", "F35", "Lockheed F-35B Lightning II", "169590"),
    DemoAirframe("US Navy", "F18", "Boeing F/A-18E Super Hornet", "168875"),
    DemoAirframe("United States Air Force", "E3TF", "Boeing E-3G Sentry", "77-0351"),
    DemoAirframe("Royal Air Force", "EUFI", "Eurofighter Typhoon FGR4", "ZK356"),
    DemoAirframe("United States Air Force", "C130", "Lockheed C-130H Hercules", "92-1532"),
    DemoAirframe("US Navy", "P3", "Lockheed P-3C Orion", "161764"),
)

#: Government operators — ``government=True`` and no military claim, which is
#: the distinction the ``government`` template is about.
GOVERNMENT_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    DemoAirframe("NASA", "GLF5", "Gulfstream G-V", "N95NA"),
    DemoAirframe("NOAA", "P3", "Lockheed WP-3D Orion", "N42RF"),
    DemoAirframe("Federal Aviation Administration", "C560", "Cessna 560 Citation V", "N87"),
    DemoAirframe("Civil Air Patrol", "C182", "Cessna 182T Skylane", "N999CP"),
)

#: Law-enforcement operators. The first two are curated by name; the last two
#: match the directory's whole-word ``police``/``sheriff`` phrase patterns,
#: which is the commoner real-world case and worth having in the scenario.
POLICE_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    DemoAirframe("US Customs and Border Protection", "EC45", "Airbus H145", "N145CB"),
    DemoAirframe("National Police Air Service", "EC35", "Airbus H135", "G-POLC"),
    DemoAirframe("Los Angeles County Sheriff", "B06", "Bell 206L-4 LongRanger", "N950LA"),
    DemoAirframe("Kent Police", "H125", "Airbus H125", "G-KPOL"),
)

#: Scheduled traffic at FL280-410: type only, so the map draws the airliner
#: planforms while the classification stays ``unknown`` — the honest answer
#: for an airliner type with no operator (``classification/data/types.py``).
#: The first dozen cover all three airliner silhouettes.
COMMERCIAL_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    _typed("B738", "Boeing 737-800"),
    _typed("A320", "Airbus A320-214"),
    _typed("B789", "Boeing 787-9 Dreamliner"),
    _typed("B744", "Boeing 747-400F"),
    _typed("A21N", "Airbus A321-271NX"),
    _typed("E175", "Embraer ERJ-175LR"),
    _typed("B77W", "Boeing 777-300ER"),
    _typed("A388", "Airbus A380-841"),
    _typed("CRJ9", "Bombardier CRJ-900LR"),
    _typed("B763", "Boeing 767-300ER"),
    _typed("A359", "Airbus A350-941"),
    _typed("MD11", "McDonnell Douglas MD-11F"),
    _typed("B752", "Boeing 757-200"),
    _typed("BCS3", "Airbus A220-300"),
    _typed("A343", "Airbus A340-313"),
    _typed("B38M", "Boeing 737 MAX 8"),
)

#: The rare-visitor profile flies a business-jet schedule (FL350-450 at
#: 420-500 kt); a purpose-built business jet type classifies as
#: ``business_aviation`` at medium confidence from the type alone.
RARE_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    _typed("GLF6", "Gulfstream G650ER"),
    _typed("GL7T", "Bombardier Global 7500"),
    _typed("FA8X", "Dassault Falcon 8X"),
    _typed("CL35", "Bombardier Challenger 350"),
    _typed("C750", "Cessna 750 Citation X"),
    _typed("E550", "Embraer Legacy 500"),
)

#: The first-ever profile (150-300 kt, 8-22 kft): a twin turboprop.
FIRST_EVER_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (_typed("BE20", "Beechcraft King Air 200"),)

#: MLAT profiles fly general-aviation speeds and altitudes (100-250 kt,
#: 2-15 kft), so they carry the light types — and the two oddities the
#: emitter-category fallback would otherwise be the only route to.
MLAT_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    _typed("C172", "Cessna 172S Skyhawk"),
    _typed("SR22", "Cirrus SR22"),
    _typed("P28A", "Piper PA-28-181 Archer"),
    _typed("BE58", "Beechcraft 58 Baron"),
    _typed("DA42", "Diamond DA42 Twin Star"),
    _typed("C208", "Cessna 208B Grand Caravan"),
    _typed("B350", "Beechcraft King Air 350"),
    _typed("MQ9", "General Atomics MQ-9B SkyGuardian"),
    _typed("DISC", "Schempp-Hirth Discus-2"),
)

#: Which categories carry an airframe identity, and from which table.
#: ``GROUND``, ``MODE_S`` and ``ROTORCRAFT`` carry none — see the module
#: docstring for the first and last; the second never has a position to draw.
AIRFRAMES_BY_CATEGORY: Final[dict[Category, tuple[DemoAirframe, ...]]] = {
    Category.MILITARY: MILITARY_AIRFRAMES,
    Category.GOVERNMENT: GOVERNMENT_AIRFRAMES,
    Category.POLICE: POLICE_AIRFRAMES,
    Category.COMMERCIAL: COMMERCIAL_AIRFRAMES,
    Category.RARE: RARE_AIRFRAMES,
    Category.FIRST_EVER: FIRST_EVER_AIRFRAMES,
    Category.MLAT: MLAT_AIRFRAMES,
}

#: The categories whose identity carries an operator, and so a classification
#: claim. Everything else in :data:`AIRFRAMES_BY_CATEGORY` is type-only.
OPERATED_CATEGORIES: Final[frozenset[Category]] = frozenset(
    {Category.MILITARY, Category.GOVERNMENT, Category.POLICE}
)


def airframe_for(profile: AircraftProfile, ordinal: int) -> DemoAirframe | None:
    """The airframe identity for ``profile``, the ``ordinal``-th of its category.

    ``None`` for every category that carries no identity.
    """
    table = AIRFRAMES_BY_CATEGORY.get(profile.category)
    return None if table is None else table[ordinal % len(table)]


def demo_metadata_records(
    roster: Iterable[AircraftProfile],
) -> tuple[NormalizedAircraftRecord, ...]:
    """One metadata record per scenario airframe that has an identity.

    Deterministic in the roster alone: the same roster always produces the same
    records, in the same order.
    """
    seen: dict[Category, int] = {}
    records: list[NormalizedAircraftRecord] = []
    for profile in roster:
        ordinal = seen.get(profile.category, 0)
        airframe = airframe_for(profile, ordinal)
        if airframe is None:
            continue
        seen[profile.category] = ordinal + 1
        records.append(
            normalize_record(
                icao24=profile.icao,
                registration=airframe.registration,
                type_code=airframe.type_code,
                model=airframe.model,
                operator_name=airframe.operator_name,
                # Left unset on purpose — see the module docstring.
                military_flag=None,
            )
        )
    return tuple(records)


async def seed_demo_metadata(
    database: Database,
    roster: Sequence[AircraftProfile],
    *,
    precedence: PrecedenceModel,
) -> int:
    """Write the scenario's airframe metadata. Returns the row count.

    Uses the importer's own staging-then-promote path rather than writing the
    tables directly, so the rows are resolved and classified by exactly the
    code a real import runs — the point of the exercise being that demo mode
    reaches the classification through the product's pipeline and not around
    it. Re-running replaces the previous demo rows rather than accumulating,
    because ``promote`` deletes the source's rows before inserting the new set.

    That path also rebuilds the whole resolved table, which on a data directory
    that has imported a real registry is a real cost — the cost of exactly one
    metadata import, paid once per process start. It is accepted rather than
    optimized away: demo mode on a populated install is a deliberate act, the
    figure is the one slice 071 already measures for an import, and the
    alternative (a partial rebuild for one source) would be a second resolution
    path to keep honest for the sake of a mode nobody runs a receiver in. Since
    slice 075 that rebuild happens off the writer lock, so it no longer stalls
    the rest of a starting process either.
    """
    records = demo_metadata_records(roster)
    if not records:  # pragma: no cover - only if every category table emptied
        return 0
    repository = MetadataRepository(database)
    at_ms = utc_now_ms()
    await repository.ensure_source(DEMO_SOURCE)
    await repository.clear_staging(DEMO_SOURCE)
    await repository.stage_batch(DEMO_SOURCE, records, updated_ms=at_ms)
    await repository.promote(
        DEMO_SOURCE,
        precedence=precedence,
        at_ms=at_ms,
        dataset_version=DEMO_DATASET_VERSION,
        row_count=len(records),
    )
    logger.info("demo_metadata_seeded", aircraft=len(records))
    return len(records)


__all__ = [
    "COMMERCIAL_AIRFRAMES",
    "DEMO_DATASET_VERSION",
    "DEMO_SOURCE",
    "FIRST_EVER_AIRFRAMES",
    "GOVERNMENT_AIRFRAMES",
    "MILITARY_AIRFRAMES",
    "MLAT_AIRFRAMES",
    "OPERATED_CATEGORIES",
    "POLICE_AIRFRAMES",
    "RARE_AIRFRAMES",
    "DemoAirframe",
    "airframe_for",
    "demo_metadata_records",
    "seed_demo_metadata",
]
