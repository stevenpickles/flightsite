"""Per-source independence (SPEC §27).

*"Downloads each source independently … reports status separately for each
source."* Independence has two halves and both are tested here: one source's
failure must not touch another's **rows**, and it must not touch another's
**status**.
"""

from __future__ import annotations

import pytest

from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.registry import ImportPhase, SourceStatus
from flightsite.metadata.repository import MetadataRepository
from tests.metadata.conftest import IMPORT_MS, record, resolved_rows
from tests.metadata.provider import InMemoryMetadataProvider

MICTRONICS = [
    record("a00001", registration="N1AA", type_code="B738", operator_name="Delta Air Lines"),
    record("a00002", registration="N2BB", type_code="A320"),
]
FAA = [
    record("a00001", registration="N1AA", manufacture_year=2016, owner="Delta Air Lines Inc"),
    record("a00003", registration="N3CC", manufacture_year=1978, owner="A Person"),
]


@pytest.fixture
def both(registry: SourceRegistry) -> tuple[InMemoryMetadataProvider, InMemoryMetadataProvider]:
    mictronics = InMemoryMetadataProvider(MICTRONICS, version="mict-1")
    faa = InMemoryMetadataProvider(FAA, version="faa-1")
    registry.register("mictronics", mictronics)
    registry.register("faa", faa)
    return mictronics, faa


async def test_both_sources_import_and_merge_by_precedence(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    """The overlapping-source case the acceptance criterion names."""
    run = await importer.run()

    assert set(run.succeeded) == {"faa", "mictronics"}
    resolved = await resolved_rows(repository, ["a00001", "a00002", "a00003"])

    merged = resolved["a00001"]
    assert (merged.registration, merged.registration_src) == ("N1AA", "mictronics")
    assert (merged.type_code, merged.type_code_src) == ("B738", "mictronics")
    assert (merged.manufacture_year, merged.year_src) == (2016, "faa")
    assert (merged.owner, merged.owner_src) == ("Delta Air Lines Inc", "faa")
    assert merged.provenance() == {
        "registration": "mictronics",
        "type_code": "mictronics",
        "operator": "mictronics",
        "manufacture_year": "faa",
        "owner": "faa",
    }

    assert resolved["a00002"].type_code_src == "mictronics"
    assert resolved["a00003"].owner_src == "faa"


async def test_one_source_failing_leaves_the_others_rows_intact(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    faa = both[1]
    await importer.run()

    faa.fail_at = ImportPhase.DOWNLOAD
    run = await importer.run()

    assert run.succeeded == ("mictronics",)
    assert run.failed == ("faa",)
    resolved = await resolved_rows(repository, ["a00001", "a00003"])
    assert resolved["a00001"].owner_src == "faa"
    assert resolved["a00003"].registration == "N3CC"


async def test_one_source_failing_leaves_the_others_status_intact(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    faa = both[1]
    await importer.run()

    faa.fail_at = ImportPhase.VALIDATE
    await importer.run()

    statuses = {status.source: status for status in await repository.read_statuses()}
    assert statuses["mictronics"].status is SourceStatus.OK
    assert statuses["mictronics"].last_error is None
    assert statuses["faa"].status is SourceStatus.FAILED
    assert statuses["faa"].last_error is not None


async def test_a_source_can_be_imported_on_its_own(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    """Selecting one source must not disturb the other's rows or status."""
    await importer.run()

    await importer.run(["faa"])

    statuses = {status.source: status for status in await repository.read_statuses()}
    assert statuses["mictronics"].dataset_version == "mict-1"
    assert await repository.count_live("mictronics") == 2
    assert await repository.count_live("faa") == 2


async def test_replacing_one_source_does_not_remove_the_others_rows(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    """ "Imports replace only their own rows" (``docs/DATA_MODEL.md`` §3.2)."""
    faa = both[1]
    await importer.run()

    faa.records = [record("a00007", registration="N7GG", owner="Someone Else")]
    faa.version = "faa-2"
    await importer.run(["faa"])

    assert await repository.count_live("mictronics") == 2
    assert await repository.count_live("faa") == 1
    resolved = await resolved_rows(repository, ["a00001", "a00003", "a00007"])
    assert "a00003" not in resolved
    assert resolved["a00007"].owner == "Someone Else"
    # a00001 keeps Mictronics' fields and loses the FAA ones it no longer has.
    assert resolved["a00001"].registration_src == "mictronics"
    assert resolved["a00001"].owner is None
    assert resolved["a00001"].owner_src is None


async def test_a_never_run_source_reports_never_run(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    await importer.run(["mictronics"])

    faa = await repository.read_status("faa")
    assert faa is None


async def test_an_attempt_is_recorded_even_when_it_fails(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    faa = both[1]
    faa.fail_at = ImportPhase.DOWNLOAD

    await importer.run(["faa"])

    status = await repository.read_status("faa")
    assert status is not None
    assert status.last_attempt_ms == IMPORT_MS
    assert status.last_success_ms is None


async def test_a_success_records_the_dataset_version_and_row_count(
    both: tuple[InMemoryMetadataProvider, InMemoryMetadataProvider],
    importer: MetadataImporter,
    repository: MetadataRepository,
) -> None:
    await importer.run(["mictronics"])

    status = await repository.read_status("mictronics")
    assert status is not None
    assert status.dataset_version == "mict-1"
    assert status.row_count == 2
    assert status.last_success_ms == IMPORT_MS
    assert status.status is SourceStatus.OK


async def test_a_long_provider_error_is_truncated_for_the_status_row(
    registry: SourceRegistry, importer: MetadataImporter, repository: MetadataRepository
) -> None:
    """Status is a summary a user reads, not a log sink."""
    from flightsite.metadata.records import ValidationReport
    from flightsite.metadata.repository import MAX_ERROR_CHARS

    registry.register(
        "faa", InMemoryMetadataProvider([], report=ValidationReport.rejected("x" * 5_000))
    )

    await importer.run()

    status = await repository.read_status("faa")
    assert status is not None
    assert status.last_error is not None
    assert len(status.last_error) == MAX_ERROR_CHARS
