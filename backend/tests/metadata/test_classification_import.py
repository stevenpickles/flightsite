"""Classification and operator grouping as the import pipeline writes them.

The import is where SPEC §38 and §39 stop being a pure function and become
three tables. Four properties matter, and each has tests here:

* **The curated data lands.** ``operator_groups`` and ``operators`` are the
  data file, made queryable (``docs/DATA_MODEL.md`` §3.5).
* **Grouping is additive.** The exact operator string survives on the resolved
  row whether or not a group claims it.
* **Everything is idempotent.** Re-importing the same snapshot produces the
  same bytes in every table — group ids included, since resolved rows point at
  them.
* **It is one transaction.** Metadata and classification are written together
  or not at all, so a reader can never see an airframe whose classification
  describes the previous dataset.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flightsite.classification.operators import OperatorDirectory, default_directory
from flightsite.classification.vocabulary import ClaimSource, Confidence, MissionCategory
from flightsite.db import Database
from flightsite.metadata import (
    MetadataImporter,
    MetadataRepository,
    NormalizedAircraftRecord,
    SourceRegistry,
)
from flightsite.metadata.registry import ImportPhase
from tests.metadata.conftest import DATASET_TABLES, dump, record, resolved_rows
from tests.metadata.provider import InMemoryMetadataProvider

CURATED_TABLES = ("operator_groups", "operators")
CLASSIFICATION_TABLES = ("aircraft_classification",)

#: A snapshot spanning every kind of evidence the engine reads.
FLEET = (
    ("ae1463", {"operator_name": "United States Air Force", "type_code": "C17"}, True),
    ("a1b2c3", {"operator_name": "Delta Air Lines, Inc.", "type_code": "B739"}, None),
    ("a44444", {"operator_name": "Travis County Sheriff", "type_code": "EC45"}, None),
    ("a55555", {"operator_name": "Air Methods Corporation", "type_code": "EC35"}, None),
    ("a66666", {"operator_name": "Federal Express Corp", "type_code": "B763"}, None),
    ("a77777", {"registration": "N12345", "type_code": "C172"}, None),
    ("a88888", {"registration": "N99999", "type_code": "B738"}, None),
)


def _fleet_records() -> list[NormalizedAircraftRecord]:
    return [record(icao, military_flag=military, **fields) for icao, fields, military in FLEET]


async def _import_fleet(
    importer: MetadataImporter, registry: SourceRegistry
) -> InMemoryMetadataProvider:
    """Import the fleet and hand back the provider, so a test can change it.

    A source can only be registered once (that is the registry's contract), so
    a second import with different data mutates the provider rather than
    replacing it — which is also what a real upstream snapshot changing looks
    like.
    """
    provider = InMemoryMetadataProvider(_fleet_records())
    registry.register("mictronics", provider)
    run = await importer.run()
    assert run.failed == ()
    return provider


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


# ------------------------------------------------------------- curated tables


async def test_the_curated_groups_land_in_the_database(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """§3.5: the data file, loaded into tables so SQL can join and filter."""
    await _import_fleet(importer, registry)
    directory = default_directory()

    groups = _rows(db_path, "SELECT id, slug, name FROM operator_groups ORDER BY id")

    assert len(groups) == len(directory.groups)
    assert (directory.group_id("us-military"), "us-military", "US Military") in groups


async def test_every_curated_operator_name_is_queryable(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """Present whether or not this receiver has ever heard the operator."""
    await _import_fleet(importer, registry)

    names = {name for (name,) in _rows(db_path, "SELECT name FROM operators")}

    assert "Delta Air Lines" in names
    # Never heard by this receiver, still in the curated table.
    assert "Qantas" in names


async def test_an_operator_matched_by_phrase_is_recorded_under_its_exact_spelling(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """The only rows an import can discover: there is no finite list of sheriffs."""
    await _import_fleet(importer, registry)
    directory = default_directory()

    rows = _rows(
        db_path,
        "SELECT name, group_id FROM operators WHERE name = 'Travis County Sheriff'",
    )

    assert rows == [("Travis County Sheriff", directory.group_id("police"))]


async def test_an_operator_no_rule_claims_is_left_ungrouped(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    registry.register(
        "mictronics",
        InMemoryMetadataProvider([record("a00001", operator_name="Nobody In Particular")]),
    )
    await importer.run()

    assert _rows(db_path, "SELECT name FROM operators WHERE name = 'Nobody In Particular'") == []


# ------------------------------------------------------ grouping is additive


async def test_the_exact_operator_survives_beside_its_group(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """SPEC §38's central promise, across three spellings and two match kinds."""
    await _import_fleet(importer, registry)
    directory = default_directory()

    resolved = await resolved_rows(repository, ["a1b2c3", "a44444", "a88888"])

    assert resolved["a1b2c3"].operator_name == "Delta Air Lines, Inc."
    assert resolved["a1b2c3"].operator_group_id == directory.group_id("delta")
    assert resolved["a44444"].operator_name == "Travis County Sheriff"
    assert resolved["a44444"].operator_group_id == directory.group_id("police")
    assert resolved["a88888"].operator_group_id is None


async def test_the_operator_group_name_is_readable_prose(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """``docs/API.md`` §3.3 publishes the name, not the slug."""
    await _import_fleet(importer, registry)

    lookup = await repository.load_live_view(["ae1463"])

    assert lookup["ae1463"].operator_group == "US Military"


# ------------------------------------------------------------ classification


async def test_classification_rows_are_written_for_the_whole_fleet(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    await _import_fleet(importer, registry)

    rows = {
        str(icao24): mission
        for icao24, mission in _rows(
            db_path, "SELECT icao24, mission_category FROM aircraft_classification"
        )
    }

    assert rows == {
        "ae1463": MissionCategory.MILITARY.value,
        "a1b2c3": MissionCategory.COMMERCIAL_PASSENGER.value,
        "a44444": MissionCategory.LAW_ENFORCEMENT.value,
        "a55555": MissionCategory.MEDICAL.value,
        "a66666": MissionCategory.CARGO.value,
        "a77777": MissionCategory.GENERAL_AVIATION.value,
    }


async def test_an_airframe_with_nothing_to_say_gets_no_classification_row(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """An airliner type and no operator: absence is the honest representation."""
    await _import_fleet(importer, registry)

    assert _rows(db_path, "SELECT icao24 FROM aircraft_classification WHERE icao24='a88888'") == []


async def test_the_military_bit_is_stored_with_its_source_and_confidence(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    await _import_fleet(importer, registry)

    rows = _rows(
        db_path,
        "SELECT military, military_src, military_conf, icon_category "
        "FROM aircraft_classification WHERE icao24 = 'ae1463'",
    )

    assert rows == [(1, ClaimSource.MICTRONICS.value, Confidence.HIGH.score, "military_transport")]


async def test_a_curated_match_is_stored_as_a_flightsite_claim(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """§3.4's ``*_src`` vocabulary: an upstream source, or FlightSite itself."""
    await _import_fleet(importer, registry)

    rows = _rows(
        db_path,
        "SELECT law_enforcement, law_enforcement_src, mission_src, mission_conf "
        "FROM aircraft_classification WHERE icao24 = 'a44444'",
    )

    assert rows == [
        (1, ClaimSource.HEURISTIC.value, ClaimSource.HEURISTIC.value, Confidence.MEDIUM.score)
    ]


async def test_an_airframe_known_only_by_a_military_bit_is_still_classified(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """No resolvable field means no resolved row — but plenty to say."""
    registry.register(
        "mictronics", InMemoryMetadataProvider([record("ae0001", military_flag=True)])
    )
    await importer.run()

    assert _rows(db_path, "SELECT icao24 FROM aircraft_metadata_resolved") == []
    assert _rows(db_path, "SELECT military, mission_category FROM aircraft_classification") == [
        (1, MissionCategory.MILITARY.value)
    ]


# --------------------------------------------------------------- idempotence


async def test_a_repeat_import_produces_identical_tables(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """Group ids are written into resolved rows, so they must not move."""
    await _import_fleet(importer, registry)
    tables = (*DATASET_TABLES, *CURATED_TABLES, *CLASSIFICATION_TABLES)
    first = dump(db_path, tables)

    await importer.run()

    assert dump(db_path, tables) == first


async def test_a_second_import_does_not_duplicate_a_discovered_operator(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """The table's primary key would refuse it; the rebuild must not try."""
    await _import_fleet(importer, registry)
    await importer.run()

    rows = _rows(db_path, "SELECT name, COUNT(*) FROM operators GROUP BY name HAVING COUNT(*) > 1")

    assert rows == []


async def test_an_operator_dropped_from_the_snapshot_loses_its_discovered_row(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """The rebuild is authoritative: withdrawn evidence is actually withdrawn."""
    provider = await _import_fleet(importer, registry)
    assert _rows(db_path, "SELECT name FROM operators WHERE name = 'Travis County Sheriff'")

    provider.records = [record("a00001", operator_name="Nobody")]
    await importer.run()

    assert _rows(db_path, "SELECT name FROM operators WHERE name = 'Travis County Sheriff'") == []


async def test_a_classification_is_withdrawn_when_its_evidence_disappears(
    db_path: Path, importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """Honesty about withdrawn evidence is the same property as honesty about weak evidence."""
    provider = await _import_fleet(importer, registry)
    assert _rows(db_path, "SELECT icao24 FROM aircraft_classification WHERE icao24='ae1463'")

    provider.records = [record("ae1463", registration="N1", type_code="B738")]
    await importer.run()

    assert _rows(db_path, "SELECT icao24 FROM aircraft_classification") == []


# --------------------------------------------------------------- atomicity


async def test_a_failed_import_leaves_the_previous_classification_intact(
    db_path: Path,
    database: Database,
    importer: MetadataImporter,
    registry: SourceRegistry,
) -> None:
    """SPEC §27's guarantee, extended to the tables slice 024 added."""
    provider = await _import_fleet(importer, registry)
    tables = (*DATASET_TABLES, *CURATED_TABLES, *CLASSIFICATION_TABLES)
    before = dump(db_path, tables)

    provider.records = [record("a00001", operator_name="Ryanair")]
    provider.fail_at = ImportPhase.STAGING
    run = await importer.run()

    assert run.failed == ("mictronics",)
    assert dump(db_path, tables) == before
    await database.dispose()


async def test_an_empty_curated_directory_leaves_the_tables_empty(
    db_path: Path,
    database: Database,
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
) -> None:
    """The directory is injectable, and an empty one is a valid one.

    A build that shipped no curated data would still resolve metadata and still
    classify from type designators; it would simply group nothing. Asserting it
    keeps the curated file a *data* dependency rather than a load-bearing one.
    """
    await _import_fleet(importer, registry)

    async with database.writer_session() as session:
        await repository.rebuild_resolved(
            session,
            precedence=registry.precedence(),
            at_ms=1,
            directory=OperatorDirectory(()),
        )

    assert _rows(db_path, "SELECT id FROM operator_groups") == []
    assert _rows(db_path, "SELECT name FROM operators") == []
    assert _rows(db_path, "SELECT icao24 FROM aircraft_metadata_resolved WHERE icao24='a1b2c3'")
    # Type evidence survives: the airframe is still a light aeroplane.
    assert _rows(
        db_path, "SELECT mission_category FROM aircraft_classification WHERE icao24='a77777'"
    ) == [(MissionCategory.GENERAL_AVIATION.value,)]
