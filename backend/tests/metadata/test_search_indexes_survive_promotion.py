"""The resolved table's search indexes survive every way it is replaced.

Rev 0018 adds two ``COLLATE NOCASE`` indexes to ``aircraft_metadata_resolved``
for the Aircraft page's ``q`` search (slice 083). A promotion drops them for
its bulk copy and rebuilds them afterwards (``_install_resolution``), because
maintaining them row by row roughly tripled the writer-held swap. That trade is
only safe if the rebuild is exact and unconditional, so this pins:

* after a promotion, and after a resolution-only rebuild, both indexes exist
  with the same definition the migration created — and answer a
  case-insensitive prefix from the new rows;
* a swap that fails after the drop rolls it back with everything else: the
  previous dataset *and* its indexes are exactly as they were.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from flightsite.db import Database
from flightsite.metadata import MetadataRepository, SourceRegistry
from flightsite.metadata import repository as repository_module
from flightsite.metadata.precedence import PrecedenceModel
from tests.metadata.conftest import IMPORT_MS, record
from tests.metadata.provider import InMemoryMetadataProvider

INDEXES = dict(repository_module.SEARCH_INDEXES)


@pytest.fixture
def precedence() -> PrecedenceModel:
    registry = SourceRegistry()
    registry.register("faa", InMemoryMetadataProvider())
    return registry.precedence()


def _index_sql(path: Path) -> dict[str, str]:
    """Each search index's stored definition, whitespace-normalized."""
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name IN (?, ?)",
            tuple(INDEXES),
        ).fetchall()
    return {str(name): " ".join(str(sql).split()).upper() for name, sql in rows}


def _prefix_hits(path: Path, index: str, column: str, prefix: str) -> list[str]:
    """``icao24`` of rows whose ``column`` starts with ``prefix``, read via ``index``."""
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            f"SELECT icao24 FROM aircraft_metadata_resolved INDEXED BY {index} "
            f"WHERE {column} COLLATE NOCASE >= ? AND {column} COLLATE NOCASE < ? "
            "ORDER BY icao24",
            (prefix, prefix + "\U0010ffff"),
        ).fetchall()
    return [str(row[0]) for row in rows]


async def _promote(
    repository: MetadataRepository,
    precedence: PrecedenceModel,
    records: Sequence[object],
    version: str,
) -> None:
    await repository.ensure_source("faa")
    await repository.clear_staging("faa")
    await repository.stage_batch("faa", records, updated_ms=IMPORT_MS)  # type: ignore[arg-type]
    await repository.promote(
        "faa",
        precedence=precedence,
        at_ms=IMPORT_MS,
        dataset_version=version,
        row_count=len(records),
    )


def _fleet(registration_prefix: str) -> list[object]:
    return [
        record(
            f"a{index:05x}",
            registration=f"{registration_prefix}{index:03d}",
            operator_name=f"Operator {index % 3}",
        )
        for index in range(12)
    ]


async def test_a_promotion_leaves_both_indexes_as_the_migration_made_them(
    database: Database,
    db_path: Path,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
) -> None:
    migrated = _index_sql(db_path)
    assert set(migrated) == set(INDEXES)

    await _promote(repository, precedence, _fleet("G-EZ"), "faa-1")

    assert _index_sql(db_path) == migrated
    for index, column in INDEXES.items():
        assert f"{column.upper()} COLLATE NOCASE" in migrated[index]


async def test_the_rebuilt_indexes_answer_from_the_new_rows(
    database: Database,
    db_path: Path,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
) -> None:
    await _promote(repository, precedence, _fleet("G-EZ"), "faa-1")
    await _promote(repository, precedence, _fleet("D-AI"), "faa-2")

    registration_index = "ix_amr_registration_nocase"
    assert len(_prefix_hits(db_path, registration_index, "registration", "d-ai")) == 12
    assert _prefix_hits(db_path, registration_index, "registration", "g-ez") == []
    assert len(_prefix_hits(db_path, "ix_amr_operator_nocase", "operator_name", "OPERATOR 1")) == 4


async def test_a_resolution_only_rebuild_keeps_them_too(
    database: Database,
    db_path: Path,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
) -> None:
    await _promote(repository, precedence, _fleet("VH-"), "faa-1")
    migrated = _index_sql(db_path)

    await repository.rebuild_resolved(precedence=precedence, at_ms=IMPORT_MS)

    assert _index_sql(db_path) == migrated
    assert len(_prefix_hits(db_path, "ix_amr_registration_nocase", "registration", "vh")) == 12


async def test_a_failed_swap_rolls_the_drop_back(
    database: Database,
    db_path: Path,
    repository: MetadataRepository,
    precedence: PrecedenceModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure lands between the drop and the rebuild — the worst place."""
    await _promote(repository, precedence, _fleet("G-EZ"), "faa-1")
    before = _index_sql(db_path)

    async def fail(*_: object, **__: object) -> None:
        raise RuntimeError("disk full mid-swap")

    monkeypatch.setattr(repository_module, "_install_from_staging", fail)
    with pytest.raises(RuntimeError, match="disk full"):
        await _promote(repository, precedence, _fleet("D-AI"), "faa-2")

    assert _index_sql(db_path) == before
    assert len(_prefix_hits(db_path, "ix_amr_registration_nocase", "registration", "g-ez")) == 12
