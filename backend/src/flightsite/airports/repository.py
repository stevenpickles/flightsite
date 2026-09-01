"""Reading and replacing the ``airports`` table.

Two operations, and both are rare. :meth:`AirportRepository.load_all` runs
exactly twice in a process's life — once at startup and once after an import —
because everything downstream of it works from
:class:`~flightsite.airports.index.AirportIndex`, in memory. :meth:`replace_all`
runs when the user asks for a metadata update.

Neither is on any hot path. ``docs/ARCHITECTURE.md`` §3.1's rule — *no live
request or decoder poll ever waits on SQLite* — is what forces that shape: a
nearest-airport question arrives up to 500 times a second and cannot become a
query.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, func, insert, select, update

from flightsite.airports.records import AirportRecord
from flightsite.db import Airport, Database, MetadataSource
from flightsite.metadata.registry import SourceStatus

#: The success value written to ``metadata_sources.status``. Read from the
#: metadata registry's own enum rather than spelled again, so the two cannot
#: drift — this is the same vocabulary the aircraft sources write.
SOURCE_STATUS_OK: Final = SourceStatus.OK.value

#: Rows per ``INSERT`` during a replacement. SQLite's default parameter limit
#: is 999 in older builds and 32 766 in current ones; nine columns at 1 000
#: rows is 9 000 parameters, comfortably inside the modern limit while keeping
#: the statement small enough that its parameter list is not itself the memory
#: story.
INSERT_CHUNK_ROWS: Final = 1_000

#: Columns written by a replacement, in the order the row tuples build them.
_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "ident",
    "iata",
    "name",
    "type",
    "lat",
    "lon",
    "elevation_ft",
    "iso_country",
)


@dataclass(frozen=True, slots=True)
class AirportRepository:
    """Persistence operations for the ``airports`` table."""

    database: Database

    async def load_all(self) -> tuple[AirportRecord, ...]:
        """Every airport, ordered by ident.

        Ordered so an index rebuilt from the same table twice is the same
        index, which is what lets a test assert on the *first* airport a tie
        resolves to rather than on whichever one SQLite happened to return.
        """
        statement = select(
            Airport.id,
            Airport.ident,
            Airport.iata,
            Airport.name,
            Airport.type,
            Airport.lat,
            Airport.lon,
            Airport.elevation_ft,
            Airport.iso_country,
        ).order_by(Airport.ident)
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            AirportRecord(
                upstream_id=row_id,
                ident=ident,
                iata=iata,
                name=name,
                type=type_,
                lat=lat,
                lon=lon,
                elevation_ft=elevation_ft,
                iso_country=iso_country,
            )
            for row_id, ident, iata, name, type_, lat, lon, elevation_ft, iso_country in rows
        )

    async def count(self) -> int:
        """How many airports the table currently holds."""
        async with self.database.read_session() as session:
            total = await session.scalar(select(func.count()).select_from(Airport))
            return int(total or 0)

    async def replace_all(
        self,
        records: Sequence[AirportRecord],
        *,
        source: str,
        at_ms: int,
        dataset_version: str,
    ) -> int:
        """Make ``records`` the contents of ``airports`` and record the run. Atomic.

        One transaction covers the whole visible change: the previous rows go,
        the new ones land, and the ``metadata_sources`` row records the success
        — so a failure anywhere inside rolls the lot back and leaves the
        previous dataset, the index built from it, and the status that
        described it exactly as they were.

        The status row is written *here*, in the same transaction, rather than
        by the caller afterwards. That is the rule
        :meth:`flightsite.metadata.repository.MetadataRepository.promote`
        already follows for the aircraft dataset, and for the same reason: a
        status claiming success beside rows that were rolled back is the one
        inconsistency a user reading SPEC §27's per-source report cannot see
        through.

        Refuses an empty replacement. Emptying the table is never something an
        import means to do; a provider that yielded nothing has failed, and the
        pipeline's own row floor should already have caught it. Returns the
        number of rows written.
        """
        if not records:
            raise ValueError("refusing to replace the airport dataset with nothing")

        rows = _rows(records)
        async with self.database.writer_session() as session:
            await session.execute(delete(Airport))
            for start in range(0, len(rows), INSERT_CHUNK_ROWS):
                await session.execute(insert(Airport), rows[start : start + INSERT_CHUNK_ROWS])
            await session.execute(
                update(MetadataSource)
                .where(MetadataSource.source == source)
                .values(
                    status=SOURCE_STATUS_OK,
                    last_attempt_ms=at_ms,
                    last_success_ms=at_ms,
                    dataset_version=dataset_version,
                    row_count=len(rows),
                    last_error=None,
                )
            )
        return len(rows)


def _rows(records: Sequence[AirportRecord]) -> list[dict[str, object]]:
    """``records`` as insertable mappings, de-duplicated by ident.

    Later duplicates of an ident overwrite earlier ones rather than failing the
    import on the ``UNIQUE`` constraint: the last row is the conventional
    reading of a repeated key, and it is the same rule the aircraft-metadata
    staging table applies to a repeated address.

    Upstream ids are kept where they are usable — they are stable across
    releases, which makes a re-import diffable — but they are never *trusted*:
    a row with no id, or one whose id another row already claimed, is numbered
    after the highest id present instead. The alternative is an import that
    dies on the ``INTEGER PRIMARY KEY`` because upstream repeated a number, and
    the surrogate id is not worth failing an import over.
    """
    by_ident: dict[str, AirportRecord] = {record.ident: record for record in records}
    next_id = max((r.upstream_id or 0 for r in by_ident.values()), default=0) + 1
    taken: set[int] = set()
    rows: list[dict[str, object]] = []
    for record in by_ident.values():
        row_id = record.upstream_id
        if row_id is None or row_id in taken:
            row_id = next_id
            next_id += 1
        taken.add(row_id)
        rows.append(
            {
                "id": row_id,
                "ident": record.ident,
                "iata": record.iata,
                "name": record.name,
                "type": record.type,
                "lat": record.lat,
                "lon": record.lon,
                "elevation_ft": record.elevation_ft,
                "iso_country": record.iso_country,
            }
        )
    return rows


__all__ = ["INSERT_CHUNK_ROWS", "AirportRepository"]
