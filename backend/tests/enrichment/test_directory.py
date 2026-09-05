"""The route directory: records, storage, and the real import pipeline.

Two halves, and the second is the one that matters most. The first is the
normalization boundary — what a directory row *is*, and what it refuses to be.
The second runs the real :class:`~flightsite.metadata.importer.MetadataImporter`
over the real :class:`~flightsite.metadata.sources.routes.VrsRoutesProvider` and
the real :class:`~flightsite.enrichment.directory.RouteDirectoryImportSink`, with
only the HTTP transport mocked, so the download, the validation gate, the
staging, the reject-ratio tolerance and the atomic promotion all execute.

The archive floors are lowered here, as ``tests/airports/test_import.py`` lowers
the airport ones: they are floors on a *genuine* snapshot — a megabyte of zip,
619,770 routes — and a suite that met them honestly would generate filler for
seconds per test. ``tests/metadata/sources/test_routes.py`` asserts the floors
themselves; here they are scenery.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

from flightsite.db import Database
from flightsite.enrichment.directory import (
    MAX_PATH_CODES,
    ROUTES_SOURCE,
    RouteDirectoryError,
    RouteDirectoryImportSink,
    RouteDirectoryRecord,
    RouteDirectoryRepository,
    RouteRecordError,
    normalize_route,
)
from flightsite.enrichment.model import ROUTE_SOURCE_VRS
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
    normalize_record,
)
from flightsite.metadata.registry import SourceRegistry, SourceStatus
from flightsite.metadata.sources.routes import VrsRoutesProvider
from tests.metadata.sources.test_routes import (
    IMPORTED_CALLSIGNS,
    ROOT,
    archive_bytes,
    csv_bytes,
    row,
)

MICTRONICS = "mictronics"


@pytest.fixture(autouse=True)
def _small_floors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scale the archive floors down to fixture size. See the module docstring."""
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_ARTIFACT_BYTES", 1)
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_ROUTE_FILES", 1)
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_EXPECTED_ROWS", 1)
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_SAMPLE_PASS_RATIO", 0.5)


@pytest.fixture
def directory(database: Database) -> RouteDirectoryRepository:
    """The ``route_directory`` repository over the migrated database."""
    return RouteDirectoryRepository(database)


def provider_over(payload: bytes, *, status_code: int = 200) -> VrsRoutesProvider:
    """A provider whose client answers with ``payload`` and never opens a socket."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=payload)

    return VrsRoutesProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def refusing_provider() -> VrsRoutesProvider:
    """A provider whose transport always refuses — an offline install."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network in tests", request=request)

    return VrsRoutesProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


class ScriptedAircraftProvider:
    """A minimal aircraft-metadata source, for the independence assertions.

    Its only job is to be *another* registered source, so "one source failing
    leaves the other alone" is a claim about two real sources rather than about
    a mock of the pipeline.
    """

    def __init__(self, *, fail: bool = False) -> None:
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
        return iter((normalize_record(icao24="a1b2c3", registration="N1AB"),))


def registry_with_routes(
    repository: RouteDirectoryRepository, provider: VrsRoutesProvider
) -> SourceRegistry:
    registry = SourceRegistry()
    registry.register(ROUTES_SOURCE, provider, sink=RouteDirectoryImportSink(repository))
    return registry


@pytest.fixture
async def imported(
    database: Database,
    live: LiveStore,
    directory: RouteDirectoryRepository,
    isolated_data_dir: Path,
) -> AsyncIterator[RouteDirectoryRepository]:
    """A directory holding the fixture archive's routes."""
    registry = registry_with_routes(directory, provider_over(archive_bytes()))
    service = MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=registry
    )
    run = await service.update()
    assert run.succeeded == (ROUTES_SOURCE,), run.results
    yield directory


# ------------------------------------------------------------- normalization


def test_a_two_leg_route_normalizes_to_its_ends() -> None:
    record = normalize_route(callsign="baw1 ", airport_codes="egll-kjfk", airline_code="baw")

    assert record.callsign == "BAW1"
    assert record.airport_codes == "EGLL-KJFK"
    assert record.airline_code == "BAW"
    assert (record.origin_ident, record.destination_ident) == ("EGLL", "KJFK")


def test_a_multi_leg_route_keeps_its_stops() -> None:
    record = normalize_route(callsign="AAE124", airport_codes="VHHH-UACC-EBLG")

    assert record.path == ("VHHH", "UACC", "EBLG")
    assert (record.origin_ident, record.destination_ident) == ("VHHH", "EBLG")


