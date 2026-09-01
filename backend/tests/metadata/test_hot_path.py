"""The hot path performs zero database reads (``docs/ARCHITECTURE.md`` §3.1).

Slice 021's third acceptance criterion, and the reason the cache is a consumer
of the live event stream rather than something ``LiveStore.apply`` calls.

Two tests, deliberately different in kind:

* a **spy** on :meth:`Database.read_session` and
  :meth:`Database.writer_session`, counting sessions opened across a full batch
  application with the cache running — the behavioural check;
* a **structural** check that nothing in ``flightsite.live`` imports the
  database at all — the check that stays true when someone adds a new call site
  the spy's batch happens not to reach.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.cache import MetadataCache
from tests.metadata.conftest import batch, record, settle, updates
from tests.metadata.provider import InMemoryMetadataProvider

BATCH_SIZE = 500


class SessionSpy:
    """Counts every session the application opens while it is installed."""

    def __init__(self, database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reads = 0
        self.writes = 0
        original_read = database.read_session
        original_write = database.writer_session

        def read_session():  # type: ignore[no-untyped-def]
            self.reads += 1
            return original_read()

        def writer_session():  # type: ignore[no-untyped-def]
            self.writes += 1
            return original_write()

        monkeypatch.setattr(database, "read_session", read_session)
        monkeypatch.setattr(database, "writer_session", writer_session)


@pytest.fixture
async def warm(
    database: Database, live: LiveStore, importer: MetadataImporter, registry: SourceRegistry
) -> MetadataCache:
    """A started cache over a populated dataset and a warm live set."""
    addresses = [f"{index:06x}" for index in range(BATCH_SIZE)]
    registry.register(
        "mictronics",
        InMemoryMetadataProvider([record(icao, type_code="B738") for icao in addresses]),
    )
    await importer.run()
    cache = MetadataCache(database=database, live=live)
    await cache.start()
    live.apply_updates(updates(*addresses))
    await settle(cache)
    return cache


async def test_applying_a_batch_opens_no_session_at_all(
    warm: MetadataCache, database: Database, live: LiveStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """500 aircraft, all already live and cached: not one session opened."""
    spy = SessionSpy(database, monkeypatch)
    poll = batch(*[f"{index:06x}" for index in range(BATCH_SIZE)])

    for _ in range(3):
        live.apply(poll)

    assert (spy.reads, spy.writes) == (0, 0)
    await warm.stop()


async def test_a_batch_of_brand_new_aircraft_still_opens_no_session_on_the_hot_path(
    warm: MetadataCache, database: Database, live: LiveStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appearances are what cost a read — and they cost it on the other task.

    ``apply`` publishes and returns; the reads happen later, when the cache's
    own task is scheduled. So even a batch that is entirely new aircraft leaves
    the hot path free of sessions.
    """
    spy = SessionSpy(database, monkeypatch)

    live.apply(batch(*[f"c{index:05x}" for index in range(BATCH_SIZE)]))

    assert (spy.reads, spy.writes) == (0, 0)

    await settle(warm)
    assert spy.reads > 0
    await warm.stop()


async def test_cache_lookups_never_touch_the_database(
    warm: MetadataCache, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``get`` is the API and classification read path; it must be pure memory."""
    spy = SessionSpy(database, monkeypatch)

    for index in range(BATCH_SIZE):
        icao = f"{index:06x}"
        assert warm.get(icao) is not None
        warm.sighting_count(icao)
        warm.type_count("B738")

    assert (spy.reads, spy.writes) == (0, 0)
    await warm.stop()


def test_the_live_package_does_not_import_the_database() -> None:
    """Structural: there is no code path from the live store to SQLite.

    Stronger than counting sessions on one batch — a module that cannot reach
    the database cannot reach it on any batch.
    """
    live_dir = Path(LiveStore.__module__.replace(".", "/")).parent
    package = Path(__file__).resolve().parents[2] / "src" / live_dir

    offenders = [
        path.name
        for path in package.glob("*.py")
        if "flightsite.db" in path.read_text(encoding="utf-8")
        or "sqlalchemy" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_the_live_store_never_references_the_metadata_cache() -> None:
    """The coupling runs one way: the cache consumes events, never the reverse."""
    package = Path(__file__).resolve().parents[2] / "src" / "flightsite" / "live"

    offenders = [
        path.name
        for path in package.glob("*.py")
        if "flightsite.metadata" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


@pytest.mark.perf
async def test_applying_a_batch_stays_far_inside_the_polling_interval(
    warm: MetadataCache, live: LiveStore
) -> None:
    """Sanity: the cache running must not slow the batch apply budget.

    ``docs/ARCHITECTURE.md`` §6 budgets a 500-aircraft apply well under one
    polling interval. This is not the slice's own gate (slice 049 owns that) —
    it is a guard that attaching a subscriber did not change the shape of the
    hot path.
    """
    poll = batch(*[f"{index:06x}" for index in range(BATCH_SIZE)])

    started = time.perf_counter()
    for _ in range(10):
        live.apply(poll)
    elapsed = time.perf_counter() - started

    assert elapsed / 10 < 0.1
    await warm.stop()
