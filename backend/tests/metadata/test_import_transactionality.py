"""Fault injection: a failed import leaves the previous dataset fully intact.

Slice 021's first acceptance criterion, and the reason the pipeline is built
the way it is. Each stage gets its own test, and each asserts the strong form:
``aircraft_metadata`` and ``aircraft_metadata_resolved`` come back row for row
identical to a dump taken before the failing run — not "still has data", not
"still has the right count", identical.

The dumps are taken with stdlib ``sqlite3`` against the file
(:func:`tests.metadata.conftest.dump`), so nothing an ORM session might
reconstruct can paper over a write that actually happened.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.db import Database
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.importer import MAX_REJECT_RATIO, WORK_DIRNAME
from flightsite.metadata.records import ValidationReport
from flightsite.metadata.registry import ImportPhase, SourceStatus
from flightsite.metadata.repository import MetadataRepository
from tests.metadata.conftest import DATASET_TABLES, dump, record, resolved_rows
from tests.metadata.provider import InMemoryMetadataProvider, ProviderFailure

GOOD = [
    record("a00001", registration="N1AA", type_code="B738", operator_name="Delta Air Lines"),
    record("a00002", registration="N2BB", type_code="A320", operator_name="United Airlines"),
    record("a00003", registration="N3CC", type_code="B738"),
]

REPLACEMENT = [record("a00009", registration="N9ZZ", type_code="C172")]


async def install_baseline(
    importer: MetadataImporter, registry: SourceRegistry
) -> InMemoryMetadataProvider:
    """Import a good Mictronics snapshot, so there is something to preserve."""
    provider = InMemoryMetadataProvider(GOOD, version="baseline")
    registry.register("mictronics", provider)
    run = await importer.run()

    assert run.succeeded == ("mictronics",)
    return provider


@pytest.fixture
async def baseline(
    importer: MetadataImporter, registry: SourceRegistry, db_path: Path
) -> dict[str, list[tuple[object, ...]]]:
    """A populated dataset plus the dump every fault test compares against."""
    await install_baseline(importer, registry)
    return dump(db_path, DATASET_TABLES)


# ------------------------------------------------------------ the happy path


async def test_a_good_import_populates_both_tables(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    await install_baseline(importer, registry)

    resolved = await resolved_rows(repository, ["a00001", "a00002", "a00003"])
    assert set(resolved) == {"a00001", "a00002", "a00003"}
    assert resolved["a00001"].registration == "N1AA"
    assert resolved["a00001"].registration_src == "mictronics"

    status = await repository.read_status("mictronics")
    assert status is not None
    assert status.status is SourceStatus.OK
    assert status.dataset_version == "baseline"
    assert status.row_count == 3


async def test_staging_is_empty_after_a_successful_promotion(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """The landing area is scratch; leaving rows there would leak into re-runs."""
    await install_baseline(importer, registry)

    assert await repository.count_staged("mictronics") == 0


async def test_the_working_directory_does_not_survive_the_run(
    importer: MetadataImporter, registry: SourceRegistry, isolated_data_dir: Path
) -> None:
    """Downloads are transient: the data directory contract holds no snapshots."""
    await install_baseline(importer, registry)

    assert not (isolated_data_dir / WORK_DIRNAME / "mictronics").exists()


# --------------------------------------------------------- fault injection


@pytest.mark.parametrize("phase", [ImportPhase.DOWNLOAD, ImportPhase.VALIDATE, ImportPhase.STAGING])
async def test_a_failure_before_the_swap_leaves_the_dataset_byte_identical(
    baseline: dict[str, list[tuple[object, ...]]],
    importer: MetadataImporter,
    registry: SourceRegistry,
    db_path: Path,
    phase: ImportPhase,
) -> None:
    """Download, validate and staging each fail without touching live rows."""
    registry.register("faa", InMemoryMetadataProvider(REPLACEMENT, fail_at=phase, fail_after=0))

    run = await importer.run(["faa"])

    assert run.failed == ("faa",)
    assert run.results[0].phase is phase
    assert dump(db_path, DATASET_TABLES) == baseline


async def test_a_failure_inside_the_swap_rolls_the_whole_swap_back(
    baseline: dict[str, list[tuple[object, ...]]],
    importer: MetadataImporter,
    registry: SourceRegistry,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last and hardest stage: the promotion transaction must be all-or-nothing.

    The fault fires inside :meth:`MetadataRepository.rebuild_resolved`, i.e.
    *after* the source's old rows have been deleted and the staged ones
    inserted. Only the transaction boundary can save the dataset here — and it
    does, for both tables.
    """
    registry.register("mictronics_v2", InMemoryMetadataProvider(REPLACEMENT))

    async def explode(*args: object, **kwargs: object) -> int:
        raise ProviderFailure("disk full mid-swap")

    monkeypatch.setattr(MetadataRepository, "rebuild_resolved", explode)

    run = await importer.run(["mictronics_v2"])

    assert run.failed == ("mictronics_v2",)
    assert run.results[0].phase is ImportPhase.SWAP
    assert dump(db_path, DATASET_TABLES) == baseline


async def test_a_failed_run_leaves_no_staged_rows_behind(
    baseline: dict[str, list[tuple[object, ...]]],
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
) -> None:
    registry.register(
        "faa",
        InMemoryMetadataProvider(REPLACEMENT * 3, fail_at=ImportPhase.STAGING, fail_after=1),
    )

    await importer.run(["faa"])

    assert await repository.count_staged("faa") == 0


