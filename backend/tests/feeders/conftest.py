"""Shared fixtures for the feeder tests: captured documents, fakes, a database.

The fixture documents under ``fixtures/`` are written from the field tables
in ``docs/design/077-feeders-page.md`` (the read-only survey of the reference
receiver) and anchored to :data:`FIXTURE_NOW_S`. The identity fields each
vendor must never let through carry ``SENTINEL`` values so a test can grep
any output for them.
"""

from __future__ import annotations

import json
import struct
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from flightsite.activity import FeederEpisode as OutageFact
from flightsite.counters import CounterRegistry
from flightsite.db import Database, database_path

FIXTURES = Path(__file__).parent / "fixtures"

#: The instant every fixture document was "captured" at (2026-09-21T14:13:20Z).
FIXTURE_NOW_S = 1_790_000_000
FIXTURE_NOW_MS = FIXTURE_NOW_S * 1000

#: Every sentinel planted in a fixture. None may ever appear in an output.
SENTINELS = (
    "SENTINEL-FR24-KEY",
    "SENTINEL-FR24-ALIAS",
    "SENTINEL-FR24-LEGACY",
    "SENTINEL-LOCAL-IP",
    "SENTINEL-FA-USER",
    "SENTINEL-FA-SITE",
    "51.12345678",
    "-1.98765432",
)

#: A stats URL configured in ``secrets.yaml`` in tests.
SECRET_STATS_URL = "https://stats.example.invalid/feeder/SENTINEL-STATS-URL-77"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def frame(payload: bytes, stream: int = 1) -> bytes:
    """One Docker multiplexed log frame."""
    return struct.pack(">BxxxI", stream, len(payload)) + payload


def framed_log(lines: Sequence[str], stream: int = 1) -> bytes:
    """A log body framed the way a non-TTY container's logs arrive."""
    return b"".join(frame(f"{line}\n".encode(), stream) for line in lines)


class ManualClock:
    """A hand-driven epoch-millisecond clock."""

    def __init__(self, now_ms: int = FIXTURE_NOW_MS) -> None:
        self.now_ms = now_ms

    def __call__(self) -> int:
        return self.now_ms

    def advance(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)


Handler = Callable[[httpx.Request], httpx.Response]


def routes(table: Mapping[str, Any | Handler]) -> httpx.MockTransport:
    """A mock transport answering by URL path; a value is JSON or a handler."""

    def handle(request: httpx.Request) -> httpx.Response:
        for path, answer in table.items():
            if request.url.path == path:
                if callable(answer):
                    response: httpx.Response = answer(request)
                    return response
                return httpx.Response(200, json=answer)
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def client_for(table: Mapping[str, Any | Handler]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=routes(table))


@dataclass(frozen=True)
class Entry:
    """A config entry, shaped like ``FeederSettings.entries[]``."""

    name: str
    label: str
    kind: str
    url: str | None = None
    web_url: str | None = None
    host: str | None = None
    mlat_port: int | None = None
    beast_port: int | None = None
    container: str | None = None


@dataclass(frozen=True)
class Page:
    label: str
    url: str


@dataclass(frozen=True)
class Settings:
    """A ``feeders`` section, shaped like B's ``FeederSettings``."""

    poll_interval_s: float = 15.0
    docker_socket: str | None = None
    entries: Sequence[Entry] = ()
    local_pages: Sequence[Page] = ()
    stats_urls: Mapping[str, SecretStr] = field(default_factory=dict)


@dataclass
class Transitions:
    """Records every outage fact the service announces."""

    facts: list[OutageFact] = field(default_factory=list)

    def __call__(self, fact: OutageFact) -> None:
        self.facts.append(fact)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def counters() -> CounterRegistry:
    return CounterRegistry(("feeder_poll_failures", "db_errors"))


@pytest.fixture
async def database(isolated_data_dir: Path) -> AsyncIterator[Database]:
    instance = Database(database_path(isolated_data_dir))
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()
