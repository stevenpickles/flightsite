"""ReadsbJsonAdapter: polling, failure handling, reconnect and backoff.

Roadmap slice 007 acceptance: *"decoder outage triggers health transitions and
recovery without restart"*. Every test here injects a mock HTTP transport and
a recording sleep, so an outage lasting minutes of simulated time is exercised
in microseconds of real time and nothing touches the network.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
from typing import Any

import httpx
import pytest
import structlog

from flightsite.counters import CounterRegistry
from flightsite.ingest.health import BACKOFF_MAX_S, HealthState, HealthTracker
from flightsite.ingest.readsb import ReadsbJsonAdapter, build_client
from flightsite.ingest.types import AircraftStateBatch
from flightsite.logging import configure_logging

from .conftest import (
    TEST_ENDPOINT,
    CountingClientFactory,
    RecordedSleep,
    ScriptedTransport,
    json_response,
)


class StopPolling(Exception):
    """Raised from the injected sleep to end an all-failures test run."""


class LimitedSleep(RecordedSleep):
    """A recording sleep that aborts the loop after ``limit`` calls."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    async def __call__(self, delay: float) -> None:
        await super().__call__(delay)
        if len(self.delays) >= self.limit:
            raise StopPolling


def make_adapter(
    transport: ScriptedTransport,
    *,
    sleeper: RecordedSleep,
    counters: CounterRegistry,
    tracker: HealthTracker | None = None,
) -> tuple[ReadsbJsonAdapter, CountingClientFactory]:
    factory = CountingClientFactory(transport)
    adapter = ReadsbJsonAdapter(
        TEST_ENDPOINT,
        client_factory=factory,
        health_tracker=tracker if tracker is not None else HealthTracker(rng=random.Random(7)),
        counter_registry=counters,
        sleep=sleeper,
    )
    return adapter, factory


async def drain(adapter: ReadsbJsonAdapter, *, batches: int) -> list[AircraftStateBatch]:
    """Consume ``batches`` successful polls, then stop the adapter."""
    collected: list[AircraftStateBatch] = []
    async for batch in adapter.updates():
        collected.append(batch)
        if len(collected) >= batches:
            break
    await adapter.stop()
    return collected


def good_response(readsb_document: Any) -> httpx.Response:
    return json_response(readsb_document)


# ------------------------------------------------------------ happy path


async def test_endpoint_url_is_built_from_host_port_and_path() -> None:
    assert TEST_ENDPOINT.url == "http://decoder.test:8080/data/aircraft.json"


async def test_successful_polls_yield_normalized_batches(
    readsb_document: Any, counters: CounterRegistry
) -> None:
    transport = ScriptedTransport([good_response(readsb_document)])
    sleeper = RecordedSleep()
    adapter, _ = make_adapter(transport, sleeper=sleeper, counters=counters)

    batches = await drain(adapter, batches=3)

    assert len(batches) == 3
    assert all(len(batch) == 6 for batch in batches)
    assert adapter.health().state is HealthState.CONNECTED
    assert adapter.health().total_successes == 3
    assert counters.snapshot()["ingestion_failures"] == 0


async def test_polls_are_paced_by_the_configured_interval(
    readsb_document: Any, counters: CounterRegistry
) -> None:
    transport = ScriptedTransport([good_response(readsb_document)])
    sleeper = RecordedSleep()
    adapter, _ = make_adapter(transport, sleeper=sleeper, counters=counters)

    await drain(adapter, batches=3)

    # Two inter-poll waits for three polls: the third batch ends the loop.
    assert sleeper.delays == [TEST_ENDPOINT.poll_interval_s] * 2


async def test_adapter_requests_the_configured_url(
    readsb_document: Any, counters: CounterRegistry
) -> None:
    transport = ScriptedTransport([good_response(readsb_document)])
    adapter, _ = make_adapter(transport, sleeper=RecordedSleep(), counters=counters)

    await drain(adapter, batches=1)

    assert str(transport.requests[0].url) == TEST_ENDPOINT.url


# --------------------------------------------------------- failure modes


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(httpx.ConnectError("connection refused"), id="connection_refused"),
        pytest.param(httpx.ReadTimeout("timed out"), id="timeout"),
        pytest.param(httpx.Response(status_code=404, text="not found"), id="http_404"),
        pytest.param(httpx.Response(status_code=503, text="unavailable"), id="http_503"),
        pytest.param(httpx.Response(status_code=200, text="<html>404</html>"), id="not_json"),
        pytest.param(json_response({"now": 1758124800.1}), id="no_aircraft_array"),
        pytest.param(json_response([1, 2, 3]), id="wrong_document_shape"),
        pytest.param(RuntimeError("transport exploded"), id="unexpected_exception"),
    ],
)
async def test_no_failure_escapes_the_update_stream(
    failure: httpx.Response | Exception, counters: CounterRegistry
) -> None:
    transport = ScriptedTransport([failure])
    sleeper = LimitedSleep(limit=2)
    adapter, _ = make_adapter(transport, sleeper=sleeper, counters=counters)

    with pytest.raises(StopPolling):
        # StopPolling comes from the test's own sleep, not from the adapter:
        # reaching it proves the failure was absorbed and retried.
        async for _ in adapter.updates():
            pytest.fail("a failing decoder must not yield a batch")

    await adapter.stop()
    assert counters.snapshot()["ingestion_failures"] == 2
    assert adapter.health().state is HealthState.DEGRADED
    assert adapter.health().last_error


