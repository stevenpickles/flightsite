"""Persisting classification and the curated operator tables.

Every statement here runs **inside a caller's transaction** — in practice the
metadata import's promotion (:meth:`flightsite.metadata.repository.
MetadataRepository.promote`), which is one transaction covering the whole
visible swap. None of these functions opens a session of its own, and that is
deliberate: a classification rebuild that committed separately from the
resolved rebuild would leave a window in which an aircraft's metadata and its
classification described different datasets.

Order matters, and it is dictated by ``foreign_keys=ON`` (ADR-0001).
``aircraft_metadata_resolved.operator_group_id`` references
``operator_groups``, so the group rows cannot be replaced while resolved rows
still point at them. The caller therefore clears the resolved table first;
:func:`sync_operator_directory` asserts nothing about that, it simply requires
it, and the repository's rebuild is written to do it in that order.

Idempotence is by construction rather than by upsert. The curated data is small
(a hundred groups, a few hundred names), the ids are derived from the slugs, and
the rows are deleted and re-inserted wholesale — so two runs over the same data
produce byte-identical tables, and a group removed from the data file actually
disappears instead of lingering as a row nothing references.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.classification.operators import OperatorDirectory
from flightsite.db.models import AircraftClassification, Operator, OperatorGroup

#: Rows per ``INSERT``. The curated tables never approach this; the
#: classification rebuild streams a whole metadata database through it.
INSERT_BATCH_ROWS = 1_000


async def sync_operator_directory(session: AsyncSession, directory: OperatorDirectory) -> int:
    """Replace ``operator_groups``/``operators`` with the curated data (§3.5).

    Returns the number of ``operators`` rows written. Children before parents on
    the way out, parents before children on the way in — the ordinary foreign
    key discipline, spelled out because SQLite enforces it.

    Only the curated *exact* names land here. Names matched by phrase are added
    by the caller as they are discovered in the dataset, since there is no
    finite list of them to write in advance.
    """
    await session.execute(delete(Operator))
    await session.execute(delete(OperatorGroup))

    groups = directory.group_rows()
    if groups:
        await session.execute(insert(OperatorGroup), groups)
    operators = directory.curated_operator_rows()
    await add_operators(session, operators)
    return len(operators)


async def add_operators(session: AsyncSession, rows: Sequence[Mapping[str, str | int]]) -> int:
    """Insert ``operators`` rows. Returns how many were written."""
    written = 0
    for start in range(0, len(rows), INSERT_BATCH_ROWS):
        chunk = rows[start : start + INSERT_BATCH_ROWS]
        await session.execute(insert(Operator), list(chunk))
        written += len(chunk)
    return written


async def clear_classifications(session: AsyncSession) -> None:
    """Drop every classification row, ahead of a rebuild.

    Cleared rather than upserted because a rebuild is authoritative: an airframe
    whose evidence changed from "military" to "nothing known" must lose its
    claim, and an upsert over the new rows alone would leave the old assertion
    standing. Honesty about *withdrawn* evidence is the same property as honesty
    about weak evidence.
    """
    await session.execute(delete(AircraftClassification))


async def add_classifications(
    session: AsyncSession, rows: Sequence[Mapping[str, str | int | float | None]]
) -> int:
    """Insert ``aircraft_classification`` rows. Returns how many were written."""
    written = 0
    for start in range(0, len(rows), INSERT_BATCH_ROWS):
        chunk = rows[start : start + INSERT_BATCH_ROWS]
        await session.execute(insert(AircraftClassification), list(chunk))
        written += len(chunk)
    return written


__all__ = [
    "INSERT_BATCH_ROWS",
    "add_classifications",
    "add_operators",
    "clear_classifications",
    "sync_operator_directory",
]
