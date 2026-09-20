"""A promotion must not hold the single writer while it thinks (issue #185).

Slice 075's central claim, tested as three separate properties rather than as
a timing measurement:

* the Python that resolves and classifies runs on a worker thread, with the
  writer lock **not** held — asserted at every call, not sampled;
* the promotion takes the writer lock in short bursts, one per page of
  resolution plus the swap, rather than once for the duration;
* a competing writer — the shape the persistence worker and the alert engine
  have — actually gets the lock while the resolution is being built.

The last two are deterministic, not racy: :attr:`asyncio.Lock` hands the lock
to waiters in order, so a writer queued while one page's transaction is open
is served the moment that transaction commits. A small
:data:`flightsite.metadata.repository.REBUILD_PAGE_ROWS` is what turns a
modest fixture into several pages.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Sequence

import pytest
from sqlalchemy import text

from flightsite.classification.engine import classify
from flightsite.db import Database
from flightsite.metadata import MetadataRepository, SourceRegistry
from flightsite.metadata import repository as repository_module
from flightsite.metadata.precedence import PrecedenceModel
from tests.metadata.conftest import IMPORT_MS, record
from tests.metadata.provider import InMemoryMetadataProvider

#: Airframes in the fixture. Enough that the pass is worth threading and that
#: the default page size splits it in two, small enough to stage in a second.
AIRFRAMES = 3_000

#: Claim rows per page for the tests that count transactions. Twenty rows is
#: ten airframes, so the fixture below is many pages whatever else changes.
SMALL_PAGE_ROWS = 20

#: Airframes for the paging tests, where the point is the number of pages.
PAGED_AIRFRAMES = 60


def _icao(index: int) -> str:
    return f"a{index:05x}"


async def _stage(repository: MetadataRepository, source: str, records: Sequence[object]) -> None:
    await repository.ensure_source(source)
    await repository.clear_staging(source)
    await repository.stage_batch(source, records, updated_ms=IMPORT_MS)  # type: ignore[arg-type]


async def _install_two_sources(
    repository: MetadataRepository, precedence: PrecedenceModel, count: int
) -> None:
    """Promote an ``faa`` snapshot, then stage a ``mictronics`` one over it.

    The two sources claim disjoint fields, so what every resolved row must
    look like afterwards is knowable without re-deriving the precedence model:
    the registration is the FAA's, the type code Mictronics'.
    """
    await _stage(
        repository,
        "faa",
        [record(_icao(index), registration=f"N{index:05d}") for index in range(count)],
    )
    await repository.promote(
        "faa", precedence=precedence, at_ms=IMPORT_MS, dataset_version="faa-1", row_count=count
    )
    await _stage(
        repository,
        "mictronics",
        [record(_icao(index), type_code="B738") for index in range(count)],
    )


@pytest.fixture
def precedence() -> PrecedenceModel:
    """The model a registry with both aircraft sources produces."""
    registry = SourceRegistry()
    registry.register("faa", InMemoryMetadataProvider())
    registry.register("mictronics", InMemoryMetadataProvider())
    return registry.precedence()


async def _resolved_sources(database: Database) -> set[tuple[str, str]]:
    async with database.read_session() as session:
        rows = (
            await session.execute(
                text("SELECT registration_src, type_code_src FROM aircraft_metadata_resolved")
            )
        ).all()
    return {(str(row[0]), str(row[1])) for row in rows}


async def _resolved_count(database: Database) -> int:
    async with database.read_session() as session:
        return int(
            (
                await session.execute(text("SELECT COUNT(*) FROM aircraft_metadata_resolved"))
            ).scalar_one()
        )


# ------------------------------------------------- resolution off the lock


async def test_resolution_and_classification_never_run_under_the_writer_lock(
    database: Database,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every ``resolve`` and every ``classify`` of a real promotion, checked.

    Both are wrapped rather than sampled: one call on the event loop with the
    writer held is the defect this slice exists to remove, and an instrument
    that only looks now and then would not see it.
    """
    await _install_two_sources(repository, precedence, AIRFRAMES)

    on_main_thread: list[str] = []
    under_the_lock: list[str] = []
    resolved_calls = 0
    classify_calls = 0

    def note(what: str) -> None:
        if threading.current_thread() is threading.main_thread():
            on_main_thread.append(what)
        if database.writer_busy:
            under_the_lock.append(what)

    original_resolve = PrecedenceModel.resolve
    original_classify = classify

    def wrapped_resolve(self: PrecedenceModel, *args: object, **kwargs: object) -> object:
        nonlocal resolved_calls
        resolved_calls += 1
        note("resolve")
        return original_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    def wrapped_classify(*args: object, **kwargs: object) -> object:
        nonlocal classify_calls
        classify_calls += 1
        note("classify")
        return original_classify(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PrecedenceModel, "resolve", wrapped_resolve)
    monkeypatch.setattr(repository_module, "classify", wrapped_classify)

    await repository.promote(
        "mictronics",
        precedence=precedence,
        at_ms=IMPORT_MS,
        dataset_version="mict-1",
        row_count=AIRFRAMES,
    )

    assert resolved_calls == AIRFRAMES
    assert classify_calls == AIRFRAMES
    assert on_main_thread == []
    assert under_the_lock == []