async def test_failures_are_retried_on_an_exponential_backoff(
    counters: CounterRegistry,
) -> None:
    transport = ScriptedTransport([httpx.ConnectError("connection refused")])
    sleeper = LimitedSleep(limit=8)
    adapter, _ = make_adapter(transport, sleeper=sleeper, counters=counters)

    with pytest.raises(StopPolling):
        async for _ in adapter.updates():
            pass
    await adapter.stop()

    # Jitter makes the exact values non-deterministic, so assert the shape:
    # each window doubles, nothing exceeds the cap, nothing is instantaneous.
    assert len(sleeper.delays) == 8
    assert all(0.0 < delay <= BACKOFF_MAX_S for delay in sleeper.delays)
    for index, delay in enumerate(sleeper.delays):
        ceiling = min(2.0**index, BACKOFF_MAX_S)
        assert delay <= ceiling
        assert delay >= ceiling / 2


async def test_the_backoff_stops_growing_at_the_cap(counters: CounterRegistry) -> None:
    transport = ScriptedTransport([httpx.ConnectError("gone")])
    sleeper = LimitedSleep(limit=40)
    adapter, _ = make_adapter(transport, sleeper=sleeper, counters=counters)

    with pytest.raises(StopPolling):
        async for _ in adapter.updates():
            pass
    await adapter.stop()

    assert max(sleeper.delays) <= BACKOFF_MAX_S
    assert sleeper.delays[-1] >= BACKOFF_MAX_S / 2


# ------------------------------------------------- outage and recovery


async def test_outage_transitions_to_down_then_recovers_without_a_restart(
    readsb_document: Any, counters: CounterRegistry
) -> None:
    transitions: list[tuple[HealthState, HealthState]] = []
    tracker = HealthTracker(
        rng=random.Random(11),
        on_transition=lambda previous, current, _h: transitions.append((previous, current)),
    )
    transport = ScriptedTransport(
        [
            good_response(readsb_document),
            httpx.ConnectError("connection refused"),
            httpx.ConnectError("connection refused"),
            httpx.ConnectError("connection refused"),
            httpx.ConnectError("connection refused"),
            good_response(readsb_document),
        ]
    )
    adapter, _ = make_adapter(
        transport, sleeper=RecordedSleep(), counters=counters, tracker=tracker
    )

    batches = await drain(adapter, batches=2)

    assert len(batches) == 2
    assert transitions == [
        (HealthState.DOWN, HealthState.CONNECTED),
        (HealthState.CONNECTED, HealthState.DEGRADED),
        (HealthState.DEGRADED, HealthState.DOWN),
        (HealthState.DOWN, HealthState.CONNECTED),
    ]
    assert adapter.health().state is HealthState.CONNECTED
    assert adapter.health().consecutive_failures == 0
    assert adapter.health().total_failures == 4
    assert counters.snapshot()["ingestion_failures"] == 4
    # Recovery happened inside the same running adapter.
    assert transport.call_count == 6


async def test_going_down_rebuilds_the_http_client(
    readsb_document: Any, counters: CounterRegistry
) -> None:
    transport = ScriptedTransport(
        [*[httpx.ConnectError("refused")] * 4, good_response(readsb_document)]
    )
    adapter, factory = make_adapter(transport, sleeper=RecordedSleep(), counters=counters)

    await adapter.start()
    assert factory.build_count == 1

    await drain(adapter, batches=1)

    # Connections pooled against a decoder that has evidently restarted are
    # dropped once it is declared down; the next poll dials fresh.
    assert factory.build_count == 2


async def test_health_transitions_are_logged(counters: CounterRegistry) -> None:
    configure_logging(level="INFO")
    stream = io.StringIO()
    for handler in logging.getLogger().handlers:
        handler.stream = stream  # type: ignore[attr-defined]

    transport = ScriptedTransport([httpx.ConnectError("connection refused")])
    factory = CountingClientFactory(transport)
    # No injected tracker: this exercises the adapter's own transition logger.
    adapter = ReadsbJsonAdapter(
        TEST_ENDPOINT,
        client_factory=factory,
        counter_registry=counters,
        sleep=LimitedSleep(limit=4),
    )

    with pytest.raises(StopPolling):
        async for _ in adapter.updates():
            pass
    await adapter.stop()

    for handler in logging.getLogger().handlers:
        handler.flush()
    events = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    changes = [event for event in events if event["event"] == "decoder_health_changed"]

    assert [change["current"] for change in changes] == ["degraded", "down"]
    assert changes[0]["url"] == TEST_ENDPOINT.url
    assert changes[-1]["error"] == "could not reach " + TEST_ENDPOINT.url + ": connection refused"


