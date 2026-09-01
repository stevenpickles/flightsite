"""The airport dataset through the real import pipeline.

The slice's other contract: *"OurAirports registered in ``metadata_sources`` so
the 025 update action reports it"* — beside the aircraft sources, and
independently of them (SPEC §27: each source succeeds or fails on its own).

Everything here runs the real
:class:`~flightsite.metadata.importer.MetadataImporter` over the real
:class:`~flightsite.airports.ourairports.OurAirportsProvider` and the real
:class:`~flightsite.airports.sink.AirportImportSink`; only the HTTP transport is
a mock, so the download, the validation gate, the reject-ratio tolerance and the
promotion all execute.

The two size floors are lowered for the fixtures. They are floors on a *genuine
snapshot* — thirteen megabytes and seventy thousand rows — and a suite that met
them honestly would spend seconds per test generating filler.
``test_ourairports.py`` asserts the floors themselves; here they are scenery.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from flightsite.airports import (
    AIRPORTS_SOURCE,
    AirportImportSink,
    AirportRepository,
    OurAirportsProvider,
    ourairports,
)
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
)
from flightsite.metadata.registry import SourceRegistry, SourceStatus
from tests.airports.test_ourairports import FIXTURE_ROWS, csv_bytes

MICTRONICS = "mictronics"


@pytest.fixture(autouse=True)
def _small_floors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scale the artifact floors down to fixture size. See the module docstring."""
    monkeypatch.setattr(ourairports, "MIN_ARTIFACT_BYTES", 10)
    monkeypatch.setattr(ourairports, "MIN_EXPECTED_ROWS", 1)


def provider_over(payload: bytes, *, status_code: int = 200) -> OurAirportsProvider:
    """A provider whose client answers with ``payload`` and never opens a socket."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=payload)

    return OurAirportsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def refusing_provider() -> OurAirportsProvider:
    """A provider whose transport always refuses — an offline install."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network in tests", request=request)

    return OurAirportsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


class ScriptedAircraftProvider:
    """A minimal aircraft-metadata provider, for the independence tests.

    Its only job is to be *another* source in the registry that succeeds or
    fails on its own, so an assertion about independence is about two real
    sources rather than one source and a mock of the pipeline.
    """

    def __init__(
        self, records: tuple[NormalizedAircraftRecord, ...], *, fail: bool = False
    ) -> None:
        self.records = records
        self.fail = fail

    async def download(self, workdir: Path) -> SourceArtifact:
        if self.fail:
            raise RuntimeError("upstream is down")
        path = workdir / "aircraft.csv"
        path.write_text("scripted", encoding="utf-8")
        return SourceArtifact(path=path, version="scripted-1", size_bytes=8)

    def validate(self, artifact: SourceArtifact) -> ValidationReport:
        return ValidationReport.accepted()

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        return iter(self.records)


def build_service(
    database: Database,
    live: LiveStore,
    data_dir: Path,
    registry: SourceRegistry,
) -> MetadataService:
    return MetadataService(database=database, live=live, data_dir=data_dir, registry=registry)


def registry_with_airports(
    repository: AirportRepository, provider: OurAirportsProvider
) -> SourceRegistry:
    registry = SourceRegistry()
    registry.register(AIRPORTS_SOURCE, provider, sink=AirportImportSink(repository))
    return registry


# ------------------------------------------------------------- a good import


