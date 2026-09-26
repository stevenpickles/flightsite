"""The feeder repository: upserts, dangling episodes, range reads, retention."""

from __future__ import annotations

from sqlalchemy import text

from flightsite.db import Database
from flightsite.feeders.model import FeederEpisode, FeederSample, FeederState
from flightsite.feeders.repository import FeederRepository

from .conftest import FIXTURE_NOW_MS

T = FIXTURE_NOW_MS


async def test_an_episode_written_open_then_closed_is_one_row(database: Database) -> None:
    repository = FeederRepository(database)

    await repository.record([], [FeederEpisode("fr24", T, FeederState.DOWN)])
    await repository.record([], [FeederEpisode("fr24", T, FeederState.DOWN, T + 90_000)])

    episodes = await repository.episodes_between("fr24", 0, T + 1)
    assert episodes == [FeederEpisode("fr24", T, FeederState.DOWN, T + 90_000)]


async def test_samples_round_trip_their_numeric_metrics(database: Database) -> None:
    repository = FeederRepository(database)

    await repository.record(
        [
            FeederSample("adsbx", T, FeederState.UP, {"mlat_peers": 12, "good_sync_pct": 93.5}),
            FeederSample("adsbx", T + 60_000, FeederState.DEGRADED, {"mlat_peers": None}),
            FeederSample("other", T, FeederState.UP, {}),
        ],
        [],
    )

    samples = await repository.samples_between("adsbx", T, T + 60_001)
    assert [(s.ts_ms, s.state, dict(s.metrics)) for s in samples] == [
        (T, FeederState.UP, {"good_sync_pct": 93.5, "mlat_peers": 12}),
        (T + 60_000, FeederState.DEGRADED, {"mlat_peers": None}),
    ]


async def test_episode_reads_are_by_overlap_with_the_window(database: Database) -> None:
    repository = FeederRepository(database)
    await repository.record(
        [],
        [
            FeederEpisode("fr24", T - 5_000, FeederState.UP, T - 1_000),  # ends before
            FeederEpisode("fr24", T - 1_000, FeederState.DOWN, T + 1_000),  # straddles
            FeederEpisode("fr24", T + 1_000, FeederState.UP, None),  # open
            FeederEpisode("fr24", T + 9_000, FeederState.UP, None),  # starts after
        ],
    )

    episodes = await repository.episodes_between("fr24", T, T + 5_000)

    assert [e.started_ms for e in episodes] == [T - 1_000, T + 1_000]


async def test_dangling_episodes_close_at_their_last_sample(database: Database) -> None:
    repository = FeederRepository(database)
    await repository.record(
        [
            FeederSample("fr24", T + 30_000, FeederState.UP),
            FeederSample("fr24", T + 90_000, FeederState.UP),
        ],
        [FeederEpisode("fr24", T, FeederState.UP), FeederEpisode("opensky", T, FeederState.DOWN)],
    )

    assert await repository.close_dangling(T + 3_600_000) == 2

    fr24 = await repository.episodes_between("fr24", 0, T + 3_600_000)
    opensky = await repository.episodes_between("opensky", 0, T + 3_600_000)
    assert fr24[0].ended_ms == T + 90_000
    assert opensky[0].ended_ms == T  # never observed after it opened
    assert await repository.close_dangling(T + 3_600_000) == 0


async def test_an_unknown_stored_state_reads_back_as_unknown(database: Database) -> None:
    repository = FeederRepository(database)
    await repository.record([FeederSample("x", T, FeederState.UP, {"a": 1})], [])
    async with database.writer_session() as session:
        await session.execute(
            text("UPDATE feeder_samples SET state = 'sideways', metrics_json = 'not json'")
        )

    (sample,) = await repository.samples_between("x", 0, T + 1)

    assert sample.state is FeederState.UNKNOWN
    assert sample.metrics == {}


async def test_open_episodes_lists_only_unended_rows(database: Database) -> None:
    repository = FeederRepository(database)
    await repository.record(
        [],
        [
            FeederEpisode("a", T, FeederState.UP, T + 1),
            FeederEpisode("a", T + 1, FeederState.DOWN),
            FeederEpisode("b", T - 5, FeederState.UP),
        ],
    )

    assert await repository.open_episodes() == [
        FeederEpisode("b", T - 5, FeederState.UP),
        FeederEpisode("a", T + 1, FeederState.DOWN),
    ]


async def test_close_dangling_keeps_resumed_rows_and_closes_removed_feeders_at_now(
    database: Database,
) -> None:
    repository = FeederRepository(database)
    await repository.record(
        [FeederSample("kept", T + 30_000, FeederState.DOWN)],
        [
            FeederEpisode("kept", T, FeederState.DOWN),
            FeederEpisode("removed", T, FeederState.DOWN),
            FeederEpisode("stale", T, FeederState.UP),
        ],
    )
    now = T + 3_600_000

    closed = await repository.close_dangling(now, keep={("kept", T)}, removed={"removed"})

    assert closed == 2
    assert await repository.open_episodes() == [FeederEpisode("kept", T, FeederState.DOWN)]
    (removed,) = await repository.episodes_between("removed", 0, now + 1)
    (stale,) = await repository.episodes_between("stale", 0, now + 1)
    assert removed.ended_ms == now
    assert stale.ended_ms == T  # never sampled after it opened
