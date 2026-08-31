"""Shared helpers for ingestion tests: fixtures, fake transport, fake clock.

Every test here runs against an injected HTTP transport and an injected sleep,
so the whole suite — including the reconnect and backoff tests, which cover
minutes of simulated outage — finishes in milliseconds and never touches the
network.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest

from flightsite.counters import CounterRegistry
from flightsite.ingest.types import DecoderEndpoint

FIXTURE_DIR = Path(__file__).parent / "fixtures"
MALFORMED_DIR = FIXTURE_DIR / "malformed"

#: The endpoint every test polls. Nothing listens on it; the transport is fake.
TEST_ENDPOINT = DecoderEndpoint(host="decoder.test", port=8080, path="/data/aircraft.json")


def fixture_bytes(name: str) -> bytes:
    """Read a fixture verbatim, including deliberately broken ones."""
    return (FIXTURE_DIR / name).read_bytes()


def fixture_document(name: str) -> Any:
    """Read and decode a well-formed fixture document."""
    return json.loads(fixture_bytes(name))


def malformed_paths() -> list[Path]:
    """Every file in the malformed corpus, in a stable order."""
    return sorted(MALFORMED_DIR.iterdir())


class RecordedSleep:
    """An awaitable stand-in for :func:`asyncio.sleep` that records delays.

    Returning immediately is what lets a test walk an adapter through a
    ten-minute outage without waiting for one; the recorded list is then the
    backoff schedule, available for assertion.
    """

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


ResponseHandler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)


class ScriptedTransport:
    """Serves a scripted sequence of responses (or raises) per request.

    Each script entry is either an :class:`httpx.Response` or an exception to
    raise; the last entry repeats once the script is exhausted, so a test can
    say "fail three times, then serve this forever".
    """

    def __init__(self, script: list[httpx.Response | Exception]) -> None:
        if not script:
            raise ValueError("script must not be empty")
        self.script = script
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.script) - 1)
        entry = self.script[index]
        if isinstance(entry, Exception):
            raise entry
        # Responses are consumed by streaming reads, so hand out a fresh copy
        # rather than a used one when the last entry repeats.
        return httpx.Response(
            status_code=entry.status_code, content=entry.content, headers=entry.headers
        )

    @property
    def call_count(self) -> int:
        """How many requests the transport has served."""
        return len(self.requests)


class CountingClientFactory:
    """Builds mock-transport clients and remembers how many it built.

    The count is how a test observes the adapter rebuilding its HTTP client
    when the decoder goes down.
    """

    def __init__(self, handler: ResponseHandler) -> None:
        self.handler = handler
        self.clients: list[httpx.AsyncClient] = []

    def __call__(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        self.clients.append(client)
        return client

    @property
    def build_count(self) -> int:
        """How many clients have been built."""
        return len(self.clients)


def json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    """Build a JSON response for a scripted transport."""
    return httpx.Response(status_code=status_code, json=payload)


@pytest.fixture(autouse=True)
def _isolated_ingestion_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ingestion failures out of the process-wide counter registry.

    ``flightsite.counters.counters`` is a module singleton that the health
    payload reports, so a test which starts a real ingestion loop against an
    unreachable decoder would otherwise leave ``ingestion_failures`` non-zero
    for every test that runs afterwards. Adapters resolve the default registry
    at call time, so redirecting the name here isolates them completely;
    ``monkeypatch`` restores it at teardown.
    """
    monkeypatch.setattr("flightsite.ingest.readsb.counters", CounterRegistry())


@pytest.fixture
def counters() -> CounterRegistry:
    """A private counter registry, so tests never observe each other."""
    return CounterRegistry()


@pytest.fixture
def readsb_document() -> Any:
    """The readsb ``aircraft.json`` fixture, decoded."""
    return fixture_document("readsb_aircraft.json")


@pytest.fixture
def dump1090fa_document() -> Any:
    """The modern dump1090-fa ``aircraft.json`` fixture, decoded."""
    return fixture_document("dump1090fa_aircraft.json")


@pytest.fixture
def dump1090fa_legacy_document() -> Any:
    """The legacy (pre-4.0) dump1090-fa ``aircraft.json`` fixture, decoded."""
    return fixture_document("dump1090fa_legacy_aircraft.json")
