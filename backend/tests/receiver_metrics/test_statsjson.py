"""Normalizing ``stats.json``, and degrading when there is none.

The roadmap's acceptance criterion for this half of the slice is *"dump1090-fa
missing metrics degrade gracefully"*, and SPEC §60 states the rule it comes
from: consume decoder-native statistics *when available*, normalize the common
fields, and gracefully hide what a decoder does not support. So these tests are
mostly about **absence** — that a smaller decoder yields a smaller set of real
values rather than a full set of invented ones, and that no absence anywhere
turns into a zero.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from flightsite.ingest import DecoderEndpoint, DecoderParseError
from flightsite.receiver_metrics.model import DecoderStats
from flightsite.receiver_metrics.statsjson import (
    MAX_DOCUMENT_BYTES,
    StatsJsonPoller,
    parse_stats_document,
    stats_url_for,
)
from tests.receiver_metrics.conftest import (
    ENDPOINT,
    STATS_URL,
    dump1090fa_stats,
    readsb_stats,
    stats_poller,
    status_poller,
)

# --------------------------------------------------------------- the URL


def test_the_statistics_url_sits_beside_the_aircraft_document() -> None:
    """One configured endpoint, not two: §11's decoder seam has a single address."""
    assert stats_url_for(ENDPOINT) == STATS_URL


def test_a_relocated_document_root_moves_both_documents_together() -> None:
    """A user who moved aircraft.json did not leave stats.json behind."""
    endpoint = DecoderEndpoint(host="pi.local", port=8754, path="/skyaware/data/aircraft.json")

    assert stats_url_for(endpoint) == "http://pi.local:8754/skyaware/data/stats.json"


def test_a_document_at_the_root_still_resolves() -> None:
    """The degenerate path a hand-edited config can produce."""
    endpoint = DecoderEndpoint(host="h", port=80, path="/aircraft.json")

    assert stats_url_for(endpoint) == "http://h:80/stats.json"


# ------------------------------------------------------------ normalization


def test_readsb_yields_the_full_normalized_set() -> None:
    """The rich decoder: every column §6.1 can source from a decoder is present."""
    stats = parse_stats_document(readsb_stats())

    assert stats == DecoderStats(
        messages_total=4_212_345,
        positions_total=45_678 + 52_341,
        rssi_avg_db=-14.2,
        rssi_peak_db=-2.1,
        max_range_nm=189.05,
        uptime_s=24_800.0,
    )


def test_dump1090fa_yields_the_smaller_set_with_the_rest_absent() -> None:
    """SPEC §60's degradation, stated as which fields are ``None``.

    Absent, not zero: a peak signal of 0 dBFS would be a receiver saturating,
    and a maximum range of 0 nm would be a receiver hearing nothing.
    """
    stats = parse_stats_document(dump1090fa_stats())

    assert stats.messages_total == 1_004_221
    assert stats.positions_total == 12_004 + 15_887
    assert stats.rssi_avg_db == -18.7
    assert stats.uptime_s == 9_600.0
    assert stats.rssi_peak_db is None
    assert stats.max_range_nm is None


def test_a_modern_dump1090fa_that_does_report_peak_signal_is_read() -> None:
    """The degradation is per field, not per decoder: newer builds have it."""
    stats = parse_stats_document(dump1090fa_stats(peak_signal=-4.5))

    assert stats.rssi_peak_db == -4.5
    assert stats.max_range_nm is None


def test_positions_count_only_the_successful_decode_paths() -> None:
    """``global_ok`` + ``local_ok``, and nothing that is a second view of them.

    ``airborne`` classifies the same successful decodes again, so a naive sum
    over the ``cpr`` block would report roughly double the real position count.
    """
    document = readsb_stats(global_ok=10, local_ok=7)

    stats = parse_stats_document(document)

    assert stats.positions_total == 17
    assert document["total"]["cpr"]["airborne"] == 17  # the double, if summed


def test_the_cumulative_block_is_the_one_read() -> None:
    """The short windows are a differently-shaped answer to the same question."""
    document = readsb_stats(messages=4_212_345)
    document["last1min"]["messages"] = 1

    assert parse_stats_document(document).messages_total == 4_212_345


def test_a_document_with_no_total_block_yields_nothing_usable() -> None:
    """A shape this version does not recognise degrades like an absent endpoint."""
    stats = parse_stats_document({"last1min": {"messages": 12}})

    assert stats.is_empty


@pytest.mark.parametrize(
    "value",
    [None, "many", True, float("nan"), float("inf"), -1],
    ids=["null", "text", "boolean", "nan", "infinity", "negative"],
)
def test_an_unusable_counter_is_absent_rather_than_coerced(value: object) -> None:
    """A counter FlightSite cannot trust must not become a number in a rate.

    ``True`` is in the list because Python makes it an ``int``: a decoder field
    that arrived as ``true`` is a shape we do not understand, not the value one.
    """
    document = readsb_stats()
    document["total"]["messages"] = value

    assert parse_stats_document(document).messages_total is None


