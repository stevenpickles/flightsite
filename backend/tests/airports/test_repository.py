"""The ``airports`` table: replaced whole, atomically, or not at all.

The guarantee under test is the one the whole import pipeline is built around
and which ``docs/DATA_MODEL.md`` §3.2 states for the aircraft dataset: **a
failed import leaves the previous dataset fully intact.** The airport sink
reaches it by a different route — buffer, then one transaction — so the route
is what these tests exercise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from flightsite.airports import AirportRepository
from flightsite.airports.records import AirportRecord
from flightsite.db import Database
from flightsite.metadata.registry import SourceStatus
from flightsite.metadata.repository import MetadataRepository
from tests.airports.conftest import BASE_EPOCH_MS, FIXTURE_AIRPORTS, airport

SOURCE = "airports"


async def replace(
    repository: AirportRepository,
    records: tuple[AirportRecord, ...] = FIXTURE_AIRPORTS,
    *,
    at_ms: int = BASE_EPOCH_MS,
    version: str = "sha256:aaaa",
) -> int:
    return await repository.replace_all(
        list(records), source=SOURCE, at_ms=at_ms, dataset_version=version
    )


async def test_a_replacement_round_trips(repository: AirportRepository) -> None:
    written = await replace(repository)

    loaded = await repository.load_all()
    assert written == len(FIXTURE_AIRPORTS)
    assert {record.ident for record in loaded} == {a.ident for a in FIXTURE_AIRPORTS}

    boeing = next(record for record in loaded if record.ident == "KBFI")
    assert boeing.name == "Boeing Field"
    assert boeing.type == "large_airport"
    assert boeing.lat == pytest.approx(47.53)
    assert boeing.lon == pytest.approx(-122.3018)
    assert boeing.elevation_ft == 21
    assert boeing.iata == "BFI"
    assert boeing.upstream_id == 3411


async def test_rows_come_back_in_ident_order(repository: AirportRepository) -> None:
    """So an index built twice from the same table is the same index."""
    await replace(repository)

    loaded = await repository.load_all()

    assert [record.ident for record in loaded] == sorted(a.ident for a in FIXTURE_AIRPORTS)


async def test_a_field_with_no_elevation_round_trips_as_none(
    repository: AirportRepository,
) -> None:
    """The ~16% case, all the way through SQLite."""
    await replace(repository)

    loaded = {record.ident: record for record in await repository.load_all()}

    assert loaded["KNOEL"].elevation_ft is None
    assert loaded["KNOEL"].iata is None


async def test_a_replacement_replaces_rather_than_merges(
    repository: AirportRepository,
) -> None:
    """A dataset that lost an airport loses it here too."""
    await replace(repository)

    await replace(repository, (airport("ONLY1", 10.0, 10.0),))

    loaded = await repository.load_all()
    assert [record.ident for record in loaded] == ["ONLY1"]
    assert await repository.count() == 1


async def test_replacing_with_nothing_is_refused(repository: AirportRepository) -> None:
    """Emptying the table is never something an import means to do."""
    await replace(repository)

    with pytest.raises(ValueError, match="nothing"):
        await replace(repository, ())

    assert await repository.count() == len(FIXTURE_AIRPORTS)


async def test_a_repeated_ident_collapses_to_the_last_row(
    repository: AirportRepository,
) -> None:
    """The conventional reading of a repeated key, and it beats a failed import."""
    await replace(
        repository,
        (
            airport("DUPE", 10.0, 10.0, name="First", upstream_id=1),
            airport("DUPE", 11.0, 11.0, name="Second", upstream_id=2),
        ),
    )

    loaded = await repository.load_all()
    assert len(loaded) == 1
    assert loaded[0].name == "Second"


async def test_a_repeated_upstream_id_is_renumbered_rather_than_failing(
    repository: AirportRepository,
) -> None:
    """The surrogate id is not worth failing an import over."""
    written = await replace(
        repository,
        (
            airport("ONE", 10.0, 10.0, upstream_id=7),
            airport("TWO", 11.0, 11.0, upstream_id=7),
        ),
    )

    assert written == 2
    loaded = await repository.load_all()
    assert {record.ident for record in loaded} == {"ONE", "TWO"}
    assert len({record.upstream_id for record in loaded}) == 2


async def test_a_record_with_no_upstream_id_is_numbered(
    repository: AirportRepository,
) -> None:
    await replace(
        repository,
        (airport("WITH", 10.0, 10.0, upstream_id=42), airport("WITHOUT", 11.0, 11.0)),
    )

    loaded = {record.ident: record for record in await repository.load_all()}

    assert loaded["WITH"].upstream_id == 42
    assert loaded["WITHOUT"].upstream_id is not None
    assert loaded["WITHOUT"].upstream_id != 42


async def test_an_empty_table_loads_as_nothing(repository: AirportRepository) -> None:
    """The state of every install that has never run an update."""
    assert await repository.load_all() == ()
    assert await repository.count() == 0


# ------------------------------------------------------------ the status row


async def test_a_replacement_records_its_own_success(
    repository: AirportRepository, database: Database
) -> None:
    """SPEC §27's per-source report, written in the same transaction as the rows."""
    metadata = MetadataRepository(database)
    await metadata.ensure_source(SOURCE)

    await replace(repository, at_ms=1_700_000_000_000, version="sha256:beef")

    status = await metadata.read_status(SOURCE)
    assert status is not None
    assert status.status == SourceStatus.OK
    assert status.last_success_ms == 1_700_000_000_000
    assert status.last_attempt_ms == 1_700_000_000_000
    assert status.dataset_version == "sha256:beef"
    assert status.row_count == len(FIXTURE_AIRPORTS)
    assert status.last_error is None