async def test_a_failure_is_a_result_not_an_exception(
    importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """The user has to be told which sources worked (SPEC §27)."""
    registry.register("faa", InMemoryMetadataProvider(REPLACEMENT, fail_at=ImportPhase.DOWNLOAD))

    run = await importer.run()

    assert run.results[0].error is not None
    assert "upstream unreachable" in run.results[0].error


async def test_a_validation_rejection_reaches_the_status_row(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    registry.register("faa", InMemoryMetadataProvider(REPLACEMENT, fail_at=ImportPhase.VALIDATE))

    await importer.run()

    status = await repository.read_status("faa")
    assert status is not None
    assert status.status is SourceStatus.FAILED
    assert status.last_error == "downloaded file is not a snapshot"
    assert status.last_success_ms is None


async def test_a_second_failure_after_a_success_keeps_the_success_facts(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    db_path: Path,
) -> None:
    """ "Last successful update" must keep describing the data actually installed."""
    provider = await install_baseline(importer, registry)
    good = dump(db_path, DATASET_TABLES)

    provider.fail_at = ImportPhase.DOWNLOAD
    await importer.run(["mictronics"])

    status = await repository.read_status("mictronics")
    assert status is not None
    assert status.status is SourceStatus.FAILED
    assert status.last_success_ms is not None
    assert status.dataset_version == "baseline"
    assert status.row_count == 3
    assert dump(db_path, DATASET_TABLES) == good


# ----------------------------------------------------- transform-level guards


async def test_an_empty_snapshot_is_refused_rather_than_wiping_the_dataset(
    baseline: dict[str, list[tuple[object, ...]]],
    importer: MetadataImporter,
    registry: SourceRegistry,
    db_path: Path,
) -> None:
    """A source that yields nothing is broken, not newly empty."""
    registry.register("faa", InMemoryMetadataProvider([]))

    run = await importer.run(["faa"])

    assert run.failed == ("faa",)
    assert "no usable rows" in (run.results[0].error or "")
    assert dump(db_path, DATASET_TABLES) == baseline


async def test_a_few_bad_rows_are_counted_and_survived(
    importer: MetadataImporter, registry: SourceRegistry
) -> None:
    """Real snapshots contain junk; one bad line must not fail an import."""
    registry.register("faa", InMemoryMetadataProvider(GOOD * 10, bad_rows=1))

    run = await importer.run()

    assert run.succeeded == ("faa",)
    assert run.results[0].rows_rejected == 1


async def test_mostly_bad_rows_fail_the_import(
    baseline: dict[str, list[tuple[object, ...]]],
    importer: MetadataImporter,
    registry: SourceRegistry,
    db_path: Path,
) -> None:
    """A parser that disagrees with its file must not replace good data."""
    registry.register("faa", InMemoryMetadataProvider(GOOD, bad_rows=100))

    run = await importer.run(["faa"])

    assert run.failed == ("faa",)
    assert f"{MAX_REJECT_RATIO:.0%}" in (run.results[0].error or "")
    assert dump(db_path, DATASET_TABLES) == baseline


async def test_a_truncated_transform_is_caught_by_the_expected_row_count(
    baseline: dict[str, list[tuple[object, ...]]],
    importer: MetadataImporter,
    registry: SourceRegistry,
    db_path: Path,
) -> None:
    """Validation saw a big file; the transform produced three rows."""
    registry.register(
        "faa",
        InMemoryMetadataProvider(GOOD, report=ValidationReport.accepted(expected_rows=500)),
    )

    run = await importer.run(["faa"])

    assert run.failed == ("faa",)
    assert "validation expected 500" in (run.results[0].error or "")
    assert dump(db_path, DATASET_TABLES) == baseline


async def test_duplicate_addresses_in_a_snapshot_keep_the_last_row(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """Upstream files repeat addresses; the conventional reading is last-wins."""
    duplicated = [
        record("a00001", registration="OLD", type_code="B738"),
        record("a00001", registration="NEW", type_code="B738"),
    ]
    registry.register("faa", InMemoryMetadataProvider(duplicated))

    run = await importer.run()

    assert run.results[0].rows_imported == 1
    resolved = await resolved_rows(repository, ["a00001"])
    assert resolved["a00001"].registration == "NEW"


async def test_a_re_import_of_an_unchanged_snapshot_is_a_no_op_on_disk(
    importer: MetadataImporter, registry: SourceRegistry, db_path: Path
) -> None:
    """Idempotence: promotion replaces rows with identical ones."""
    await install_baseline(importer, registry)
    first = dump(db_path, DATASET_TABLES)

    await importer.run(["mictronics"])

    assert dump(db_path, DATASET_TABLES) == first


async def test_importing_an_unregistered_source_is_a_programming_error(
    importer: MetadataImporter,
) -> None:
    """Not a run outcome: nobody asked a user to type this name."""
    with pytest.raises(KeyError):
        await importer.run(["nope"])


async def test_an_empty_registry_runs_and_reports_nothing(
    importer: MetadataImporter, database: Database
) -> None:
    """A stock install has no providers until slices 022/023 register theirs."""
    run = await importer.run()

    assert run.results == ()
    assert not run.changed_data
