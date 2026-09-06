"""``metadata.source_url_overrides`` through a real socket (issue #112).

Every other import test in this package reaches the provider through an
``httpx.MockTransport``: the fetch is *described* rather than performed, and
the one layer a mirror or a proxy would actually change — the HTTP client and
the URL it is handed — is the layer that never runs. That was the gap issue
#112 recorded, and it is why an integration test could not exercise the real
fetch path at all.

So this module does the opposite. A real ``ThreadingHTTPServer`` on
``127.0.0.1`` serves the same curated fixture the mock-transport tests use, the
URL of that server goes into ``metadata.source_url_overrides``, and the
provider is built by :func:`flightsite.app._build_metadata_registry` from those
settings — no argument passed by hand, nothing stubbed. What runs is
configuration → registry construction → ``httpx`` → a TCP connection → the
provider's own download, validation and transform → the importer → resolved
rows.

The one concession is the artifact-size floor, dropped to match a fixture that
is 32 airframes rather than 8 MB of them. That floor is a *content* check with
its own dedicated tests; it is not part of the path under test here.

The wiring-only tests read each provider's private URL attribute. That is
deliberate and is the honest cheaper option: the alternative — standing up five
mirrors and running five real imports to observe five URLs — would test the
five providers all over again rather than the one thing in question, which is
whether the configured URL reached the provider that will use it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from flightsite.airports import AirportRepository
from flightsite.app import _build_metadata_registry
from flightsite.config import Settings
from flightsite.config.models import MetadataSettings
from flightsite.db import Database
from flightsite.enrichment import RouteDirectoryRepository
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.repository import MetadataRepository
from flightsite.metadata.sources import faa, mictronics
from tests.metadata.conftest import resolved_rows

#: Path the fixture mirror serves the artifact at. Deliberately not the real
#: artifact's path: a provider that ignored the override and fell back to its
#: own URL would not reach this server at all.
ARTIFACT_PATH = "/mirror/aircraft.csv.gz"


@dataclass(slots=True)
class Mirror:
    """A running fixture server: where to fetch from, and what was fetched."""

    url: str = ""
    body: bytes = b""
    requested: list[str] = field(default_factory=list)


def _handler_for(mirror: Mirror) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        """Serves one artifact and records every path that was asked for."""

        def do_GET(self) -> None:  # the stdlib's spelling, not ours
            mirror.requested.append(self.path)
            if self.path != ARTIFACT_PATH:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(len(mirror.body)))
            self.end_headers()
            self.wfile.write(mirror.body)

        def log_message(self, format: str, *args: object) -> None:
            """Silence the stdlib's stderr logging; the test reads `requested`."""

    return _Handler


@pytest.fixture
def mirror(sample_gzip_bytes: bytes) -> Iterator[Mirror]:
    """A real HTTP server on a loopback port, serving the fixture artifact."""
    running = Mirror(body=sample_gzip_bytes)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(running))
    running.url = f"http://127.0.0.1:{server.server_port}{ARTIFACT_PATH}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield running
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _settings(data_dir: Path, **overrides: str) -> Settings:
    return Settings(
        data_dir=data_dir,
        metadata=MetadataSettings.model_validate({"source_url_overrides": overrides}),
    )


def _registry(settings: Settings, database: Database) -> SourceRegistry:
    """The application's own registry builder, over these settings.

    The real function rather than a rebuilt one, so a test cannot pass while
    the product wires the override somewhere else — or nowhere.
    """
    return _build_metadata_registry(
        AirportRepository(database), RouteDirectoryRepository(database), settings
    )


def _url_of(registry: SourceRegistry, source: str) -> str:
    """The URL a registered provider will actually fetch from."""
    provider = registry.get(source).provider
    url = getattr(provider, "_artifact_url", None)
    return str(url if url is not None else provider._url)  # type: ignore[attr-defined]