async def test_the_recorded_row_count_is_what_the_table_holds(
    repository: AirportRepository, database: Database
) -> None:
    """After de-duplication, so the number a user reads is the number of rows."""
    metadata = MetadataRepository(database)
    await metadata.ensure_source(SOURCE)

    await replace(
        repository,
        (
            airport("DUPE", 10.0, 10.0, upstream_id=1),
            airport("DUPE", 11.0, 11.0, upstream_id=2),
        ),
    )

    status = await metadata.read_status(SOURCE)
    assert status is not None
    assert status.row_count == 1


async def test_a_replacement_clears_a_previous_failure(
    repository: AirportRepository, database: Database
) -> None:
    """A recovered source must not keep reporting the error it recovered from."""
    metadata = MetadataRepository(database)
    await metadata.ensure_source(SOURCE)
    await metadata.mark_failure(SOURCE, at_ms=1, error="the network was down")

    await replace(repository)

    status = await metadata.read_status(SOURCE)
    assert status is not None
    assert status.status == SourceStatus.OK
    assert status.last_error is None


# ---------------------------------------------------------------- atomicity


async def test_a_failed_replacement_leaves_the_previous_dataset_intact(
    repository: AirportRepository, database: Database, db_path: Path
) -> None:
    """The guarantee, provoked rather than asserted about.

    A record whose ``name`` violates the table's ``NOT NULL`` fails the
    transaction partway through the inserts — after the ``DELETE`` has already
    run inside it. If the delete were not rolled back with everything else, the
    previous dataset would be gone.
    """
    await replace(repository)
    assert await repository.count() == len(FIXTURE_AIRPORTS)

    broken = (
        airport("GOOD1", 10.0, 10.0),
        AirportRecord(
            ident="BROKEN",
            name=None,  # type: ignore[arg-type]
            type="small_airport",
            lat=11.0,
            lon=11.0,
        ),
    )
    with pytest.raises(IntegrityError):
        await replace(repository, broken)

    loaded = await repository.load_all()
    assert {record.ident for record in loaded} == {a.ident for a in FIXTURE_AIRPORTS}
    assert "GOOD1" not in {record.ident for record in loaded}


async def test_a_failed_replacement_does_not_record_a_success(
    repository: AirportRepository, database: Database
) -> None:
    """Status and rows roll back together, so neither can lie about the other."""
    metadata = MetadataRepository(database)
    await metadata.ensure_source(SOURCE)
    await replace(repository, version="sha256:first")

    broken = (
        AirportRecord(
            ident="BROKEN",
            name=None,  # type: ignore[arg-type]
            type="small_airport",
            lat=11.0,
            lon=11.0,
        ),
    )
    with pytest.raises(IntegrityError):
        await replace(repository, broken, version="sha256:second")

    status = await metadata.read_status(SOURCE)
    assert status is not None
    assert status.dataset_version == "sha256:first"


async def test_a_replacement_larger_than_one_insert_chunk_lands_whole(
    repository: AirportRepository,
) -> None:
    """The chunk loop is a parameter-limit accommodation, not a transaction boundary."""
    many = tuple(
        airport(f"P{index:04d}", 10.0 + index / 1000.0, 10.0, upstream_id=index + 1)
        for index in range(2_500)
    )

    written = await replace(repository, many)

    assert written == 2_500
    assert await repository.count() == 2_500


# ------------------------------------------------------- clear_all (slice 045)


async def test_clear_all_empties_the_table_and_reports_what_it_removed(
    repository: AirportRepository,
) -> None:
    """SPEC §73's Clear Metadata Cache action, at the repository layer."""
    await replace(repository)
    assert await repository.count() == len(FIXTURE_AIRPORTS)

    removed = await repository.clear_all()

    assert removed == len(FIXTURE_AIRPORTS)
    assert await repository.load_all() == ()
    assert await repository.count() == 0


async def test_clear_all_on_an_empty_table_removes_nothing(
    repository: AirportRepository,
) -> None:
    """Idempotent: a second clear (or a first, on a fresh install) is a no-op."""
    assert await repository.clear_all() == 0
    assert await repository.count() == 0
