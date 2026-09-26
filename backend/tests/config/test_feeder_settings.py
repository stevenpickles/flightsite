"""The ``feeders`` configuration section — slice 077's validation matrix.

Every rule here is a shape rule: nothing opens a connection. What matters is
that an invalid entry is rejected *per field* (the error's ``loc`` ends at the
field the Settings UI must mark) and that a valid fermi-shaped document loads.
"""

from __future__ import annotations

import typing
from typing import Any

import pytest
from pydantic import ValidationError

from flightsite.config import FeederSettings, Settings
from flightsite.config.models import FEEDER_KIND_REQUIRED_FIELDS, FeederKind

#: The design record's fermi example, with ``host.docker.internal`` URLs.
FERMI: dict[str, Any] = {
    "poll_interval_s": 15,
    "docker_socket": "/var/run/docker.sock",
    "entries": [
        {
            "name": "receiver",
            "label": "Receiver (readsb)",
            "kind": "readsb",
            "url": "http://host.docker.internal:8080/",
            "web_url": "http://fermi.local:8080/",
        },
        {
            "name": "flightaware",
            "label": "FlightAware",
            "kind": "piaware",
            "url": "http://host.docker.internal:8081/status.json",
            "web_url": "http://fermi.local:8081/",
        },
        {
            "name": "fr24",
            "label": "FlightRadar24",
            "kind": "fr24",
            "url": "http://host.docker.internal:8754/monitor.json",
            "web_url": "http://fermi.local:8754/",
        },
        {
            "name": "adsbx",
            "label": "ADS-B Exchange",
            "kind": "ultrafeeder",
            "url": "http://host.docker.internal:8080/",
            "host": "feed.adsbexchange.com",
            "mlat_port": 31090,
            "beast_port": 30004,
            "container": "ultrafeeder",
        },
        {
            "name": "aerodatabox",
            "label": "AeroDataBox",
            "kind": "ultrafeeder",
            "url": "http://host.docker.internal:8080/",
            "host": "feed.aerodatabox.com",
            "mlat_port": 31090,
            "beast_port": 30004,
            "container": "ultrafeeder",
        },
        {
            "name": "opensky",
            "label": "OpenSky Network",
            "kind": "opensky_logs",
            "container": "opensky",
        },
    ],
    "local_pages": [
        {"label": "tar1090", "url": "http://fermi.local:8080/"},
        {"label": "graphs1090", "url": "http://fermi.local:8080/graphs1090/"},
    ],
}


def _validate(**data: Any) -> FeederSettings:
    """Validate raw input, as ``config.yaml`` and the config API supply it."""
    return FeederSettings.model_validate(data)


def _locs(exc: pytest.ExceptionInfo[ValidationError]) -> list[tuple[Any, ...]]:
    return [tuple(error["loc"]) for error in exc.value.errors()]


def test_the_section_defaults_to_nothing_configured() -> None:
    feeders = Settings().feeders

    assert feeders.poll_interval_s == 15
    assert feeders.docker_socket is None
    assert feeders.entries == []
    assert feeders.local_pages == []
    assert feeders.stats_urls == {}


def test_the_fermi_document_loads() -> None:
    feeders = FeederSettings.model_validate(FERMI)

    assert [entry.name for entry in feeders.entries] == [
        "receiver",
        "flightaware",
        "fr24",
        "adsbx",
        "aerodatabox",
        "opensky",
    ]
    assert feeders.docker_socket == "/var/run/docker.sock"
    assert str(feeders.local_pages[1].url) == "http://fermi.local:8080/graphs1090/"


@pytest.mark.parametrize("interval", [4, 121, 0])
def test_poll_interval_is_bounded(interval: int) -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(poll_interval_s=interval)
    assert _locs(exc) == [("poll_interval_s",)]


@pytest.mark.parametrize("interval", [5, 120])
def test_poll_interval_bounds_are_inclusive(interval: int) -> None:
    assert _validate(poll_interval_s=interval).poll_interval_s == interval


@pytest.mark.parametrize("socket", ["var/run/docker.sock", "docker.sock", "unix:///x"])
def test_docker_socket_must_be_absolute(socket: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(docker_socket=socket)
    assert _locs(exc) == [("docker_socket",)]


def test_a_blank_docker_socket_means_unset() -> None:
    assert _validate(docker_socket="  ").docker_socket is None


@pytest.mark.parametrize(
    "name",
    ["", "FR24", "-fr24", "fr_24", "fr 24", "a" * 33, "fr24/../x"],
)
def test_entry_names_must_be_slugs(name: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[{"name": name, "label": "x", "kind": "link_only"}])
    assert _locs(exc) == [("entries", 0, "name")]


@pytest.mark.parametrize("name", ["a", "fr24", "0", "adsb-x", "a" * 32])
def test_valid_slugs_are_accepted(name: str) -> None:
    feeders = _validate(entries=[{"name": name, "label": "x", "kind": "link_only"}])
    assert feeders.entries[0].name == name


def test_entry_names_are_unique() -> None:
    entry = {"name": "fr24", "label": "x", "kind": "link_only"}
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[entry, dict(entry, label="y")])
    assert _locs(exc) == [("entries",)]
    assert "more than one entry" in exc.value.errors()[0]["msg"]