async def test_the_promotion_resolves_every_airframe_from_the_post_swap_picture(
    database: Database, repository: MetadataRepository, precedence: PrecedenceModel
) -> None:
    """Moving the work did not change its answer.

    The claim view a build pages through is the *staged* source plus every
    other source's live rows, so a field only the incoming snapshot supplies
    has to win on every airframe — which it can only do if the staged rows
    were read.
    """
    await _install_two_sources(repository, precedence, AIRFRAMES)

    await repository.promote(
        "mictronics",
        precedence=precedence,
        at_ms=IMPORT_MS,
        dataset_version="mict-1",
        row_count=AIRFRAMES,
    )

    assert await _resolved_count(database) == AIRFRAMES
    assert await _resolved_sources(database) == {("faa", "mictronics")}


# --------------------------------------------------- short transactions


async def test_the_promotion_takes_the_writer_lock_once_per_page_and_once_to_swap(
    database: Database,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build's transactions are counted, because their number is the point.

    One to clear the scratch tables, one per page of resolution, one for the
    swap. The assertion is a floor rather than an equality so that a future
    page that writes twice is not a failure — what must never happen is the
    single transaction this slice replaced.
    """
    monkeypatch.setattr(repository_module, "REBUILD_PAGE_ROWS", SMALL_PAGE_ROWS)
    await _install_two_sources(repository, precedence, PAGED_AIRFRAMES)

    acquisitions = 0
    original = Database.writer_session

    def counting(self: Database) -> AsyncIterator[object]:
        nonlocal acquisitions
        acquisitions += 1
        return original(self)  # type: ignore[return-value]

    monkeypatch.setattr(Database, "writer_session", counting)

    await repository.promote(
        "mictronics",
        precedence=precedence,
        at_ms=IMPORT_MS,
        dataset_version="mict-1",
        row_count=PAGED_AIRFRAMES,
    )

    # Two sources per airframe, cut back to whole airframes: SMALL_PAGE_ROWS
    # claim rows is SMALL_PAGE_ROWS // 2 airframes per page.
    pages = PAGED_AIRFRAMES // (SMALL_PAGE_ROWS // 2)
    assert acquisitions >= 1 + pages + 1


async def test_a_competing_writer_gets_the_lock_while_resolution_is_built(
    database: Database,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persistence worker's shape: a writer that must keep draining.

    It is counted only up to the moment the swap opens its transaction, so
    what the assertion proves is that the lock was free *during the build* —
    the phase that used to hold it from beginning to end.
    """
    monkeypatch.setattr(repository_module, "REBUILD_PAGE_ROWS", SMALL_PAGE_ROWS)
    await _install_two_sources(repository, precedence, PAGED_AIRFRAMES)

    writes = 0
    writes_before_the_swap = -1
    stop = asyncio.Event()

    async def keep_writing() -> None:
        nonlocal writes
        while not stop.is_set():
            async with database.writer_session() as session:
                await session.execute(text("UPDATE meta SET value = value WHERE key = 'nothing'"))
            writes += 1
            await asyncio.sleep(0)

    original_install = MetadataRepository._install_resolution

    async def watched_install(self: MetadataRepository, *args: object, **kwargs: object) -> None:
        nonlocal writes_before_the_swap
        writes_before_the_swap = writes
        await original_install(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(MetadataRepository, "_install_resolution", watched_install)

    competitor = asyncio.create_task(keep_writing())
    try:
        await repository.promote(
            "mictronics",
            precedence=precedence,
            at_ms=IMPORT_MS,
            dataset_version="mict-1",
            row_count=PAGED_AIRFRAMES,
        )
    finally:
        stop.set()
        await competitor

    pages = PAGED_AIRFRAMES // (SMALL_PAGE_ROWS // 2)
    assert writes_before_the_swap >= pages