def test_the_route_info_a_two_leg_row_yields_names_its_source() -> None:
    """``vrs`` is what reaches ``sightings.route_source`` and ``provenance``."""
    route = normalize_route(callsign="BAW1", airport_codes="EGLL-KJFK").route_info()

    assert (route.origin_ident, route.destination_ident) == ("EGLL", "KJFK")
    assert route.source == ROUTE_SOURCE_VRS
    assert route.extras == {}


def test_a_multi_leg_row_carries_its_path_as_a_diagnostic_extra() -> None:
    """The stops are the only record of *why* the ends are what they are."""
    route = normalize_route(callsign="AAE124", airport_codes="VHHH-UACC-EBLG").route_info()

    assert route.extras == {"path": "VHHH-UACC-EBLG"}


@pytest.mark.parametrize(
    "callsign",
    [
        pytest.param("N523GB", id="registration-flown-as-callsign"),
        pytest.param("BM2003", id="two-letter-designator"),
        pytest.param("", id="blank"),
        pytest.param(None, id="absent"),
        pytest.param("DAL12345678", id="longer-than-a-flight-id"),
    ],
)
def test_a_callsign_no_lookup_could_ask_for_is_refused(callsign: str | None) -> None:
    """The table holds only rows the enrichment worker could ever key on."""
    with pytest.raises(RouteRecordError):
        normalize_route(callsign=callsign, airport_codes="EGLL-KJFK")


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("", id="empty"),
        pytest.param(None, id="absent"),
        pytest.param("EGLL", id="one-airport-is-not-a-route"),
        pytest.param("EGLL-", id="trailing-separator-leaves-one"),
        pytest.param("EGLL-KJF!", id="not-an-airport-code"),
        pytest.param("EGLL-TOOLONG", id="too-long-for-an-ident"),
        pytest.param("-".join(["EGLL"] * (MAX_PATH_CODES + 1)), id="implausibly-many-legs"),
    ],
)
def test_an_unusable_path_is_refused(path: str | None) -> None:
    with pytest.raises(RouteRecordError):
        normalize_route(callsign="BAW1", airport_codes=path)


def test_a_malformed_airline_code_is_dropped_rather_than_failing_the_row() -> None:
    """The designator is a label; the route is what the row is for."""
    record = normalize_route(callsign="BAW1", airport_codes="EGLL-KJFK", airline_code="!!!!")

    assert record.airline_code is None
    assert record.airport_codes == "EGLL-KJFK"


def test_the_sink_re_normalizes_rather_than_trusting_the_provider() -> None:
    """The ADR-0006 boundary enforced: a padded key is a row nothing can find."""
    sink = RouteDirectoryImportSink(RouteDirectoryRepository(None))  # type: ignore[arg-type]

    canonical = sink.canonical(RouteDirectoryRecord(callsign=" baw1 ", airport_codes="egll-kjfk"))

    assert canonical is not None
    assert canonical.callsign == "BAW1"
    assert canonical.airport_codes == "EGLL-KJFK"


def test_the_sink_rejects_a_row_it_cannot_normalize() -> None:
    sink = RouteDirectoryImportSink(RouteDirectoryRepository(None))  # type: ignore[arg-type]

    assert sink.canonical(RouteDirectoryRecord(callsign="", airport_codes="")) is None
    assert sink.canonical(object()) is None


# ------------------------------------------------------------------ storage


async def test_a_lookup_finds_an_imported_route(
    imported: RouteDirectoryRepository,
) -> None:
    found = await imported.lookup("BAW1")

    assert found is not None
    assert found.airport_codes == "EGLL-KJFK"


async def test_a_lookup_normalizes_the_key_it_is_given(
    imported: RouteDirectoryRepository,
) -> None:
    """One spelling of a callsign, decided in one place."""
    assert await imported.lookup(" baw1 ") is not None


async def test_a_lookup_for_an_unknown_callsign_answers_nothing(
    imported: RouteDirectoryRepository,
) -> None:
    assert await imported.lookup("DAL1234") is None


async def test_promoting_nothing_is_refused(
    directory: RouteDirectoryRepository,
) -> None:
    """Emptying the directory is never what an import means to do."""
    with pytest.raises(RouteDirectoryError):
        await directory.promote(source=ROUTES_SOURCE, at_ms=1, dataset_version="v1")


# ------------------------------------------------------------- the pipeline


