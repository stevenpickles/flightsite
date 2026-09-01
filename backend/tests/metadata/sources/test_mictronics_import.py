"""End-to-end: a real-format Mictronics snapshot through the real pipeline.

Unlike :mod:`tests.metadata.sources.test_mictronics`, which exercises the
provider's three methods directly, this runs the actual
:class:`~flightsite.metadata.importer.MetadataImporter` against a registered
:class:`~flightsite.metadata.sources.mictronics.MictronicsProvider` — the
path a real "Update Aircraft Metadata" run takes — and checks what lands in
``aircraft_metadata_resolved``, including provenance and precedence against a
second source.
"""

from __future__ import annotations

import httpx
import pytest

from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.repository import AircraftLookup, MetadataRepository
from flightsite.metadata.sources import mictronics
from flightsite.metadata.sources.mictronics import MictronicsProvider
from tests.metadata.conftest import record, resolved_rows
from tests.metadata.provider import InMemoryMetadataProvider
from tests.metadata.sources.conftest import SAMPLE_MARKER_ICAOS


def _mictronics_provider(
    sample_gzip_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> MictronicsProvider:
    """A real provider wired to an in-process transport serving the fixture.

    The size floor is dropped to match the fixture, which is far smaller than
    a real ~8 MB snapshot (see ``tests.metadata.sources.conftest``).
    """
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sample_gzip_bytes)

    return MictronicsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_a_real_snapshot_imports_with_mictronics_provenance(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    sample_gzip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry.register("mictronics", _mictronics_provider(sample_gzip_bytes, monkeypatch))

    run = await importer.run()

    assert run.results[0].source == "mictronics"
    assert run.results[0].ok
    assert run.results[0].rows_imported == 32  # the fixture's 32 real airframe rows

    metadata = (await resolved_rows(repository, ["a1bcca"]))["a1bcca"]
    assert metadata.registration == "N21065"
    assert metadata.registration_src == "mictronics"
    assert metadata.type_code == "P28A"
    assert metadata.type_code_src == "mictronics"
    assert metadata.operator_name == "OMNI MANAGEMENT LLC"
    assert metadata.operator_src == "mictronics"
    assert metadata.manufacture_year == 1978
    assert metadata.year_src == "mictronics"

    # ICAO-block bookkeeping rows are not aircraft and never reach the resolved table.
    marker_view = await repository.load_live_view([icao.lower() for icao in SAMPLE_MARKER_ICAOS])
    assert all(entry == AircraftLookup() for entry in marker_view.values())


async def test_mictronics_and_faa_resolve_per_field_precedence(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    sample_gzip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC/roadmap: Mictronics leads identity and type; FAA leads year and owner."""
    registry.register("mictronics", _mictronics_provider(sample_gzip_bytes, monkeypatch))
    registry.register(
        "faa",
        InMemoryMetadataProvider(
            [record("a1bcca", registration="N1ZZ", manufacture_year=1980, owner="Someone")]
        ),
    )

    await importer.run()

    resolved = (await resolved_rows(repository, ["a1bcca"]))["a1bcca"]
    assert resolved.registration == "N21065"
    assert resolved.registration_src == "mictronics"
    assert resolved.type_code == "P28A"
    assert resolved.type_code_src == "mictronics"
    # FAA wins manufacture year (rank 0 there vs. mictronics' rank 1)...
    assert resolved.manufacture_year == 1980
    assert resolved.year_src == "faa"
    # ...and owner outright, since mictronics never supplies one.
    assert resolved.owner == "Someone"
    assert resolved.owner_src == "faa"