def test_a_backwards_uptime_is_absent_rather_than_negative() -> None:
    """A decoder whose clock stepped is not a decoder that ran for -3 hours."""
    document = readsb_stats()
    document["total"]["end"] = document["total"]["start"] - 10_800.0

    assert parse_stats_document(document).uptime_s is None


def test_a_document_that_is_not_an_object_is_a_parse_error() -> None:
    """A wrong URL or an interposed error page is worth counting, not ignoring."""
    with pytest.raises(DecoderParseError, match="must be a JSON object"):
        parse_stats_document([1, 2, 3])


# ------------------------------------------------------------------ polling


async def test_a_successful_poll_returns_normalized_statistics() -> None:
    poller = stats_poller(documents=[readsb_stats()])
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.failed is False
    assert poll.absent is False
    assert poll.stats is not None
    assert poll.stats.messages_total == 4_212_345


@pytest.mark.parametrize("status", [404, 410])
async def test_a_decoder_with_no_statistics_document_is_absent_not_failed(status: int) -> None:
    """The whole point of SPEC §60's "when available".

    ``absent`` rather than ``failed`` is what keeps a supported configuration
    out of the ingestion-failure count for the rest of the install's life.
    """
    poller = status_poller(status)
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.absent is True
    assert poll.failed is False
    assert poll.stats is None


@pytest.mark.parametrize("status", [500, 502, 403])
async def test_an_error_status_is_a_genuine_failure(status: int) -> None:
    """A decoder that is broken is not a decoder that has nothing to say."""
    poller = status_poller(status)
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.failed is True
    assert poll.absent is False
    assert poll.error is not None and str(status) in poll.error


async def test_an_unreachable_decoder_is_a_failure_and_not_an_exception() -> None:
    """Nothing a decoder does escapes ``poll`` — the contract the service relies on."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    poller = StatsJsonPoller(
        ENDPOINT,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.failed is True
    assert "could not reach" in (poll.error or "")


async def test_a_body_that_is_not_json_is_a_failure() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>Not Found</html>")
    )
    poller = StatsJsonPoller(
        ENDPOINT, client_factory=lambda: httpx.AsyncClient(transport=transport)
    )
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.failed is True
    assert "not valid JSON" in (poll.error or "")


async def test_an_oversized_document_is_refused_rather_than_buffered() -> None:
    """A misconfigured URL pointing at something enormous must not fill a Pi."""
    body = b'{"total": {"messages": 1, "padding": "' + b"x" * (MAX_DOCUMENT_BYTES + 64) + b'"}}'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    poller = StatsJsonPoller(
        ENDPOINT, client_factory=lambda: httpx.AsyncClient(transport=transport)
    )
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.failed is True
    assert "exceeds" in (poll.error or "")


async def test_a_document_that_parses_to_nothing_reports_absence() -> None:
    """A decoder answering with a statistics shape we cannot read is not broken."""
    poller = stats_poller(documents=[{"last5min": {"messages": 4}}])
    try:
        poll = await poller.poll()
    finally:
        await poller.stop()

    assert poll.absent is True
    assert poll.failed is False


async def test_the_poller_requests_the_statistics_url_and_nothing_else() -> None:
    """It must not touch the aircraft document; that endpoint is ingestion's."""
    requested: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=readsb_stats())

    poller = StatsJsonPoller(
        ENDPOINT,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(record)),
    )
    try:
        await poller.poll()
        await poller.poll()
    finally:
        await poller.stop()

    assert requested == [STATS_URL, STATS_URL]


async def test_the_default_client_is_a_plain_http_client() -> None:
    """No transport injected: the production path opens and closes cleanly.

    Nothing is polled, so no socket is dialled — the point is that building the
    client is not itself an act with side effects worth avoiding at startup.
    """
    poller = StatsJsonPoller(ENDPOINT)

    await poller.start()
    try:
        assert poller.url == STATS_URL
    finally:
        await poller.stop()


async def test_stopping_before_starting_is_safe() -> None:
    """Shutdown runs the same calls whether or not the service ever started."""
    poller = StatsJsonPoller(ENDPOINT)

    await poller.stop()
    await poller.stop()


async def test_starting_twice_opens_one_client() -> None:
    clients: list[httpx.AsyncClient] = []

    def build() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
        clients.append(client)
        return client

    poller = StatsJsonPoller(ENDPOINT, client_factory=build)
    try:
        await poller.start()
        await poller.start()
        await poller.poll()
    finally:
        await poller.stop()

    assert len(clients) == 1


def test_the_fixture_documents_really_do_differ_in_the_documented_way() -> None:
    """Guards the degradation tests against a fixture that lost its distinction."""
    rich: dict[str, Any] = readsb_stats()["total"]
    smaller: dict[str, Any] = dump1090fa_stats()["total"]

    assert "max_distance_in_nautical_miles" in rich
    assert "max_distance_in_nautical_miles" not in smaller
    assert "peak_signal" in rich["local"]
    assert "peak_signal" not in smaller["local"]
    # And what they share, so the normalization above is testing agreement
    # rather than two unrelated documents.
    assert {"messages", "cpr", "local", "start", "end"} <= set(rich) | set(smaller)