async def test_unexpected_errors_are_logged_as_such(counters: CounterRegistry) -> None:
    configure_logging(level="INFO")
    stream = io.StringIO()
    for handler in logging.getLogger().handlers:
        handler.stream = stream  # type: ignore[attr-defined]

    transport = ScriptedTransport([RuntimeError("transport exploded")])
    adapter, _ = make_adapter(transport, sleeper=LimitedSleep(limit=1), counters=counters)

    with pytest.raises(StopPolling):
        async for _ in adapter.updates():
            pass
    await adapter.stop()

    for handler in logging.getLogger().handlers:
        handler.flush()
    events = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    unexpected = [event for event in events if event["event"] == "decoder_poll_unexpected_error"]

    assert unexpected
    assert unexpected[0]["error_type"] == "RuntimeError"


# ----------------------------------------------------------- lifecycle


async def test_stop_is_idempotent_and_safe_before_start(counters: CounterRegistry) -> None:
    transport = ScriptedTransport([json_response({"now": 1758124800.1, "aircraft": []})])
    adapter, _ = make_adapter(transport, sleeper=RecordedSleep(), counters=counters)

    await adapter.stop()
    await adapter.start()
    await adapter.stop()
    await adapter.stop()

    assert adapter.health().state is HealthState.DOWN


async def test_a_stopped_adapter_yields_nothing(
    readsb_document: Any, counters: CounterRegistry
) -> None:
    transport = ScriptedTransport([good_response(readsb_document)])
    adapter, _ = make_adapter(transport, sleeper=RecordedSleep(), counters=counters)
    await adapter.stop()

    yielded = [batch async for batch in adapter.updates()]

    assert yielded == []
    assert transport.call_count == 0


async def test_oversized_documents_are_refused(
    counters: CounterRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Something answering on the decoder's port with an endless body must not
    # be buffered whole onto a Pi. The cap is shrunk rather than a 16 MB body
    # generated, so the test stays fast.
    monkeypatch.setattr("flightsite.ingest.readsb.MAX_DOCUMENT_BYTES", 512)
    oversized = json.dumps({"now": 1758124800.1, "aircraft": [{"hex": "4ca87c"}] * 200})
    transport = ScriptedTransport([httpx.Response(status_code=200, text=oversized)])
    adapter, _ = make_adapter(transport, sleeper=LimitedSleep(limit=1), counters=counters)

    with pytest.raises(StopPolling):
        async for _ in adapter.updates():
            pytest.fail("an oversized document must not yield a batch")
    await adapter.stop()

    assert counters.snapshot()["ingestion_failures"] == 1
    assert "exceeds" in (adapter.health().last_error or "")


async def test_cancellation_during_a_poll_is_not_swallowed(counters: CounterRegistry) -> None:
    polling = asyncio.Event()

    async def hang(_request: httpx.Request) -> httpx.Response:
        polling.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    adapter = ReadsbJsonAdapter(
        TEST_ENDPOINT,
        client_factory=CountingClientFactory(hang),
        counter_registry=counters,
        sleep=RecordedSleep(),
    )

    async def consume() -> None:
        async for _ in adapter.updates():
            pass  # pragma: no cover

    task = asyncio.create_task(consume())
    await asyncio.wait_for(polling.wait(), timeout=1.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    # Shutdown must not be mistaken for a decoder failure.
    assert counters.snapshot()["ingestion_failures"] == 0
    await adapter.stop()


def test_the_default_client_is_configured_with_a_timeout() -> None:
    client = build_client()

    assert client.timeout.read is not None
    assert client.follow_redirects is True


def test_the_adapter_exposes_its_endpoint(counters: CounterRegistry) -> None:
    adapter = ReadsbJsonAdapter(TEST_ENDPOINT, counter_registry=counters)

    assert adapter.endpoint is TEST_ENDPOINT


def test_adapter_satisfies_the_decoder_adapter_protocol(counters: CounterRegistry) -> None:
    from flightsite.ingest.protocol import DecoderAdapter

    assert isinstance(ReadsbJsonAdapter(TEST_ENDPOINT, counter_registry=counters), DecoderAdapter)


def test_structlog_is_configured_for_these_tests() -> None:
    # Guards the log-capture tests above: if structlog were not wired to the
    # stdlib root logger, they would silently assert nothing.
    configure_logging(level="INFO")
    assert structlog.is_configured()
