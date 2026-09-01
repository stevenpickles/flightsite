"""Shared fixtures for the storage-qualification suite.

The dataset here is deliberately tiny — a fortnight of a fraction of Scenario
A's traffic. That is enough to exercise every code path and every cross-table
invariant, and it keeps the default suite fast; the *large* datasets live
behind the ``load`` marker in :mod:`tests.perf.storage.test_qualification` and
in the ``flightsite-storage-qual`` command.

The fixture is module-scoped for the same reason
``tests/perf/test_harness.py``'s is: generating history costs seconds, reading
it back costs nothing, and a per-test dataset would build a dozen databases for
no additional signal. Module scope means the autouse function-scoped
``isolated_data_dir`` has not run yet, so the data directory comes explicitly
from ``tmp_path_factory`` and is handed to :class:`Database` directly — an
implicit resolution here would put a multi-megabyte database wherever the
ambient environment happened to point, up to and including the working tree.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flightsite.db import Database
from flightsite.perf.storage_qualification.generator import (
    GenerationConfig,
    GenerationResult,
    generate_history,
)
from flightsite.perf.storage_qualification.scenarios import Scenario

#: A fortnight, which is the shortest span that still spans the 14-day
#: high-resolution retention window and therefore still has a prune to make.
SMOKE_DAYS = 14

#: Traffic small enough to generate in a couple of seconds and still produce a
#: genuinely skewed airframe population, several thousand tracks, and every
#: table the growth model names. Shaped like Scenario A, at a fortieth of it.
SMOKE_SCENARIO = Scenario(
    name="smoke",
    label="in-suite smoke scenario (a fortieth of docs/DATA_MODEL.md sec.9 Scenario A)",
    sightings_per_day=40,
    unique_aircraft_per_day=24,
    new_aircraft_per_year=4_000,
    events_per_sighting=3.0,
    activity_events_per_day=6,
    alert_matches_per_day=3,
    predicted_gb_per_year=(1.0, 1.2),
)

#: Fixed so the generated history is identical on every run, which is what lets
#: a test assert an exact row count rather than a range.
SMOKE_END = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Dataset:
    """A generated database and the report describing it."""

    path: Path
    data_dir: Path
    result: GenerationResult


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Dataset]:
    """One small synthetic history, shared by the whole module."""
    data_dir: Path = tmp_path_factory.mktemp("storage-qual")

    async def build() -> Dataset:
        database = Database(data_dir / "flightsite.sqlite3")
        await database.upgrade_to("head")
        result = await generate_history(
            database,
            GenerationConfig(
                scenario=SMOKE_SCENARIO,
                days=SMOKE_DAYS,
                end=SMOKE_END,
                high_res_backlog_days=2,
            ),
        )
        await database.dispose()
        return Dataset(path=data_dir / "flightsite.sqlite3", data_dir=data_dir, result=result)

    yield asyncio.run(build())


@pytest.fixture
async def database(dataset: Dataset) -> AsyncIterator[Database]:
    """A :class:`Database` over the shared dataset, disposed after each test.

    The dataset file is module-scoped and read-only as far as these tests are
    concerned; the engines over it are per-test so no pooled connection outlives
    the test that opened it.
    """
    instance = Database(dataset.path)
    try:
        yield instance
    finally:
        await instance.dispose()
