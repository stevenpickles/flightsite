"""Vendor parsers and probes against captured-shape fixtures.

One section per vendor module. Each reads the fixture its field table in
``docs/design/077-feeders-page.md`` describes, then mutates one field at a
time to prove each state rule — so a rule is tested by the field that drives
it, not by a second hand-written document that might drift from the first.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx

from flightsite.feeders.docker import DockerClient, LogLine, split_timestamp
from flightsite.feeders.fr24 import Fr24Probe, parse_monitor
from flightsite.feeders.model import FeederState, Observability
from flightsite.feeders.opensky import (
    STALE_AFTER_MS,
    OpenSkyLogsProbe,
    block_result,
    last_statistics_block,
)
from flightsite.feeders.piaware import PiawareProbe, parse_status
from flightsite.feeders.readsb import ReadsbProbe
from flightsite.feeders.ultrafeeder import (
    ZERO_PEER_TOLERANCE,
    UltrafeederProbe,
    mlat_stats_path,
    parse_mlat_stats,
)

from .conftest import (
    FIXTURE_NOW_MS,
    FIXTURE_NOW_S,
    client_for,
    framed_log,
    load_json,
    load_lines,
)

# ------------------------------------------------------------------ piaware


def piaware() -> dict[str, Any]:
    document: dict[str, Any] = load_json("piaware_status.json")
    return document


def test_piaware_all_green_is_up_with_detail() -> None:
    result, fallback = parse_status(piaware(), now_ms=FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert result.observability is Observability.HTTP
    assert result.last_data_sent_ms == FIXTURE_NOW_MS
    assert result.detail["version"] == "10.2"
    assert result.detail["cpu_temp_c"] == 48.7
    assert result.detail["connection"] == "green"
    assert result.detail["mlat"] == "green"
    assert fallback is not None and fallback.startswith("https://www.flightaware.com/")


def test_piaware_red_connection_is_down_with_its_message() -> None:
    document = piaware()
    document["adept"] = {"status": "red", "message": "Not connected to FlightAware"}

    result, _ = parse_status(document, now_ms=FIXTURE_NOW_MS)

    assert result.state is FeederState.DOWN
    assert result.message == "Not connected to FlightAware"
    assert result.last_data_sent_ms is None


def test_piaware_amber_light_or_unsynchronized_mlat_is_degraded() -> None:
    amber = piaware()
    amber["radio"] = {"status": "amber", "message": "No recent data"}
    mlat = piaware()
    mlat["mlat"] = {"status": "amber", "message": "MLAT not synchronized"}

    assert parse_status(amber, now_ms=FIXTURE_NOW_MS)[0].state is FeederState.DEGRADED
    result, _ = parse_status(mlat, now_ms=FIXTURE_NOW_MS)
    assert result.state is FeederState.DEGRADED
    assert result.message == "MLAT not synchronized"


def test_piaware_expired_status_is_down() -> None:
    result, _ = parse_status(piaware(), now_ms=FIXTURE_NOW_MS + 11_000)

    assert result.state is FeederState.DOWN
    assert "stopped refreshing" in (result.message or "")


async def test_piaware_probe_keeps_the_site_link_only_as_its_fallback() -> None:
    client = client_for({"/status.json": piaware()})
    probe = PiawareProbe("flightaware", url="http://piaware.test/status.json", client=client)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert probe.stats_fallback is not None
    assert "SENTINEL-FA-USER" in probe.stats_fallback
    assert "SENTINEL" not in repr(result)


async def test_piaware_probe_unreachable_is_a_failed_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    probe = PiawareProbe("flightaware", url="http://piaware.test/status.json", client=client)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.DOWN
    assert result.failed


# --------------------------------------------------------------------- fr24


def fr24() -> dict[str, Any]:
    document: dict[str, Any] = load_json("fr24_monitor.json")
    return document


def test_fr24_connected_is_up_with_coerced_strings() -> None:
    result = parse_monitor(fr24(), now_ms=FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert result.last_data_sent_ms == (FIXTURE_NOW_S - 2) * 1000
    assert result.detail["aircraft_sent"] == 38
    assert result.detail["messages"] == 12_345_678
    assert result.detail["receiver_input"] is True
    assert result.detail["server"] == "185.218.24.22"
    assert result.detail["version"] == "1.0.48-0"


def test_fr24_disconnected_is_down_with_the_status_message() -> None:
    document = fr24()
    document["feed_status"] = "disconnected"
    document["feed_status_message"] = "Network timeout"

    result = parse_monitor(document, now_ms=FIXTURE_NOW_MS)

    assert result.state is FeederState.DOWN
    assert result.message == "Network timeout"


def test_fr24_without_receiver_input_is_down() -> None:
    document = fr24()
    document["rx_connected"] = "0"

    assert parse_monitor(document, now_ms=FIXTURE_NOW_MS).state is FeederState.DOWN


def test_fr24_connected_but_silent_is_degraded() -> None:
    document = fr24()
    document["feed_last_ac_sent_time"] = str(FIXTURE_NOW_S - 600)

    assert parse_monitor(document, now_ms=FIXTURE_NOW_MS).state is FeederState.DEGRADED


def test_fr24_stale_monitor_is_down_but_a_misparsed_date_is_ignored() -> None:
    stale = fr24()
    stale["time_update_utc"] = str(FIXTURE_NOW_S - 300)
    nonsense = fr24()
    nonsense["time_update_utc"] = "1999-01-01 00:00:00"

    assert parse_monitor(stale, now_ms=FIXTURE_NOW_MS).state is FeederState.DOWN
    assert parse_monitor(nonsense, now_ms=FIXTURE_NOW_MS).state is FeederState.UP


async def test_fr24_probe_reads_the_configured_document() -> None:
    probe = Fr24Probe(
        "fr24", url="http://fr24.test/monitor.json", client=client_for({"/monitor.json": fr24()})
    )

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert not result.failed


# ------------------------------------------------------------------- readsb


def readsb_client(stats: dict[str, Any] | None = None) -> httpx.AsyncClient:
    return client_for(
        {
            "/data/status.json": load_json("readsb_status.json"),
            "/data/stats.json": stats if stats is not None else load_json("readsb_stats.json"),
        }
    )


async def test_readsb_reports_the_uplink_and_no_rate_on_the_first_poll() -> None:
    probe = ReadsbProbe("receiver", url="http://readsb.test:8080/", client=readsb_client())

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    uplink = result.receiver
    assert uplink is not None
    assert uplink.messages_per_min == 31_234
    assert uplink.aircraft_with_pos == 37
    assert uplink.aircraft_total == 49
    assert uplink.aircraft_mlat == 3
    assert uplink.dropped_samples == 0
    assert uplink.max_range_nm == 212.7
    assert uplink.gain_db == 43.9
    assert uplink.signal_db == -17.4
    assert uplink.noise_db == -31.6
    assert uplink.bytes_out_per_s is None


async def test_readsb_bytes_out_rate_is_differenced_between_polls() -> None:
    stats = load_json("readsb_stats.json")
    later = copy.deepcopy(stats)
    later["total"]["remote"]["bytes_out"] += 45_000
    documents = iter([stats, later])

    def serve_stats(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(documents))

    client = client_for(
        {"/data/status.json": load_json("readsb_status.json"), "/data/stats.json": serve_stats}
    )
    probe = ReadsbProbe("receiver", url="http://readsb.test:8080", client=client)

    await probe.probe(FIXTURE_NOW_MS)
    result = await probe.probe(FIXTURE_NOW_MS + 15_000)

    assert result.receiver is not None
    assert result.receiver.bytes_out_per_s == 3000.0
    assert result.metrics["bytes_out_per_s"] == 3000.0
    assert result.last_data_sent_ms == FIXTURE_NOW_MS + 15_000


async def test_readsb_counter_reset_yields_no_rate_rather_than_a_negative_one() -> None:
    stats = load_json("readsb_stats.json")
    reset = copy.deepcopy(stats)
    reset["total"]["remote"]["bytes_out"] = 10
    documents = iter([stats, reset])
    client = client_for(
        {
            "/data/status.json": load_json("readsb_status.json"),
            "/data/stats.json": lambda request: httpx.Response(200, json=next(documents)),
        }
    )
    probe = ReadsbProbe("receiver", url="http://readsb.test:8080/", client=client)

    await probe.probe(FIXTURE_NOW_MS)
    result = await probe.probe(FIXTURE_NOW_MS + 15_000)

    assert result.receiver is not None
    assert result.receiver.bytes_out_per_s is None


async def test_readsb_stale_status_is_down_and_silence_is_degraded() -> None:
    probe = ReadsbProbe("receiver", url="http://readsb.test:8080/", client=readsb_client())
    silent_stats = load_json("readsb_stats.json")
    silent_stats["last1min"]["messages"] = 0
    silent = ReadsbProbe(
        "receiver", url="http://readsb.test:8080/", client=readsb_client(silent_stats)
    )

    assert (await probe.probe(FIXTURE_NOW_MS + 120_000)).state is FeederState.DOWN
    assert (await silent.probe(FIXTURE_NOW_MS)).state is FeederState.DEGRADED


async def test_readsb_missing_stats_document_still_reports_the_status_half() -> None:
    client = client_for({"/data/status.json": load_json("readsb_status.json")})
    probe = ReadsbProbe("receiver", url="http://readsb.test:8080/", client=client)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert result.receiver is not None
    assert result.receiver.aircraft_with_pos == 37
    assert result.receiver.messages_per_min is None


async def test_readsb_never_carries_the_receiver_coordinates() -> None:
    probe = ReadsbProbe("receiver", url="http://readsb.test:8080/", client=readsb_client())

    result = await probe.probe(FIXTURE_NOW_MS)

    assert "51.12345678" not in repr(result)
    assert "1.98765432" not in repr(result)


# -------------------------------------------------------------- ultrafeeder

ADSBX = "feed.adsbexchange.com"
ADB = "feed.aerodatabox.com"


def mlat_doc(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = load_json("mlat_client_stats.json")
    document.update(changes)
    return document


def docker_with_logs(lines: list[str]) -> DockerClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/logs"):
            return httpx.Response(200, content=framed_log(lines))
        return httpx.Response(200, text="OK")

    return DockerClient("/var/run/docker.sock", transport=httpx.MockTransport(handle))


def ultrafeeder(
    host: str, documents: dict[str, Any], docker: DockerClient | None = None
) -> UltrafeederProbe:
    return UltrafeederProbe(
        host.split(".")[1],
        url="http://ultrafeeder.test:8080/",
        host=host,
        mlat_port=31090,
        beast_port=30004,
        container="ultrafeeder",
        client=client_for(documents),
        docker=docker,
    )


def test_mlat_stats_are_normalized() -> None:
    status, outliers, written_ms = parse_mlat_stats(mlat_doc())

    assert status.peers == 14
    assert status.good_sync_pct == 93.4
    assert status.bad_sync_timeout_s == 0
    assert status.last_bad_sync_ms is None  # -1 means never
    assert outliers == 0.8
    assert written_ms == FIXTURE_NOW_MS - 3200


def test_mlat_last_bad_sync_epoch_is_kept() -> None:
    status, _, _ = parse_mlat_stats(mlat_doc(last_bad_sync=FIXTURE_NOW_S - 60))

    assert status.last_bad_sync_ms == (FIXTURE_NOW_S - 60) * 1000


async def test_ultrafeeder_without_a_socket_is_judged_on_mlat_over_http() -> None:
    path = "/" + mlat_stats_path(ADSBX, 31090)
    probe = ultrafeeder(ADSBX, {path: mlat_doc()})

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert result.observability is Observability.HTTP
    assert result.adsb_out is None
    assert result.mlat is not None and result.mlat.peers == 14


async def test_zero_peers_is_tolerated_then_degraded_never_down() -> None:
    path = "/" + mlat_stats_path(ADB, 31090)
    probe = ultrafeeder(ADB, {path: mlat_doc(peer_count=0)})

    states = [(await probe.probe(FIXTURE_NOW_MS)).state for _ in range(ZERO_PEER_TOLERANCE + 1)]

    assert states[: ZERO_PEER_TOLERANCE - 1] == [FeederState.UP] * (ZERO_PEER_TOLERANCE - 1)
    assert states[ZERO_PEER_TOLERANCE - 1 :] == [FeederState.DEGRADED] * 2


async def test_a_single_peer_resets_the_zero_peer_tolerance() -> None:
    path = "/" + mlat_stats_path(ADB, 31090)
    counts = iter([0, 0, 1, 0, 0])
    probe = ultrafeeder(
        ADB,
        {path: lambda request: httpx.Response(200, json=mlat_doc(peer_count=next(counts)))},
    )

    states = [(await probe.probe(FIXTURE_NOW_MS)).state for _ in range(5)]

    assert states == [FeederState.UP] * 5


async def test_stale_or_missing_mlat_stats_without_a_socket_is_down() -> None:
    stale = ultrafeeder(ADSBX, {"/" + mlat_stats_path(ADSBX, 31090): mlat_doc()})
    missing = ultrafeeder(ADSBX, {})

    assert (await stale.probe(FIXTURE_NOW_MS + 120_000)).state is FeederState.DOWN
    result = await missing.probe(FIXTURE_NOW_MS)
    assert result.state is FeederState.DOWN
    assert result.failed


async def test_adsb_out_connected_from_the_latest_established_line() -> None:
    docker = docker_with_logs(load_lines("ultrafeeder.log"))
    probe = ultrafeeder(ADSBX, {"/" + mlat_stats_path(ADSBX, 31090): mlat_doc()}, docker)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert result.observability is Observability.DOCKER
    assert result.adsb_out is not None
    assert result.adsb_out.connected is True
    assert result.last_data_sent_ms == FIXTURE_NOW_MS


async def test_adsb_out_disconnected_is_down_even_with_healthy_mlat() -> None:
    docker = docker_with_logs(load_lines("ultrafeeder.log"))
    probe = ultrafeeder(ADB, {"/" + mlat_stats_path(ADB, 31090): mlat_doc()}, docker)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.DOWN
    assert result.adsb_out is not None
    assert result.adsb_out.connected is False
    assert result.message == "ADS-B output disconnected"


async def test_adsb_out_connected_with_mlat_unwell_is_degraded() -> None:
    docker = docker_with_logs(load_lines("ultrafeeder.log"))
    probe = ultrafeeder(ADSBX, {}, docker)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.DEGRADED
    assert result.adsb_out is not None and result.adsb_out.connected is True


async def test_unreachable_socket_falls_back_to_mlat_and_says_so() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no socket", request=request)

    docker = DockerClient("/nope.sock", transport=httpx.MockTransport(refuse))
    probe = ultrafeeder(ADSBX, {"/" + mlat_stats_path(ADSBX, 31090): mlat_doc()}, docker)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UP
    assert result.observability is Observability.HTTP
    assert result.adsb_out is None
    assert result.failed
    assert docker.reachable is False


# ------------------------------------------------------------------ opensky


def opensky_lines() -> list[LogLine]:
    return [split_timestamp(line) for line in load_lines("opensky.log")]


def test_opensky_reads_the_newest_statistics_block() -> None:
    block = last_statistics_block(opensky_lines())

    assert block is not None
    assert block.online is True
    assert block.seconds_online == 86_790
    assert block.availability_pct == 99.77
    assert block.disconnections == 4
    assert block.bytes_sent == 51_588_567
    assert block.bytes_per_s == 1230.0
    assert block.logged_ms == (FIXTURE_NOW_S - 20 * 60) * 1000


def test_opensky_online_is_up_offline_is_down_stale_is_unknown() -> None:
    block = last_statistics_block(opensky_lines())
    lines = opensky_lines()
    offline_lines = [
        LogLine(line.ts_ms, line.text.replace("currently online", "currently offline"))
        for line in lines
    ]
    offline = last_statistics_block(offline_lines)

    assert block_result(block, now_ms=FIXTURE_NOW_MS).state is FeederState.UP
    assert block_result(offline, now_ms=FIXTURE_NOW_MS).state is FeederState.DOWN
    assert block is not None and block.logged_ms is not None
    stale = block_result(block, now_ms=block.logged_ms + STALE_AFTER_MS + 1)
    assert stale.state is FeederState.UNKNOWN
    assert block_result(None, now_ms=FIXTURE_NOW_MS).state is FeederState.UNKNOWN


async def test_opensky_without_a_socket_is_unknown_and_unobservable_never_down() -> None:
    result = await OpenSkyLogsProbe("opensky", container="opensky", docker=None).probe(
        FIXTURE_NOW_MS
    )

    assert result.state is FeederState.UNKNOWN
    assert result.observability is Observability.NONE
    assert not result.failed


async def test_opensky_probe_reads_logs_through_the_socket() -> None:
    docker = docker_with_logs(load_lines("opensky.log"))
    result = await OpenSkyLogsProbe("opensky", container="opensky", docker=docker).probe(
        FIXTURE_NOW_MS
    )

    assert result.state is FeederState.UP
    assert result.observability is Observability.DOCKER
    assert result.metrics["availability_pct"] == 99.77
