"""End-to-end: a real-format OpenSky snapshot through the real pipeline.

Unlike :mod:`tests.metadata.sources.test_opensky`, which exercises the
provider's three methods directly, this runs the actual
:class:`~flightsite.metadata.importer.MetadataImporter` against a registered
:class:`~flightsite.metadata.sources.opensky.OpenSkyProvider` — the path a real
"Update Aircraft Metadata" run takes — and checks what lands in
``aircraft_metadata_resolved``, that the fill-gaps-only policy survives the
round trip through storage, and that a failed OpenSky import leaves everything
else exactly as it was (``docs/SECURITY.md`` §4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.registry import SourceStatus, SourceStatusRecord
from flightsite.metadata.repository import MetadataRepository
from flightsite.metadata.sources import opensky
from flightsite.metadata.sources.opensky import OpenSkyProvider
from tests.metadata.conftest import DATASET_TABLES, dump, record, resolved_rows
from tests.metadata.provider import InMemoryMetadataProvider


@dataclass
class _Upstream:
    """A mutable stand-in for OpenSky, so one run can succeed and the next fail."""

    body: bytes
    status: int = 200

    def respond(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self.status, content=self.body)


def _opensky_provider(upstream: _Upstream, monkeypatch: pytest.MonkeyPatch) -> OpenSkyProvider:
    """A real provider wired to an in-process transport serving ``upstream``.

    The size floor is dropped to match the fixture, which is a handful of rows
    against a real ~94 MB snapshot.
    """
    monkeypatch.setattr(opensky, "MIN_ARTIFACT_BYTES", 10)

    return OpenSkyProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream.respond))
    )


async def _status(repository: MetadataRepository, source: str) -> SourceStatusRecord:
    """``read_status`` narrowed: these tests always run the source first."""
    status = await repository.read_status(source)
    assert status is not None, f"{source} should have a status row after a run"
    return status


async def test_a_real_snapshot_imports_with_opensky_provenance(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    opensky_csv_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry.register("opensky", _opensky_provider(_Upstream(opensky_csv_bytes), monkeypatch))

    run = await importer.run()

    assert run.results[0].source == "opensky"
    assert run.results[0].ok
    assert run.results[0].rows_imported == 7  # the fixture's 7 contributing rows

    resolved = (await resolved_rows(repository, ["ad4b72"]))["ad4b72"]
    assert resolved.operator_name == "Federal Express"
    assert resolved.operator_src == "opensky"
    assert resolved.owner == "Federal Express Corp"
    assert resolved.owner_src == "opensky"
    assert resolved.model == "Boeing 757-236"
    assert resolved.manufacture_year == 1998
    # Withheld by the adapter even though the upstream row carries both.
    assert resolved.registration is None
    assert resolved.type_code is None


async def test_a_run_records_a_dataset_version_for_opensky(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    opensky_csv_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The content hash is what ties resolved rows back to the bytes."""
    registry.register("opensky", _opensky_provider(_Upstream(opensky_csv_bytes), monkeypatch))

    await importer.run()

    status = await _status(repository, "opensky")
    assert status.status is SourceStatus.OK
    assert status.dataset_version is not None
    assert status.dataset_version.startswith("sha256:")
    assert status.row_count == 7


async def test_re_importing_an_unchanged_snapshot_reports_the_same_version(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    opensky_csv_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry.register("opensky", _opensky_provider(_Upstream(opensky_csv_bytes), monkeypatch))

    await importer.run()
    first = (await _status(repository, "opensky")).dataset_version
    await importer.run()
    second = (await _status(repository, "opensky")).dataset_version

    assert first == second


async def test_opensky_fills_only_the_gaps_the_other_sources_left(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    opensky_csv_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The slice's central guarantee, asserted through real storage.

    Mictronics claims the identity, type and operator of ``ad4b72``; OpenSky's
    row for the same airframe disagrees about the operator and adds an owner
    and a year. Only the additions may survive.
    """
    registry.register(
        "mictronics",
        InMemoryMetadataProvider(
            [
                record(
                    "ad4b72",
                    registration="N956FD",
                    type_code="B752",
                    model="Boeing 757-236",
                    operator_name="FedEx Express",
                )
            ]
        ),
    )
    registry.register("opensky", _opensky_provider(_Upstream(opensky_csv_bytes), monkeypatch))

    await importer.run()

    resolved = (await resolved_rows(repository, ["ad4b72"]))["ad4b72"]
    assert resolved.operator_name == "FedEx Express"
    assert resolved.operator_src == "mictronics"
    assert resolved.registration == "N956FD"
    assert resolved.registration_src == "mictronics"
    assert resolved.model_src == "mictronics"
    # The gaps mictronics left, and only those.
    assert resolved.owner == "Federal Express Corp"
    assert resolved.owner_src == "opensky"
    assert resolved.manufacture_year == 1998
    assert resolved.year_src == "opensky"


async def test_a_failed_opensky_import_leaves_the_previous_dataset_intact(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    db_path: Path,
    opensky_csv_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SECURITY §4: a failure never degrades what is already stored.

    The first run succeeds; the second serves a 500. The dataset must be byte
    identical afterwards, and the source's own status must record the failure
    without clearing its last success.
    """
    upstream = _Upstream(opensky_csv_bytes)
    registry.register("opensky", _opensky_provider(upstream, monkeypatch))
    await importer.run()

    before = dump(db_path, DATASET_TABLES)
    good_version = (await _status(repository, "opensky")).dataset_version

    upstream.status = 500
    upstream.body = b"upstream is having a bad day"
    run = await importer.run()

    assert not run.results[0].ok
    assert dump(db_path, DATASET_TABLES) == before, "a failed import must not touch stored rows"

    status = await _status(repository, "opensky")
    assert status.status is SourceStatus.FAILED
    assert status.last_error is not None
    assert status.dataset_version == good_version, "the good version survives the failure"
    assert status.last_success_ms is not None


async def test_a_malformed_opensky_download_is_refused_before_anything_is_promoted(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong-shaped file fails validation, not staging or promotion."""
    registry.register(
        "mictronics", InMemoryMetadataProvider([record("abc123", registration="G-ABCD")])
    )
    registry.register(
        "opensky", _opensky_provider(_Upstream(b"<html>not a csv at all</html>"), monkeypatch)
    )

    await importer.run()
    before = dump(db_path, DATASET_TABLES)

    run = await importer.run()

    opensky_result = next(result for result in run.results if result.source == "opensky")
    assert not opensky_result.ok
    assert dump(db_path, DATASET_TABLES) == before

    # The other source is entirely unaffected — SPEC §27 independence.
    mictronics_status = await _status(repository, "mictronics")
    assert mictronics_status.status is SourceStatus.OK
    resolved = (await resolved_rows(repository, ["abc123"]))["abc123"]
    assert resolved.registration == "G-ABCD"