async def test_an_import_fills_the_directory_and_reports_its_status(
    database: Database,
    live: LiveStore,
    directory: RouteDirectoryRepository,
    isolated_data_dir: Path,
) -> None:
    """The whole pipeline: download, validate, stage, promote, report."""
    registry = registry_with_routes(directory, provider_over(archive_bytes()))
    service = MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=registry
    )

    run = await service.update()

    result = run.results[0]
    assert result.ok
    assert result.rows_imported == len(IMPORTED_CALLSIGNS)
    # The row with a good callsign and no path — counted, not silently dropped.
    assert result.rows_rejected == 1
    assert await directory.count() == len(IMPORTED_CALLSIGNS)

    statuses = {record.source: record for record in await service.statuses()}
    assert statuses[ROUTES_SOURCE].status is SourceStatus.OK
    assert statuses[ROUTES_SOURCE].row_count == len(IMPORTED_CALLSIGNS)
    assert statuses[ROUTES_SOURCE].dataset_version == result.dataset_version
    assert statuses[ROUTES_SOURCE].dataset_version is not None


async def test_every_row_carries_the_version_it_was_imported_from(
    imported: RouteDirectoryRepository,
) -> None:
    """The table is replaced whole, so a row cannot outlive its snapshot."""
    version = await imported.dataset_version()

    assert version is not None
    assert version.startswith("sha256:")


async def test_a_second_import_replaces_the_directory_rather_than_merging(
    database: Database,
    live: LiveStore,
    directory: RouteDirectoryRepository,
    isolated_data_dir: Path,
) -> None:
    """A retired flight number must not survive the snapshot that dropped it."""
    members = {
        f"{ROOT}/routes/schema-01/D/DAL-all.csv": csv_bytes((row("DAL1", "DAL", "KATL-KSLC"),))
    }
    registry = registry_with_routes(directory, provider_over(archive_bytes()))
    service = MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=registry
    )
    await service.update()

    second = registry_with_routes(directory, provider_over(archive_bytes(members)))
    replaced = MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=second
    )
    await replaced.update()

    assert await directory.lookup("DAL1") is not None
    assert await directory.lookup("BAW1") is None
    assert await directory.count() == 1


async def test_a_failed_import_leaves_the_previous_directory_intact(
    database: Database,
    live: LiveStore,
    directory: RouteDirectoryRepository,
    isolated_data_dir: Path,
) -> None:
    """The pipeline's guarantee, for this dataset: a bad day changes nothing."""
    good = registry_with_routes(directory, provider_over(archive_bytes()))
    await MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=good
    ).update()
    before = await directory.count()

    offline = registry_with_routes(directory, refusing_provider())
    run = await MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=offline
    ).update()

    assert run.failed == (ROUTES_SOURCE,)
    assert await directory.count() == before
    assert await directory.lookup("BAW1") is not None


async def test_a_failing_route_import_leaves_the_aircraft_sources_alone(
    database: Database,
    live: LiveStore,
    directory: RouteDirectoryRepository,
    isolated_data_dir: Path,
) -> None:
    """SPEC §27: one source's outcome is nobody else's."""
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider())
    registry.register(ROUTES_SOURCE, refusing_provider(), sink=RouteDirectoryImportSink(directory))
    service = MetadataService(
        database=database, live=live, data_dir=isolated_data_dir, registry=registry
    )

    run = await service.update()

    assert run.succeeded == (MICTRONICS,)
    assert run.failed == (ROUTES_SOURCE,)


async def test_clearing_the_metadata_cache_empties_the_directory(
    imported: RouteDirectoryRepository,
) -> None:
    """SPEC §73: the next update recreates every row this deletes."""
    removed = await imported.clear_all()

    assert removed == len(IMPORTED_CALLSIGNS)
    assert await imported.count() == 0
    assert await imported.dataset_version() is None


# ------------------------------------------------------------- precedence


def test_the_routes_source_is_outside_the_airframe_precedence_model(
    directory: RouteDirectoryRepository,
) -> None:
    """It writes no ``aircraft_metadata`` row, so it has no field to win.

    The same exclusion slice 027's ``airports`` gets, and by the same
    mechanism: a source carrying a sink of its own is not in the model, so its
    name can never appear in a ``*_src`` column.
    """
    registry = SourceRegistry()
    registry.register(MICTRONICS, ScriptedAircraftProvider())
    registry.register(ROUTES_SOURCE, VrsRoutesProvider(), sink=RouteDirectoryImportSink(directory))

    assert ROUTES_SOURCE in registry
    assert set(registry.precedence().priorities) == {MICTRONICS}
