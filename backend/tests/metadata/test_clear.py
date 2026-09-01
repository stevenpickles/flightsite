"""``MetadataRepository.clear_all`` (SPEC §73, slice 045): the Clear Metadata
Cache action's storage layer.

Everything asserted here is the repository's own contract: every row a
successful import produced or derived is gone afterwards, every registered
source's status is reset rather than deleted, and a second call is a clean
no-op. History has no table in this module at all, so "history intact" is
asserted at the API layer (``tests/api/test_reset_api.py``) instead, where
``aircraft``/``sightings`` rows actually exist alongside imported metadata.
"""

from __future__ import annotations

from sqlalchemy import func, select

from flightsite.db import (
    AircraftClassification,
    AircraftMetadata,
    AircraftMetadataResolved,
    AircraftMetadataStaging,
    Database,
    MetadataSource,
    Operator,
    OperatorGroup,
)
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.registry import SourceStatus
from flightsite.metadata.repository import MetadataRepository
from tests.metadata.conftest import IMPORT_MS, record
from tests.metadata.provider import InMemoryMetadataProvider

RECORDS = [
    record("a00001", registration="N1AA", type_code="B738", operator_name="Delta Air Lines"),
    record("a00002", registration="N2BB", type_code="A320", operator_name="United Airlines"),
]


async def _count(database: Database, model: object) -> int:
    async with database.read_session() as session:
        total = await session.scalar(select(func.count()).select_from(model))  # type: ignore[arg-type]
        return int(total or 0)


async def seed(importer: MetadataImporter, registry: SourceRegistry) -> None:
    """One successful mictronics import: something real to clear."""
    registry.register("mictronics", InMemoryMetadataProvider(RECORDS, version="mict-1"))
    run = await importer.run()
    assert run.succeeded == ("mictronics",)


async def test_clear_all_empties_every_table_it_owns(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    database: Database,
) -> None:
    await seed(importer, registry)
    assert await _count(database, AircraftMetadata) == len(RECORDS)
    assert await _count(database, AircraftMetadataResolved) == len(RECORDS)
    assert await _count(database, OperatorGroup) > 0, "curated groups populate on any import"

    counts = await repository.clear_all()

    assert counts.aircraft_metadata_rows == len(RECORDS)
    assert counts.resolved_rows == len(RECORDS)
    assert counts.staging_rows == 0  # promote() already emptied staging
    assert counts.sources_reset == 1

    assert await _count(database, AircraftMetadata) == 0
    assert await _count(database, AircraftMetadataStaging) == 0
    assert await _count(database, AircraftMetadataResolved) == 0
    assert await _count(database, AircraftClassification) == 0
    assert await _count(database, Operator) == 0
    assert await _count(database, OperatorGroup) == 0


async def test_clear_all_resets_source_status_without_deleting_the_row(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """A stale ``ok`` beside a now-empty dataset would misreport what is installed."""
    await seed(importer, registry)
    before = await repository.read_status("mictronics")
    assert before is not None
    assert before.status is SourceStatus.OK

    await repository.clear_all()

    after = await repository.read_status("mictronics")
    assert after is not None
    assert after.status is SourceStatus.NEVER_RUN
    assert after.last_success_ms is None
    assert after.dataset_version is None
    assert after.row_count is None
    assert after.last_error is None
    # The historical fact of when the (now-cleared) import last ran is not
    # itself a claim about what is installed, so it is left alone.
    assert after.last_attempt_ms == before.last_attempt_ms == IMPORT_MS


async def test_clear_all_on_a_never_imported_database_removes_nothing(
    repository: MetadataRepository, database: Database
) -> None:
    """The state of a fresh install: nothing to clear, and clearing is still safe."""
    counts = await repository.clear_all()

    assert counts.aircraft_metadata_rows == 0
    assert counts.resolved_rows == 0
    assert counts.classification_rows == 0
    assert counts.operator_rows == 0
    assert counts.operator_group_rows == 0
    assert counts.sources_reset == 0


async def test_clear_all_is_idempotent(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    await seed(importer, registry)
    await repository.clear_all()

    second = await repository.clear_all()

    assert second.aircraft_metadata_rows == 0
    assert second.resolved_rows == 0
    assert second.operator_rows == 0
    assert second.operator_group_rows == 0
    assert second.sources_reset == 1  # the row survives; it is reset again, harmlessly


async def test_clear_all_does_not_touch_a_different_sources_row(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    database: Database,
) -> None:
    """Every registered source's status row is reset, not just the one imported."""
    await repository.ensure_source("faa")
    await seed(importer, registry)

    await repository.clear_all()

    faa_status = await repository.read_status("faa")
    assert faa_status is not None
    assert faa_status.status is SourceStatus.NEVER_RUN
    # The row itself must survive, not just read as reset-shaped: gone would
    # break the foreign key the (now empty) aircraft_metadata table carries.
    async with database.read_session() as session:
        assert await session.get(MetadataSource, "faa") is not None
