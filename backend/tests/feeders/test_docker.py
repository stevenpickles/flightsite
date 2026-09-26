"""The Docker Engine API client: stream demux, requests, and never raising."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from flightsite.feeders.docker import (
    API_VERSION,
    DockerClient,
    DockerHealthProbe,
    LogDemuxer,
    demux,
    parse_docker_time,
    split_timestamp,
)
from flightsite.feeders.model import FeederState, Observability

from .conftest import FIXTURE_NOW_MS, frame, framed_log


def test_demux_reads_a_canned_multiplexed_stream() -> None:
    body = frame(b"first line\nsecond ") + frame(b"stderr says hi\n", 2) + frame(b"line\n")

    assert demux(body) == ["first line", "stderr says hi", "second line"]


def test_demux_handles_frames_split_at_every_byte() -> None:
    body = framed_log(["alpha", "beta"]) + frame(b"gamma\n", 2)
    demuxer = LogDemuxer()

    lines: list[str] = []
    for index in range(len(body)):
        lines.extend(demuxer.feed(body[index : index + 1]))
    lines.extend(demuxer.close())

    assert lines == ["alpha", "beta", "gamma"]


def test_demux_passes_a_tty_stream_through_raw() -> None:
    assert demux(b"plain tty output\r\nno frames here\nlast") == [
        "plain tty output",
        "no frames here",
        "last",
    ]


def test_demux_of_a_tiny_raw_stream_still_yields_it() -> None:
    assert demux(b"hi") == ["hi"]


def test_docker_timestamps_parse_to_utc_milliseconds() -> None:
    assert parse_docker_time("2026-09-21T14:13:20.123456789Z") == FIXTURE_NOW_MS + 123
    assert parse_docker_time("0001-01-01T00:00:00Z") is None
    assert parse_docker_time("garbage") is None
    line = split_timestamp("2026-09-21T14:13:20.000000000Z hello world")
    assert line.ts_ms == FIXTURE_NOW_MS
    assert line.text == "hello world"
    assert split_timestamp("no stamp here").ts_ms is None


class Recorder:
    """A mock Docker daemon that records what it was asked."""

    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for suffix, response in self.responses.items():
            if request.url.path.endswith(suffix):
                return response
        return httpx.Response(404, json={"message": "No such container"})


def client(recorder: Recorder) -> DockerClient:
    return DockerClient("/var/run/docker.sock", transport=httpx.MockTransport(recorder))


async def test_logs_are_requested_read_only_with_timestamps_and_filtered() -> None:
    lines = [f"2026-09-21T14:0{index}:00.000000000Z line {index}" for index in range(6)]
    recorder = Recorder({"/logs": httpx.Response(200, content=framed_log(lines))})
    docker = client(recorder)

    kept = await docker.logs("opensky", since_s=100, tail=2, match=lambda text: text != "line 5")

    assert kept is not None
    assert [line.text for line in kept] == ["line 3", "line 4"]
    request = recorder.requests[0]
    assert request.method == "GET"
    assert request.url.path == f"/{API_VERSION}/containers/opensky/logs"
    assert request.url.params["stdout"] == "1"
    assert request.url.params["stderr"] == "1"
    assert request.url.params["timestamps"] == "1"
    assert request.url.params["since"] == "100"
    assert request.url.params["tail"] == "2"
    assert docker.reachable is True


async def test_container_health_is_read_from_the_inspect_document() -> None:
    inspect: dict[str, Any] = {
        "State": {
            "Status": "running",
            "Running": True,
            "StartedAt": "2026-09-21T14:13:20.000000000Z",
            "Health": {"Status": "healthy"},
        }
    }
    docker = client(Recorder({"/opensky/json": httpx.Response(200, json=inspect)}))

    state = await docker.container("opensky")
    missing = await docker.container("nope")

    assert state is not None
    assert state.found and state.running
    assert state.health == "healthy"
    assert state.started_ms == FIXTURE_NOW_MS
    assert missing is not None and not missing.found


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("no such file"), httpx.ReadTimeout("slow"), PermissionError("denied")],
)
async def test_every_call_answers_none_or_false_instead_of_raising(failure: Exception) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure

    docker = DockerClient("/var/run/docker.sock", transport=httpx.MockTransport(fail))

    assert await docker.ping() is False
    assert await docker.container("x") is None
    assert await docker.logs("x") is None
    assert docker.reachable is False
    await docker.aclose()


async def test_an_error_status_on_logs_is_none_but_the_daemon_is_reachable() -> None:
    docker = client(Recorder({"/logs": httpx.Response(500)}))

    assert await docker.logs("x") is None
    assert docker.reachable is True


async def test_ping() -> None:
    docker = client(Recorder({"/_ping": httpx.Response(200, text="OK")}))

    assert await docker.ping() is True
    assert docker.reachable is True


def inspect_response(**state: Any) -> httpx.Response:
    return httpx.Response(200, json={"State": state})


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (inspect_response(Status="running", Running=True), FeederState.UP),
        (
            inspect_response(Status="running", Running=True, Health={"Status": "unhealthy"}),
            FeederState.DEGRADED,
        ),
        (inspect_response(Status="exited", Running=False), FeederState.DOWN),
        (httpx.Response(404), FeederState.DOWN),
    ],
)
async def test_docker_health_probe_states(response: httpx.Response, expected: FeederState) -> None:
    docker = client(Recorder({"/feeder/json": response}))
    probe = DockerHealthProbe("feeder", container="feeder", docker=docker)

    result = await probe.probe(FIXTURE_NOW_MS)

    assert result.state is expected
    assert result.observability is Observability.DOCKER


async def test_docker_health_without_a_socket_is_unknown_never_down() -> None:
    result = await DockerHealthProbe("feeder", container=None, docker=None).probe(FIXTURE_NOW_MS)

    assert result.state is FeederState.UNKNOWN
    assert result.observability is Observability.NONE
