"""Resolution against the database: the rebuild, its paging, and the FK.

:mod:`tests.metadata.test_precedence` covers the merge rule in memory; this
covers what the repository does with it — that the materialized table matches
the pure function over the same claims, that streaming does not lose or split
an airframe at a page boundary, and that the operator-group foreign key
``docs/DATA_MODEL.md`` §3.3 requires from birth actually works.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from flightsite.classification.operators import default_directory
from flightsite.db import Database
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.importer import TRANSFORM_BATCH
from flightsite.metadata.precedence import PrecedenceModel, SourceClaim
from flightsite.metadata.repository import (
    REBUILD_PAGE_ROWS,
    AircraftLookup,
    MetadataRepository,
)
from tests.metadata.conftest import IMPORT_MS, record, resolved_rows, seed_aircraft
from tests.metadata.provider import InMemoryMetadataProvider


async def test_the_materialized_table_matches_the_pure_resolution(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """The stored row must equal what the precedence model computes in memory."""
    mictronics = record("a00001", registration="N1AA", type_code="B738", model="737-800")
    faa = record("a00001", registration="N1ZZ", manufacture_year=2016, owner="Someone")
    registry.register("mictronics", InMemoryMetadataProvider([mictronics]))
    registry.register("faa", InMemoryMetadataProvider([faa]))

    await importer.run()

    expected = registry.precedence().resolve(
        "a00001",
        [SourceClaim("mictronics", mictronics), SourceClaim("faa", faa)],
        updated_ms=IMPORT_MS,
    )
    stored = (await resolved_rows(repository, ["a00001"]))["a00001"]
    assert stored == expected


async def test_an_airframe_no_source_describes_is_absent_not_blank(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """A row of nothing but NULLs would claim to be an answer."""
    registry.register(
        "faa",
        InMemoryMetadataProvider([record("a00001"), record("a00002", registration="N2BB")]),
    )

    await importer.run()

    resolved = await resolved_rows(repository, ["a00001", "a00002"])
    assert set(resolved) == {"a00002"}


async def test_resolution_survives_more_airframes_than_fit_one_page(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """Streaming must not drop, duplicate, or split an airframe's claims.

    Sized past *both* streamed boundaries — the transform's staging batch and
    the rebuild's keyset page — with two sources per airframe, so a boundary
    lands mid-group in each. The deliberately awkward ``+ 37`` keeps the final
    page partial.
    """
    count = max(REBUILD_PAGE_ROWS, TRANSFORM_BATCH) + 37
    addresses = [f"{index:06x}" for index in range(count)]
    registry.register(
        "mictronics",
        InMemoryMetadataProvider(
            [
                record(icao, type_code="B738", registration=f"N{index}")
                for index, icao in enumerate(addresses)
            ]
        ),
    )
    registry.register(
        "faa",
        InMemoryMetadataProvider(
            [
                record(icao, manufacture_year=2000 + (index % 20))
                for index, icao in enumerate(addresses)
            ]
        ),
    )

    await importer.run()

    resolved = await resolved_rows(repository, addresses)
    assert len(resolved) == count
    assert all(row.type_code_src == "mictronics" for row in resolved.values())
    assert all(row.year_src == "faa" for row in resolved.values())


async def test_a_curated_operator_group_is_attached_when_one_exists(
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
) -> None:
    """Slice 021 built the FK and the join; slice 024 supplies the data.

    The group id is read back from the directory rather than written into the
    test: ids are assigned from the curated slugs, so adding an airline to the
    data file legitimately moves them.
    """
    directory = default_directory()

    registry.register(
        "mictronics",
        InMemoryMetadataProvider(
            [
                record("a00001", operator_name="Delta Air Lines", type_code="B738"),
                record("a00002", operator_name="Nobody In Particular", type_code="A320"),
            ]
        ),
    )
    await importer.run()

    resolved = await resolved_rows(repository, ["a00001", "a00002"])
    assert resolved["a00001"].operator_group_id == directory.group_id("delta")
    # Grouping is additive: the exact operator string is preserved either way.
    assert resolved["a00001"].operator_name == "Delta Air Lines"
    assert resolved["a00002"].operator_group_id is None
    assert resolved["a00002"].operator_name == "Nobody In Particular"


async def test_resolution_ignores_rows_from_an_unregistered_source(
    database: Database, repository: MetadataRepository
) -> None:
    """Rows left by a source this build dropped rank unranked, never first."""
    async with database.writer_session() as session:
        await session.execute(
            text("INSERT INTO metadata_sources (source, status) VALUES ('gone', 'ok')")
        )
        await session.execute(
            text("INSERT INTO metadata_sources (source, status) VALUES ('mictronics', 'ok')")
        )
        for source, type_code in (("gone", "OLD1"), ("mictronics", "B738")):
            await session.execute(
                text(
                    "INSERT INTO aircraft_metadata (icao24, source, type_code, updated_ms) "
                    "VALUES ('a00001', :source, :type_code, :ms)"
                ),
                {"source": source, "type_code": type_code, "ms": IMPORT_MS},
            )
        registered = SourceRegistry()
        registered.register("mictronics", InMemoryMetadataProvider())
        await repository.rebuild_resolved(
            session, precedence=registered.precedence(), at_ms=IMPORT_MS
        )

    resolved = await resolved_rows(repository, ["a00001"])
    assert resolved["a00001"].type_code_src == "mictronics"


async def test_looking_up_nothing_reads_nothing(
    repository: MetadataRepository,
) -> None:
    assert await repository.load_live_view([]) == {}


async def test_staging_nothing_writes_nothing(repository: MetadataRepository) -> None:
    """A transform that yields an empty batch must not open a transaction."""
    assert await repository.stage_batch("faa", [], updated_ms=IMPORT_MS) == 0
    assert await repository.count_staged("faa") == 0


async def test_a_lookup_reports_every_requested_address(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """Present-but-unknown and never-asked are different answers to the cache."""
    registry.register("mictronics", InMemoryMetadataProvider([record("a00001", type_code="B738")]))
    await importer.run()

    view = await repository.load_live_view(["a00001", "beef01"])

    assert set(view) == {"a00001", "beef01"}
    assert view["beef01"] == AircraftLookup()
    assert view["a00001"].metadata is not None
    assert view["a00001"].sighting_count is None


async def test_a_lookup_chunks_past_the_bound_parameter_limit(
    importer: MetadataImporter, registry: SourceRegistry, repository: MetadataRepository
) -> None:
    """SQLite's default host-parameter limit is 999; a live set can exceed it."""
    addresses = [f"{index:06x}" for index in range(1_500)]
    registry.register(
        "mictronics",
        InMemoryMetadataProvider([record(icao, type_code="B738") for icao in addresses]),
    )
    await importer.run()

    resolved = await resolved_rows(repository, addresses)

    assert len(resolved) == 1_500


@pytest.mark.parametrize("empty", [True, False])
async def test_type_counts_count_unique_airframes(
    database: Database,
    importer: MetadataImporter,
    registry: SourceRegistry,
    repository: MetadataRepository,
    empty: bool,
) -> None:
    """``type_stats`` lands in slice 031; until then this is the same figure."""
    registry.register(
        "mictronics",
        InMemoryMetadataProvider(
            [
                record("a00001", type_code="B738"),
                record("a00002", type_code="B738"),
                record("a00003", type_code="A320"),
                record("a00004", type_code="A320"),
                record("a00005", registration="N5EE"),
            ]
        ),
    )
    await importer.run()
    if not empty:
        await seed_aircraft(
            database, {"a00001": 3, "a00002": 1, "a00003": 7, "a00005": 2, "a00006": 9}
        )

    counts = await repository.load_type_counts()

    assert counts == ({} if empty else {"B738": 2, "A320": 1})


def test_precedence_over_an_empty_claim_list_is_stable() -> None:
    """Defensive: a rebuild over an empty table must not raise."""
    resolved = PrecedenceModel({}).resolve("a00001", [], updated_ms=IMPORT_MS)

    assert resolved.is_empty