def test_an_unknown_kind_is_rejected_on_the_kind_field() -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[{"name": "x", "label": "x", "kind": "adsbhub"}])
    assert _locs(exc) == [("entries", 0, "kind")]


def test_an_unknown_entry_key_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[{"name": "x", "label": "x", "kind": "link_only", "fr24key": "abc"}])
    assert _locs(exc) == [("entries", 0, "fr24key")]


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        ("readsb", {"url"}),
        ("piaware", {"url"}),
        ("fr24", {"url"}),
        ("ultrafeeder", {"url", "host"}),
        ("opensky_logs", {"container"}),
        ("docker_health", {"container"}),
        ("link_only", set()),
    ],
)
def test_each_kind_reports_its_missing_fields_per_field(kind: str, missing: set[str]) -> None:
    entry = {"name": "x", "label": "X", "kind": kind}
    if not missing:
        _validate(entries=[entry])
        return
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[entry])
    assert {loc[-1] for loc in _locs(exc)} == missing
    assert all(loc[:2] == ("entries", 0) for loc in _locs(exc))


def test_the_required_field_table_covers_every_kind_but_link_only() -> None:
    kinds = set(typing.get_args(FeederKind))
    assert set(FEEDER_KIND_REQUIRED_FIELDS) == kinds - {"link_only"}


def test_a_blank_container_counts_as_missing() -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[{"name": "o", "label": "O", "kind": "opensky_logs", "container": "  "}])
    assert _locs(exc) == [("entries", 0, "container")]


@pytest.mark.parametrize("field", ["url", "web_url"])
@pytest.mark.parametrize("value", ["file:///etc/passwd", "not a url", "javascript:alert(1)"])
def test_urls_must_be_http(field: str, value: str) -> None:
    entry: dict[str, Any] = {"name": "r", "label": "R", "kind": "readsb", "url": "http://h/"}
    entry[field] = value
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[entry])
    assert _locs(exc) == [("entries", 0, field)]


@pytest.mark.parametrize("field", ["mlat_port", "beast_port"])
@pytest.mark.parametrize("port", [0, 65536])
def test_ports_are_bounded(field: str, port: int) -> None:
    entry: dict[str, Any] = {"name": "l", "label": "L", "kind": "link_only", field: port}
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[entry])
    assert _locs(exc) == [("entries", 0, field)]


def test_blank_labels_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(entries=[{"name": "l", "label": "   ", "kind": "link_only"}])
    assert _locs(exc) == [("entries", 0, "label")]


def test_local_pages_need_an_http_url_and_a_label() -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(local_pages=[{"label": "tar1090", "url": "ftp://fermi/"}])
    assert _locs(exc) == [("local_pages", 0, "url")]
    with pytest.raises(ValidationError) as exc:
        _validate(local_pages=[{"label": "", "url": "http://fermi/"}])
    assert _locs(exc) == [("local_pages", 0, "label")]


@pytest.mark.parametrize("key", ["FlightAware", "fa/../x", ""])
def test_stats_url_keys_must_be_entry_name_shaped(key: str) -> None:
    with pytest.raises(ValidationError):
        _validate(stats_urls={key: "https://flightaware.com/adsb/stats/user/x"})


@pytest.mark.parametrize("url", ["javascript:alert(1)", "flightaware.com/x", "ftp://x/y"])
def test_stats_urls_must_be_http_and_the_error_never_echoes_them(url: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _validate(stats_urls={"flightaware": url})
    rendered = str(exc.value.errors(include_input=False, include_url=False))
    assert url not in rendered
    assert "feeders.stats_urls.flightaware" in rendered


def test_a_null_stats_url_is_dropped() -> None:
    feeders = FeederSettings.model_validate(
        {"stats_urls": {"fr24": None, "flightaware": "https://flightaware.com/x"}}
    )
    assert set(feeders.stats_urls) == {"flightaware"}


@pytest.mark.parametrize("cleared", [None, "", "   "])
def test_a_null_or_blank_stats_url_is_dropped(cleared: str | None) -> None:
    feeders = _validate(stats_urls={"fr24": cleared, "flightaware": "https://flightaware.com/x"})
    assert set(feeders.stats_urls) == {"flightaware"}


def test_web_url_is_allowed_on_every_kind() -> None:
    needs = {
        "url": "http://host.docker.internal:8080/",
        "host": "feed.example.com",
        "container": "c",
    }
    for kind in typing.get_args(FeederKind):
        entry = {"name": "x", "label": "X", "kind": kind, "web_url": "http://fermi.local/"}
        entry.update({field: needs[field] for field in FEEDER_KIND_REQUIRED_FIELDS.get(kind, ())})
        assert str(_validate(entries=[entry]).entries[0].web_url) == "http://fermi.local/"


def test_an_unknown_field_is_reported_on_its_own_cell() -> None:
    entries = [
        {"name": "a", "label": "A", "kind": "link_only"},
        {"name": "b", "label": "B", "kind": "link_only"},
        {"name": "c", "label": "C", "kind": "link_only", "colour": "red"},
    ]
    with pytest.raises(ValidationError) as exc:
        _validate(entries=entries)
    assert _locs(exc) == [("entries", 2, "colour")]
    assert exc.value.errors()[0]["type"] == "extra_forbidden"
