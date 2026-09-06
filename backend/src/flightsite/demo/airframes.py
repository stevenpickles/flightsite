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
``rebuild_resolved`` classifies them, the metadata cache loads the resolved
view when the aircraft appears, and a rule matches on the classification it
finds. Nothing in :mod:`flightsite.classification` or
:mod:`flightsite.alerts` learns that demo mode exists.

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
  it was.
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
    operator_name: str
    type_code: str
    model: str
    registration: str


#: Military operators, all of which the curated directory recognises with a
#: ``military`` group, so :func:`~flightsite.classification.engine.classify`
#: reports ``military=True`` at HIGH confidence from the operator alone.
MILITARY_AIRFRAMES: Final[tuple[DemoAirframe, ...]] = (
    DemoAirframe("United States Air Force", "C17", "Boeing C-17A Globemaster III", "05-5153"),
    DemoAirframe("United States Air Force", "K35R", "Boeing KC-135R Stratotanker", "62-3552"),
    DemoAirframe("US Navy", "P8", "Boeing P-8A Poseidon", "169329"),
    DemoAirframe("Royal Air Force", "A400", "Airbus A400M Atlas", "ZM415"),
    DemoAirframe("United States Marine Corps", "V22", "Bell Boeing MV-22B Osprey", "168331"),
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

#: Which categories carry an airframe identity, and from which table. Every
#: other category is left exactly as it was: a demo in which *everything*
#: classifies would be a worse demo, because "unknown" is the honest and
#: common answer for an airframe no registry describes.
AIRFRAMES_BY_CATEGORY: Final[dict[Category, tuple[DemoAirframe, ...]]] = {
    Category.MILITARY: MILITARY_AIRFRAMES,
    Category.GOVERNMENT: GOVERNMENT_AIRFRAMES,
    Category.POLICE: POLICE_AIRFRAMES,
}


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
    path to keep honest for the sake of a mode nobody runs a receiver in.
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
    "DEMO_DATASET_VERSION",
    "DEMO_SOURCE",
    "GOVERNMENT_AIRFRAMES",
    "MILITARY_AIRFRAMES",
    "POLICE_AIRFRAMES",
    "DemoAirframe",
    "airframe_for",
    "demo_metadata_records",
    "seed_demo_metadata",
]
