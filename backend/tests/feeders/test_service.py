"""The feeder service: debounce, episodes, flushing, hot apply, report, history.

Driven one :meth:`~flightsite.feeders.service.FeederService.poll_once` at a
time against a hand-driven clock and scripted probes, so every transition in
a test is one the test asked for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.feeders import FeederService
from flightsite.feeders.docker import DockerClient
from flightsite.feeders.model import (
    FeederEpisode,
    FeederState,
    MlatStatus,
    Observability,
    ProbeResult,
    ReceiverUplink,
)
from flightsite.feeders.protocol import FeederEntryLike, FeederProbe, ProbeContext
from flightsite.feeders.repository import FeederRepository
from flightsite.feeders.service import availability_pct

from .conftest import (
    FIXTURE_NOW_MS,
    SECRET_STATS_URL,
    Entry,
    ManualClock,
    Page,
    Settings,
    Transitions,
)

UP = ProbeResult(state=FeederState.UP, observability=Observability.HTTP, metrics={"peers": 3})
DOWN = ProbeResult(
    state=FeederState.DOWN, observability=Observability.HTTP, message="gone", failed=True
)
DEGRADED = ProbeResult(state=FeederState.DEGRADED, observability=Observability.HTTP)


@dataclass
class ScriptedProbe:
    """Answers with the next scripted result, repeating the last one."""

    name: str
    kind: str
    script: list[ProbeResult] = field(default_factory=lambda: [UP])
    stats_fallback: str | None = None
    calls: int = 0

    async def probe(self, now_ms: int) -> ProbeResult:
        self.calls += 1
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


class Factory:
    """A probe factory that remembers what it built, per name."""

    def __init__(self, scripts: dict[str, list[ProbeResult]] | None = None) -> None:
        self.scripts = scripts or {}
        self.built: dict[str, ScriptedProbe] = {}
        self.contexts: list[ProbeContext] = []

    def __call__(self, entry: FeederEntryLike, context: ProbeContext) -> FeederProbe:
        self.contexts.append(context)
        probe = ScriptedProbe(entry.name, str(entry.kind), list(self.scripts.get(entry.name, [UP])))
        self.built[entry.name] = probe
        return probe


def settings(*names: str, **overrides: object) -> Settings:
    entries = tuple(Entry(name=name, label=name.title(), kind="fr24") for name in names)
    values: dict[str, object] = {"entries": entries}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def make(
    database: Database,
    clock: ManualClock,
    counters: CounterRegistry,
    config: Settings | None,
    factory: Factory,
    transitions: Transitions | None = None,
    docker_factory: Callable[[str], DockerClient] = DockerClient,
) -> FeederService:
    return FeederService(
        database=database,
        settings=config,
        on_transition=transitions,
        probe_factory=factory,
        docker_factory=docker_factory,
        clock=clock,
        counters=counters,
    )


async def test_first_poll_opens_an_episode_in_the_observed_state(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    transitions = Transitions()
    service = make(database, clock, counters, settings("fr24"), Factory(), transitions)

    statuses = await service.poll_once()

    assert statuses[0].state is FeederState.UP
    assert statuses[0].since_ms == FIXTURE_NOW_MS
    assert transitions.episodes == [
        FeederEpisode(feeder="fr24", started_ms=FIXTURE_NOW_MS, state=FeederState.UP)
    ]
    await service.stop()


async def test_down_is_committed_only_after_two_consecutive_polls(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    transitions = Transitions()
    factory = Factory({"fr24": [UP, DOWN, UP, DOWN, DOWN, DOWN]})
    service = make(database, clock, counters, settings("fr24"), factory, transitions)

    states = []
    for _ in range(6):
        states.append((await service.poll_once())[0].state)
        clock.advance(15)

    assert states == [
        FeederState.UP,
        FeederState.UP,  # one down reading is held back
        FeederState.UP,
        FeederState.UP,
        FeederState.DOWN,  # the second consecutive one commits
        FeederState.DOWN,
    ]
    down_opened = [e for e in transitions.episodes if e.state is FeederState.DOWN]
    assert len(down_opened) == 1 and down_opened[0].open
    assert counters.snapshot()["feeder_poll_failures"] == 4
    await service.stop()


async def test_restoration_closes_the_down_episode_then_opens_up(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    transitions = Transitions()
    factory = Factory({"fr24": [UP, DOWN, DOWN, UP]})
    service = make(database, clock, counters, settings("fr24"), factory, transitions)
    for _ in range(4):
        await service.poll_once()
        clock.advance(15)

    kinds = [(e.state, e.open) for e in transitions.episodes]
    assert kinds == [
        (FeederState.UP, True),
        (FeederState.UP, False),
        (FeederState.DOWN, True),
        (FeederState.DOWN, False),
        (FeederState.UP, True),
    ]
    closed_down = transitions.episodes[3]
    assert closed_down.ended_ms == FIXTURE_NOW_MS + 45_000
    await service.stop()


async def test_degraded_and_unknown_commit_immediately(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    unknown = ProbeResult(state=FeederState.UNKNOWN, observability=Observability.NONE)
    service = make(
        database, clock, counters, settings("fr24"), Factory({"fr24": [UP, DEGRADED, unknown]})
    )

    states = [(await service.poll_once())[0].state for _ in range(3)]

    assert states == [FeederState.UP, FeederState.DEGRADED, FeederState.UNKNOWN]
    await service.stop()


async def test_a_raising_listener_or_probe_never_stops_polling(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    def explode(episode: FeederEpisode) -> None:
        raise RuntimeError("listener bug")

    class Broken:
        name = "fr24"
        kind = "fr24"

        async def probe(self, now_ms: int) -> ProbeResult:
            raise RuntimeError("probe bug")

    service = FeederService(
        database=database,
        settings=settings("fr24"),
        on_transition=explode,
        probe_factory=lambda entry, context: Broken(),
        clock=clock,
        counters=counters,
    )

    statuses = await service.poll_once()

    assert statuses[0].state is FeederState.UNKNOWN
    assert counters.snapshot()["feeder_poll_failures"] == 1
    await service.stop()


async def test_an_undeclared_counter_never_stops_polling(
    database: Database, clock: ManualClock
) -> None:
    service = make(
        database,
        clock,
        CounterRegistry(("db_errors",)),
        settings("fr24"),
        Factory({"fr24": [DOWN]}),
    )

    await service.poll_once()
    await service.stop()


async def test_transitions_are_written_at_once_and_samples_on_the_flush_interval(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = make(database, clock, counters, settings("fr24"), Factory())
    repository = FeederRepository(database)

    await service.poll_once()  # opens an episode: flushed immediately
    episodes = await repository.episodes_between("fr24", 0, FIXTURE_NOW_MS + 1)
    assert [(e.state, e.ended_ms) for e in episodes] == [(FeederState.UP, None)]

    for _ in range(4):  # one sample per minute, flushed once a minute
        clock.advance(15)
        await service.poll_once()
    samples = await repository.samples_between("fr24", 0, clock.now_ms + 1)
    assert [s.ts_ms for s in samples] == [FIXTURE_NOW_MS, FIXTURE_NOW_MS + 60_000]
    assert samples[0].metrics == {"peers": 3}
    await service.stop()


async def test_stop_closes_open_episodes_silently_and_start_closes_dangling_ones(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    transitions = Transitions()
    service = make(database, clock, counters, settings("fr24"), Factory(), transitions)
    await service.poll_once()
    clock.advance(30)
    await service.stop()

    episodes = await FeederRepository(database).episodes_between("fr24", 0, clock.now_ms + 1)
    assert episodes[0].ended_ms == FIXTURE_NOW_MS + 30_000
    assert len(transitions.episodes) == 1  # stopping is not a transition

    # An unclean stop: an episode left open, samples after it.
    repository = FeederRepository(database)
    dangling = FeederEpisode(feeder="fr24", started_ms=clock.now_ms, state=FeederState.DOWN)
    await repository.record([], [dangling])
    restarted = make(database, clock, counters, settings("fr24"), Factory())
    clock.advance(600)
    await restarted.start()
    await restarted.stop()

    stored = await repository.episodes_between("fr24", 0, clock.now_ms + 1)
    down = next(e for e in stored if e.state is FeederState.DOWN)
    assert down.ended_ms == dangling.started_ms  # no sample after it: closed at its start


async def test_start_with_no_entries_starts_no_task_and_apply_starts_one(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    gate = asyncio.Event()

    async def sleep(seconds: float) -> None:
        await gate.wait()

    service = FeederService(
        database=database,
        settings=None,
        probe_factory=Factory(),
        clock=clock,
        sleep=sleep,
        counters=counters,
    )
    await service.start()
    assert not service.running
    assert service.docker_client is None

    await service.apply_settings(settings("fr24"))
    assert service.running

    await service.apply_settings(settings())
    assert not service.running
    await service.stop()


async def test_no_socket_means_no_docker_client_and_a_socket_means_one(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    built: list[str] = []

    def docker_factory(path: str) -> DockerClient:
        built.append(path)
        return DockerClient(path)

    factory = Factory()
    service = make(
        database, clock, counters, settings("fr24"), factory, docker_factory=docker_factory
    )
    assert service.docker_client is None
    assert service.docker_socket_status == "unset"
    assert factory.contexts[-1].docker is None

    await service.apply_settings(settings("fr24", docker_socket="/var/run/docker.sock"))

    assert built == ["/var/run/docker.sock"]
    assert service.docker_client is not None
    assert factory.contexts[-1].docker is service.docker_client
    await service.stop()


async def test_hot_apply_keeps_state_for_surviving_names_and_rebuilds_changed_probes(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    factory = Factory({"a": [DEGRADED]})
    service = make(database, clock, counters, settings("a", "b"), factory)
    await service.poll_once()
    probe_a, probe_b = factory.built["a"], factory.built["b"]

    changed = Settings(
        entries=(
            Entry(name="a", label="A", kind="fr24"),
            Entry(name="b", label="Renamed B", kind="fr24", url="http://b.test/monitor.json"),
            Entry(name="c", label="C", kind="fr24"),
        ),
        poll_interval_s=30,
    )
    await service.apply_settings(changed)

    assert service.names == ("a", "b", "c")
    assert service.poll_interval_s == 30
    assert factory.built["a"] is probe_a  # unchanged entry keeps its probe
    assert factory.built["b"] is not probe_b  # changed entry gets a new one
    status_a = service.status("a")
    assert status_a is not None
    assert status_a.state is FeederState.DEGRADED  # and no state was lost
    assert status_a.since_ms == FIXTURE_NOW_MS
    status_b = service.status("b")
    assert status_b is not None and status_b.label == "Renamed B"

    await service.apply_settings(settings("c"))
    episodes = await FeederRepository(database).episodes_between("a", 0, clock.now_ms + 1)
    assert episodes[0].ended_ms == clock.now_ms  # removed feeder's episode closed
    await service.stop()


async def test_report_shape_and_stats_link_is_a_boolean(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    mlat_result = ProbeResult(
        state=FeederState.UP,
        observability=Observability.HTTP,
        mlat=MlatStatus(peers=4, good_sync_pct=91.0, last_bad_sync_ms=FIXTURE_NOW_MS),
        receiver=ReceiverUplink(messages_per_min=900, updated_ms=FIXTURE_NOW_MS),
        detail={"host": "feed.example"},
        last_data_sent_ms=FIXTURE_NOW_MS - 1000,
    )
    config = Settings(
        entries=(
            Entry(name="adsbx", label="ADS-B Exchange", kind="ultrafeeder", web_url="http://w/"),
            Entry(name="opensky", label="OpenSky", kind="opensky_logs"),
        ),
        local_pages=(Page(label="tar1090", url="http://fermi.local:8080/"),),
        stats_urls={"adsbx": SecretStr(SECRET_STATS_URL), "opensky": SecretStr("  ")},
    )
    service = make(database, clock, counters, config, Factory({"adsbx": [mlat_result]}))
    await service.poll_once()

    report = service.report()

    assert report["generated_at"] == "2026-09-21T14:13:20.000Z"
    assert report["poll_interval_s"] == 15.0
    assert report["docker_socket"] == "unset"
    assert report["receiver"]["messages_per_min"] == 900
    assert report["local_pages"] == [{"label": "tar1090", "url": "http://fermi.local:8080/"}]
    adsbx, opensky = report["feeders"]
    assert adsbx["stats_link"] is True
    assert opensky["stats_link"] is False  # a blank secret is no link
    assert adsbx["mlat"] == {
        "peers": 4,
        "good_sync_pct": 91.0,
        "bad_sync_timeout_s": None,
        "last_bad_sync_at": "2026-09-21T14:13:20.000Z",
    }
    assert adsbx["adsb_out"] is None
    assert adsbx["web_url"] == "http://w/"
    assert adsbx["last_data_sent_at"] == "2026-09-21T14:13:19.000Z"
    assert SECRET_STATS_URL not in repr(report)
    assert service.stats_url("adsbx") == SECRET_STATS_URL
    assert service.stats_url("opensky") is None
    assert service.stats_url("unknown") is None
    await service.stop()


async def test_a_probe_fallback_is_used_only_when_nothing_is_configured(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    class Fallback(Factory):
        def __call__(self, entry: FeederEntryLike, context: ProbeContext) -> FeederProbe:
            probe = super().__call__(entry, context)
            assert isinstance(probe, ScriptedProbe)
            probe.stats_fallback = "https://fallback.example/"
            return probe

    service = make(database, clock, counters, settings("flightaware"), Fallback())

    assert service.stats_url("flightaware") == "https://fallback.example/"
    await service.apply_settings(
        settings("flightaware", stats_urls={"flightaware": SecretStr(SECRET_STATS_URL)})
    )
    assert service.stats_url("flightaware") == SECRET_STATS_URL
    await service.stop()


async def test_summary_counts_states(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = make(database, clock, counters, settings("a", "b", "c"), Factory({"b": [DEGRADED]}))
    await service.poll_once()

    assert service.summary() == {
        "configured": 3,
        "up": 2,
        "degraded": 1,
        "down": 0,
        "unknown": 0,
        "docker_socket": "unset",
    }
    await service.stop()


async def test_history_merges_stored_and_pending_rows(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    factory = Factory({"fr24": [UP, DOWN, DOWN, DOWN, UP]})
    service = make(database, clock, counters, settings("fr24"), factory)
    for _ in range(5):
        await service.poll_once()
        clock.advance(60)

    history = await service.history("fr24", "24h")

    assert history is not None
    assert [e["state"] for e in history["episodes"]] == ["up", "down", "up"]
    assert history["episodes"][-1]["ended_at"] is None
    assert len(history["samples"]) == 5
    # 2 min up then 2 min down (committed on the third poll) then 1 min up.
    assert history["availability_pct"] == 60.0
    assert await service.history("nope", "24h") is None
    with pytest.raises(ValueError):
        await service.history("fr24", "1y")
    await service.stop()


def test_availability_ignores_unknown_and_uncovered_time() -> None:
    episodes = [
        FeederEpisode("x", 0, FeederState.UP, 100),
        FeederEpisode("x", 100, FeederState.UNKNOWN, 300),
        FeederEpisode("x", 300, FeederState.DOWN, 400),
        FeederEpisode("x", 900, FeederState.DEGRADED, None),
    ]

    assert availability_pct(episodes, from_ms=50, to_ms=1000) == 60.0
    assert availability_pct([], from_ms=0, to_ms=10) is None


async def test_maintenance_prunes_old_samples_and_closed_episodes(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    repository = FeederRepository(database)
    day = 24 * 3600 * 1000
    from flightsite.feeders.model import FeederSample

    await repository.record(
        [
            FeederSample("fr24", FIXTURE_NOW_MS - 15 * day, FeederState.UP, {}),
            FeederSample("fr24", FIXTURE_NOW_MS - 13 * day, FeederState.UP, {}),
        ],
        [
            FeederEpisode(
                "fr24", FIXTURE_NOW_MS - 100 * day, FeederState.UP, FIXTURE_NOW_MS - 95 * day
            ),
            FeederEpisode(
                "fr24", FIXTURE_NOW_MS - 95 * day, FeederState.DOWN, FIXTURE_NOW_MS - 80 * day
            ),
            FeederEpisode("old", FIXTURE_NOW_MS - 200 * day, FeederState.UNKNOWN, None),
        ],
    )
    service = make(database, clock, counters, settings("fr24"), Factory())

    assert await service.run_maintenance() == (1, 1)
    assert len(await repository.samples_between("fr24", 0, FIXTURE_NOW_MS)) == 1
    remaining = await repository.episodes_between("fr24", 0, FIXTURE_NOW_MS)
    assert [e.state for e in remaining] == [FeederState.DOWN]
    # An open episode is the feeder's current state and is never pruned.
    assert len(await repository.episodes_between("old", 0, FIXTURE_NOW_MS)) == 1
    await service.stop()


async def test_a_failed_flush_keeps_the_batch_for_the_next_one(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = make(database, clock, counters, settings("fr24"), Factory())
    repository = FeederRepository(database)

    class Refusing(FeederRepository):
        async def record(self, *args: object, **kwargs: object) -> None:
            raise OSError("disk full")

    service._repository = Refusing(database)
    await service.poll_once()

    assert service.pending_samples == 1
    assert counters.snapshot()["db_errors"] == 1

    service._repository = repository
    assert await service.flush()
    assert service.pending_samples == 0
    assert len(await repository.episodes_between("fr24", 0, clock.now_ms + 1)) == 1