async def test_an_override_imports_from_a_local_server_over_the_real_fetch_path(
    mirror: Mirror,
    database: Database,
    repository: MetadataRepository,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acceptance criterion: a real import through an override URL."""
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)
    settings = _settings(isolated_data_dir, mictronics=mirror.url)
    # Only the overridden source, so the run cannot reach the internet for the
    # others — the provider is still the one the product's builder produced.
    registry = SourceRegistry()
    registry.register("mictronics", _registry(settings, database).get("mictronics").provider)
    importer = MetadataImporter(database=database, registry=registry, data_dir=isolated_data_dir)

    run = await importer.run()

    assert [result.source for result in run.results] == ["mictronics"]
    assert run.results[0].ok, run.results[0].error
    assert run.results[0].rows_imported == 32
    # The bytes really did come off a socket, and off *this* server's path.
    assert mirror.requested == [ARTIFACT_PATH]
    metadata = (await resolved_rows(repository, ["a1bcca"]))["a1bcca"]
    assert metadata.registration == "N21065"
    assert metadata.operator_name == "OMNI MANAGEMENT LLC"


def test_an_unset_source_keeps_its_own_default_url(
    database: Database, isolated_data_dir: Path
) -> None:
    """An override is per source: naming one leaves the rest alone."""
    settings = _settings(isolated_data_dir, mictronics="http://127.0.0.1:1/x.csv.gz")

    registry = _registry(settings, database)

    assert _url_of(registry, "mictronics") == "http://127.0.0.1:1/x.csv.gz"
    assert _url_of(registry, "faa") == faa.DEFAULT_URL


def test_every_dataset_source_honours_its_override(
    database: Database, isolated_data_dir: Path
) -> None:
    """All five, so a source added later cannot quietly opt out of the map."""
    settings = Settings(
        data_dir=isolated_data_dir,
        metadata=MetadataSettings.model_validate(
            {
                "opensky_enabled": True,
                "source_url_overrides": {
                    "mictronics": "http://127.0.0.1:1/m.csv.gz",
                    "faa": "http://127.0.0.1:1/f.zip",
                    "opensky": "http://127.0.0.1:1/o.csv",
                    "airports": "http://127.0.0.1:1/a.csv",
                    "routes": "http://127.0.0.1:1/r.zip",
                },
            }
        ),
    )

    registry = _registry(settings, database)

    assert _url_of(registry, "mictronics") == "http://127.0.0.1:1/m.csv.gz"
    assert _url_of(registry, "faa") == "http://127.0.0.1:1/f.zip"
    assert _url_of(registry, "opensky") == "http://127.0.0.1:1/o.csv"
    assert _url_of(registry, "airports") == "http://127.0.0.1:1/a.csv"
    assert _url_of(registry, "routes") == "http://127.0.0.1:1/r.zip"


@pytest.mark.parametrize("value", ["file:///etc/passwd", "not-a-url", "ftp://mirror/a.csv"])
def test_a_non_http_override_is_refused_by_configuration(
    isolated_data_dir: Path, value: str
) -> None:
    """``HttpUrl`` is the guard: a typo cannot become a file read."""
    with pytest.raises(ValueError, match="source_url_overrides"):
        _settings(isolated_data_dir, mictronics=value)


def test_a_blank_source_name_is_refused(isolated_data_dir: Path) -> None:
    with pytest.raises(ValueError, match="source_url_overrides"):
        _settings(isolated_data_dir, **{"   ": "http://127.0.0.1:1/x"})


class RecordedLogs:
    """A stand-in for ``flightsite.app``'s module logger.

    Substituted for the logger rather than captured through structlog, for the
    reason ``tests/enrichment/test_economy.py`` gives: by this point in a full
    suite another test has usually built the real application, which configures
    structlog with cached bound loggers that neither ``capture_logs`` nor
    ``caplog`` can intercept. Replacing the name is exact, and it is the same
    seam the code itself uses.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))

    debug = info = warning = error = _record

    def named(self, event: str) -> list[dict[str, object]]:
        return [fields for name, fields in self.events if name == event]


def test_an_override_naming_no_source_is_a_warning_not_a_failure(
    database: Database, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo must be visible, and must not stop the app from starting."""
    logs = RecordedLogs()
    monkeypatch.setattr("flightsite.app.logger", logs)
    settings = _settings(isolated_data_dir, mictonics="http://127.0.0.1:1/typo.csv.gz")

    registry = _registry(settings, database)

    assert "mictronics" in registry.names
    assert _url_of(registry, "mictronics") == mictronics.DEFAULT_ARTIFACT_URL
    assert [entry["source"] for entry in logs.named("metadata_source_url_override_unused")] == [
        "mictonics"
    ]


def test_an_override_that_is_used_says_so(
    database: Database, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: an operator must be able to tell a mirror is in use."""
    logs = RecordedLogs()
    monkeypatch.setattr("flightsite.app.logger", logs)
    settings = _settings(isolated_data_dir, mictronics="http://mirror.lan/a.csv.gz")

    _registry(settings, database)

    assert [entry["source"] for entry in logs.named("metadata_source_url_overridden")] == [
        "mictronics"
    ]
    assert logs.named("metadata_source_url_override_unused") == []
