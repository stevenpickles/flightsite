"""The demo feeders: deterministic, every kind answered, the scripted behaviours."""

from __future__ import annotations

import json

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.demo.feeders import (
    DEMO_ENTRIES,
    FR24_CYCLE_S,
    FR24_OUTAGE_S,
    aerodatabox_peers,
    demo_docker_client,
    demo_feeder_settings,
    demo_probe,
    demo_probes,
    demo_result,
    fr24_outage,
)
from flightsite.feeders import FeederService
from flightsite.feeders.model import FeederKind, FeederState
from flightsite.feeders.service import FeederEntry

from .conftest import ManualClock

#: The start of an FR24 cycle, so outage arithmetic is exact.
CYCLE_START_MS = 1_790_001_600 * 1000


def test_every_kind_has_a_plausible_answer() -> None:
    for kind in FeederKind:
        entry = FeederEntry(name=f"demo-{kind.value}", label=kind.value, kind=kind.value)
        result = demo_result(entry, CYCLE_START_MS + 600_000)
        expected = FeederState.UNKNOWN if kind is FeederKind.LINK_ONLY else FeederState.UP
        assert result.state is expected, kind


def test_the_same_instant_gives_the_same_answer() -> None:
    for entry in DEMO_ENTRIES:
        assert demo_result(entry, CYCLE_START_MS + 123_456) == demo_result(
            entry, CYCLE_START_MS + 123_456
        )


def test_fr24_is_out_for_three_minutes_in_every_twenty() -> None:
    assert CYCLE_START_MS // 1000 % FR24_CYCLE_S == 0
    assert fr24_outage(CYCLE_START_MS)
    assert fr24_outage(CYCLE_START_MS + (FR24_OUTAGE_S - 1) * 1000)
    assert not fr24_outage(CYCLE_START_MS + FR24_OUTAGE_S * 1000)
    assert fr24_outage(CYCLE_START_MS + FR24_CYCLE_S * 1000)


def test_aerodatabox_peers_flap_between_zero_and_one() -> None:
    seen = {aerodatabox_peers(CYCLE_START_MS + second * 1000) for second in range(0, 120, 15)}

    assert seen == {0, 1}


def test_demo_probes_cover_every_entry() -> None:
    probes = demo_probes(DEMO_ENTRIES)

    assert set(probes) == {entry.name for entry in DEMO_ENTRIES}
    assert all(
        probe.kind == entry.kind for entry, probe in zip(DEMO_ENTRIES, probes.values(), strict=True)
    )


async def test_the_demo_drives_the_whole_service(
    database: Database, counters: CounterRegistry
) -> None:
    clock = ManualClock(CYCLE_START_MS + FR24_OUTAGE_S * 1000 + 60_000)
    service = FeederService(
        database=database,
        settings=demo_feeder_settings(),
        probe_factory=demo_probe,
        docker_factory=demo_docker_client,
        clock=clock,
        counters=counters,
    )
    await service.poll_once()

    report = service.report()
    assert report["docker_socket"] == "available"
    assert report["receiver"]["messages_per_min"] > 0
    assert len(report["local_pages"]) == 4
    assert {f["name"]: f["state"] for f in report["feeders"]} == {
        "receiver": "up",
        "flightaware": "up",
        "fr24": "up",
        "adsbx": "up",
        "aerodatabox": "up",
        "opensky": "up",
    }
    assert {f["name"]: f["stats_link"] for f in report["feeders"]}["flightaware"] is True
    assert "flightaware.com" not in json.dumps(report)

    # Into the next cycle's outage: down after the two-poll debounce, then back.
    clock.now_ms = CYCLE_START_MS + FR24_CYCLE_S * 1000
    first = {s.name: s.state for s in await service.poll_once()}
    clock.advance(15)
    second = {s.name: s.state for s in await service.poll_once()}
    clock.advance(FR24_OUTAGE_S)
    after = {s.name: s.state for s in await service.poll_once()}

    assert first["fr24"] is FeederState.UP
    assert second["fr24"] is FeederState.DOWN
    assert after["fr24"] is FeederState.UP
    history = await service.history("fr24", "24h")
    assert history is not None
    assert [e["state"] for e in history["episodes"]] == ["up", "down", "up"]
    await service.stop()