async def test_an_import_fills_the_table_and_records_its_status(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """The whole pipeline: download, validate, stage, promote, report."""
    registry = registry_with_airports(repository, provider_over(csv_bytes()))
    service = build_service(database, live, isolated_data_dir, registry)

    run = await service.update()

    assert run.succeeded == (AIRPORTS_SOURCE,)
    result = run.results[0]
    assert result.rows_imported == 3
    assert result.rows_rejected == 0

    loaded = await repository.load_all()
    assert [record.ident for record in loaded] == ["00A", "00AA", "KBFI"]

    statuses = {status.source: status for status in await service.statuses()}
    assert statuses[AIRPORTS_SOURCE].status == SourceStatus.OK
    assert statuses[AIRPORTS_SOURCE].row_count == 3
    assert statuses[AIRPORTS_SOURCE].dataset_version == result.dataset_version


async def test_a_second_import_replaces_the_first(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """Repeat runs are idempotent in the way that matters: the table is the file."""
    registry = registry_with_airports(repository, provider_over(csv_bytes()))
    service = build_service(database, live, isolated_data_dir, registry)
    await service.update()

    smaller = registry_with_airports(repository, provider_over(csv_bytes(FIXTURE_ROWS[:1])))
    await build_service(database, live, isolated_data_dir, smaller).update()

    loaded = await repository.load_all()
    assert [record.ident for record in loaded] == ["KBFI"]


async def test_re_importing_the_same_bytes_reports_the_same_version(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """So a user can tell whether an "update" actually changed anything."""
    registry = registry_with_airports(repository, provider_over(csv_bytes()))
    service = build_service(database, live, isolated_data_dir, registry)

    first = await service.update()
    second = await service.update()

    assert first.results[0].dataset_version == second.results[0].dataset_version


# ------------------------------------------------------------ a bad import


async def test_a_download_failure_leaves_the_previous_dataset_intact(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """The pipeline's guarantee, reached through the airport sink."""
    good = registry_with_airports(repository, provider_over(csv_bytes()))
    await build_service(database, live, isolated_data_dir, good).update()
    assert await repository.count() == 3

    offline = registry_with_airports(repository, refusing_provider())
    service = build_service(database, live, isolated_data_dir, offline)
    run = await service.update()

    assert run.failed == (AIRPORTS_SOURCE,)
    assert await repository.count() == 3

    statuses = {status.source: status for status in await service.statuses()}
    status = statuses[AIRPORTS_SOURCE]
    assert status.status == SourceStatus.FAILED
    assert status.last_error is not None
    # The row still describes the dataset that is actually in the table.
    assert status.row_count == 3


async def test_a_rejected_artifact_never_touches_the_table(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A captive-portal page is caught at validate, before staging exists."""
    monkeypatch.setattr(ourairports, "MIN_ARTIFACT_BYTES", 2_000_000)
    registry = registry_with_airports(repository, provider_over(b"<html>login</html>"))
    service = build_service(database, live, isolated_data_dir, registry)

    run = await service.update()

    assert run.failed == (AIRPORTS_SOURCE,)
    assert await repository.count() == 0


async def test_a_file_with_no_importable_rows_fails_rather_than_emptying_the_table(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """Only closed fields and seaplane bases: nothing to import, and a failure."""
    good = registry_with_airports(repository, provider_over(csv_bytes()))
    await build_service(database, live, isolated_data_dir, good).update()

    excluded = registry_with_airports(repository, provider_over(csv_bytes(FIXTURE_ROWS[3:])))
    run = await build_service(database, live, isolated_data_dir, excluded).update()

    assert run.failed == (AIRPORTS_SOURCE,)
    assert await repository.count() == 3


async def test_a_run_that_staged_fewer_rows_than_validation_expected_fails(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The truncation a file-level check cannot see: it parsed, and it is short."""
    monkeypatch.setattr(ourairports, "MIN_EXPECTED_ROWS", 30_000)
    registry = registry_with_airports(repository, provider_over(csv_bytes()))

    run = await build_service(database, live, isolated_data_dir, registry).update()

    assert run.failed == (AIRPORTS_SOURCE,)
    assert await repository.count() == 0


# ---------------------------------------------------------- independence


async def test_the_airport_source_is_reported_beside_the_aircraft_sources(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """Slice 025's status endpoint reads exactly this list."""
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider((_aircraft("ae1463"),)))
    registry.register(
        AIRPORTS_SOURCE, provider_over(csv_bytes()), sink=AirportImportSink(repository)
    )
    service = build_service(database, live, isolated_data_dir, registry)

    await service.update()

    statuses = {status.source: status for status in await service.statuses()}
    assert set(statuses) == {AIRPORTS_SOURCE, MICTRONICS}
    assert statuses[AIRPORTS_SOURCE].status == SourceStatus.OK
    assert statuses[MICTRONICS].status == SourceStatus.OK


async def test_the_airport_source_failing_does_not_affect_the_aircraft_sources(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """SPEC §27: one source failing neither aborts the run nor touches another."""
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider((_aircraft("ae1463"),)))
    registry.register(AIRPORTS_SOURCE, refusing_provider(), sink=AirportImportSink(repository))
    service = build_service(database, live, isolated_data_dir, registry)

    run = await service.update()

    assert run.failed == (AIRPORTS_SOURCE,)
    assert run.succeeded == (MICTRONICS,)

    statuses = {status.source: status for status in await service.statuses()}
    assert statuses[AIRPORTS_SOURCE].status == SourceStatus.FAILED
    assert statuses[MICTRONICS].status == SourceStatus.OK
    assert statuses[MICTRONICS].last_error is None


async def test_an_aircraft_source_failing_does_not_affect_the_airport_dataset(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider((), fail=True))
    registry.register(
        AIRPORTS_SOURCE, provider_over(csv_bytes()), sink=AirportImportSink(repository)
    )
    service = build_service(database, live, isolated_data_dir, registry)

    run = await service.update()

    assert run.failed == (MICTRONICS,)
    assert run.succeeded == (AIRPORTS_SOURCE,)
    assert await repository.count() == 3


async def test_only_the_named_source_runs(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """An update restricted to airports leaves the aircraft sources untouched."""
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider((_aircraft("ae1463"),)))
    registry.register(
        AIRPORTS_SOURCE, provider_over(csv_bytes()), sink=AirportImportSink(repository)
    )
    service = build_service(database, live, isolated_data_dir, registry)

    run = await service.update([AIRPORTS_SOURCE])

    assert run.succeeded == (AIRPORTS_SOURCE,)
    statuses = {status.source: status for status in await service.statuses()}
    assert statuses[MICTRONICS].status == SourceStatus.NEVER_RUN


async def test_precedence_never_names_the_airport_source(
    repository: AirportRepository,
) -> None:
    """It writes no ``aircraft_metadata`` rows, so it has no claim to rank."""
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider(()))
    registry.register(AIRPORTS_SOURCE, OurAirportsProvider(), sink=AirportImportSink(repository))

    assert AIRPORTS_SOURCE in registry
    assert AIRPORTS_SOURCE not in registry.precedence().priorities
    assert MICTRONICS in registry.precedence().priorities


# ------------------------------------------------------------ post-import


async def test_a_listener_runs_after_a_run_that_changed_data(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """The seam the app rebuilds the airport index through."""
    seen: list[tuple[str, ...]] = []

    async def listener(run: object) -> None:
        seen.append(run.succeeded)  # type: ignore[attr-defined]

    registry = registry_with_airports(repository, provider_over(csv_bytes()))
    service = MetadataService(
        database=database,
        live=live,
        data_dir=isolated_data_dir,
        registry=registry,
        listeners=(listener,),
    )

    await service.update()

    assert seen == [(AIRPORTS_SOURCE,)]


async def test_a_listener_still_runs_when_every_source_failed(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """A run in which nothing imported is news, and reaches the listeners.

    Slice 035 widened this seam. SPEC §55 puts metadata update *results* in the
    activity feed and SPEC §27 requires the user to see which sources failed,
    so the notification cannot be conditional on success. The run arrives with
    an empty ``succeeded`` and the failure named in ``failed`` — which is what
    lets the airport index rebuild keep doing nothing (it guards on the source
    having succeeded, see :func:`flightsite.app._rebuild_airport_index`) while
    the feed still reports the failure.
    """
    seen: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    async def listener(run: object) -> None:
        seen.append((run.succeeded, run.failed))  # type: ignore[attr-defined]

    registry = registry_with_airports(repository, refusing_provider())
    service = MetadataService(
        database=database,
        live=live,
        data_dir=isolated_data_dir,
        registry=registry,
        listeners=(listener,),
    )

    await service.update()

    assert seen == [((), (AIRPORTS_SOURCE,))]


async def test_a_failing_listener_does_not_fail_the_import(
    database: Database,
    live: LiveStore,
    repository: AirportRepository,
    isolated_data_dir: Path,
) -> None:
    """A listener rebuilds a derived structure; the rows are already committed."""
    ran: list[str] = []

    async def explodes(run: object) -> None:
        raise RuntimeError("the index would not build")

    async def afterwards(run: object) -> None:
        ran.append("second")

    registry = registry_with_airports(repository, provider_over(csv_bytes()))
    service = MetadataService(
        database=database,
        live=live,
        data_dir=isolated_data_dir,
        registry=registry,
        listeners=(explodes, afterwards),
    )

    run = await service.update()

    assert run.succeeded == (AIRPORTS_SOURCE,)
    assert await repository.count() == 3
    assert ran == ["second"]


def _aircraft(icao24: str) -> NormalizedAircraftRecord:
    return NormalizedAircraftRecord(icao24=icao24, registration="N12345", type_code="P28A")
