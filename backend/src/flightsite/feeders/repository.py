"""Persistence for ``feeder_episodes`` and ``feeder_samples`` — the only SQL here.

``docs/DATA_MODEL.md`` §6.6. Two small tables nothing else touches, written
through :meth:`~flightsite.db.engine.Database.writer_session` like every other
writer in the process (ADR-0001, ADR-0008): one short transaction per flush,
one per maintenance prune, and one at start-up to close the episodes an
unclean stop left open. Nothing here is awaited by ingestion or by the live
store, and reads go through the read-only session.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Final

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flightsite.db import Database, FeederEpisodeRow, FeederSampleRow
from flightsite.feeders.model import FeederEpisode, FeederSample, FeederState, MetricValue

#: Rows per ``INSERT`` statement; well under SQLite's bound-parameter limit.
_BATCH: Final = 200


def _state(value: str) -> FeederState:
    try:
        return FeederState(value)
    except ValueError:
        return FeederState.UNKNOWN


def _metrics(payload: str | None) -> dict[str, MetricValue]:
    if not payload:
        return {}
    try:
        decoded = json.loads(payload)
    except ValueError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(key): value
        for key, value in decoded.items()
        if value is None or (isinstance(value, int | float) and not isinstance(value, bool))
    }


def _encode(metrics: Mapping[str, MetricValue]) -> str:
    return json.dumps(dict(metrics), separators=(",", ":"), sort_keys=True)


class FeederRepository:
    """Reads and writes the two feeder tables."""

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    async def record(
        self, samples: Iterable[FeederSample], episodes: Iterable[FeederEpisode]
    ) -> None:
        """Write samples and episode upserts in one transaction.

        Episodes are keyed on ``(feeder, started_ms)``, so writing an episode
        again — once as it opens, once as it closes — updates the one row.
        """
        sample_rows = [
            {
                "feeder": sample.feeder,
                "ts_ms": sample.ts_ms,
                "state": sample.state.value,
                "metrics_json": _encode(sample.metrics),
            }
            for sample in samples
        ]
        episode_rows = [
            {
                "feeder": episode.feeder,
                "started_ms": episode.started_ms,
                "ended_ms": episode.ended_ms,
                "state": episode.state.value,
            }
            for episode in episodes
        ]
        if not sample_rows and not episode_rows:
            return
        async with self._database.writer_session() as session:
            for start in range(0, len(sample_rows), _BATCH):
                statement = sqlite_insert(FeederSampleRow).values(
                    sample_rows[start : start + _BATCH]
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["feeder", "ts_ms"],
                        set_={
                            "state": statement.excluded.state,
                            "metrics_json": statement.excluded.metrics_json,
                        },
                    )
                )
            for start in range(0, len(episode_rows), _BATCH):
                statement = sqlite_insert(FeederEpisodeRow).values(
                    episode_rows[start : start + _BATCH]
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["feeder", "started_ms"],
                        set_={
                            "ended_ms": statement.excluded.ended_ms,
                            "state": statement.excluded.state,
                        },
                    )
                )

    async def close_dangling(self, now_ms: int) -> int:
        """Close every episode a previous process left open. Returns how many.

        Each is closed at the last instant the previous process is known to
        have observed that feeder — its newest sample, never earlier than the
        episode's own start — rather than at ``now``: the time between is time
        nobody was watching, and claiming it as the old state would put a
        fabricated stretch of "up" (or "down") on the timeline.
        """
        async with self._database.writer_session() as session:
            open_rows = (
                await session.execute(
                    select(FeederEpisodeRow.feeder, FeederEpisodeRow.started_ms).where(
                        FeederEpisodeRow.ended_ms.is_(None)
                    )
                )
            ).all()
            for feeder, started_ms in open_rows:
                last_seen = (
                    await session.execute(
                        select(func.max(FeederSampleRow.ts_ms)).where(
                            FeederSampleRow.feeder == feeder,
                            FeederSampleRow.ts_ms >= started_ms,
                        )
                    )
                ).scalar_one_or_none()
                ended = min(now_ms, max(int(started_ms), int(last_seen or started_ms)))
                await session.execute(
                    update(FeederEpisodeRow)
                    .where(
                        FeederEpisodeRow.feeder == feeder,
                        FeederEpisodeRow.started_ms == started_ms,
                    )
                    .values(ended_ms=ended)
                )
        return len(open_rows)

    async def episodes_between(self, feeder: str, from_ms: int, to_ms: int) -> list[FeederEpisode]:
        """Episodes of ``feeder`` overlapping ``[from_ms, to_ms)``, oldest first."""
        async with self._database.read_session() as session:
            rows = (
                await session.execute(
                    select(
                        FeederEpisodeRow.started_ms,
                        FeederEpisodeRow.ended_ms,
                        FeederEpisodeRow.state,
                    )
                    .where(
                        FeederEpisodeRow.feeder == feeder,
                        FeederEpisodeRow.started_ms < to_ms,
                        or_(
                            FeederEpisodeRow.ended_ms.is_(None),
                            FeederEpisodeRow.ended_ms > from_ms,
                        ),
                    )
                    .order_by(FeederEpisodeRow.started_ms)
                )
            ).all()
        return [
            FeederEpisode(
                feeder=feeder,
                started_ms=int(started),
                ended_ms=None if ended is None else int(ended),
                state=_state(state),
            )
            for started, ended, state in rows
        ]

    async def samples_between(self, feeder: str, from_ms: int, to_ms: int) -> list[FeederSample]:
        """Samples of ``feeder`` in ``[from_ms, to_ms)``, oldest first."""
        async with self._database.read_session() as session:
            rows = (
                await session.execute(
                    select(
                        FeederSampleRow.ts_ms, FeederSampleRow.state, FeederSampleRow.metrics_json
                    )
                    .where(
                        and_(
                            FeederSampleRow.feeder == feeder,
                            FeederSampleRow.ts_ms >= from_ms,
                            FeederSampleRow.ts_ms < to_ms,
                        )
                    )
                    .order_by(FeederSampleRow.ts_ms)
                )
            ).all()
        return [
            FeederSample(feeder=feeder, ts_ms=int(ts), state=_state(state), metrics=_metrics(blob))
            for ts, state, blob in rows
        ]

    async def prune(self, *, samples_before_ms: int, episodes_before_ms: int) -> tuple[int, int]:
        """Delete expired samples and closed episodes. Returns (samples, episodes).

        An open episode is never pruned however old its start: it is the
        feeder's current state.
        """
        async with self._database.writer_session() as session:
            samples = await session.execute(
                delete(FeederSampleRow).where(FeederSampleRow.ts_ms < samples_before_ms)
            )
            episodes = await session.execute(
                delete(FeederEpisodeRow).where(
                    FeederEpisodeRow.ended_ms.is_not(None),
                    FeederEpisodeRow.ended_ms < episodes_before_ms,
                )
            )
        return _rowcount(samples), _rowcount(episodes)


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return value if isinstance(value, int) and value > 0 else 0


__all__ = ["FeederRepository"]
