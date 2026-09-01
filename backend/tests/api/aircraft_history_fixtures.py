"""Shared fixture-building helpers for the Aircraft page's tests.

Rows are built through SQLAlchemy Core ``insert()`` against the ORM models —
the same statement shape :meth:`~flightsite.metadata.repository.MetadataRepository.rebuild_resolved`
issues when it rebuilds ``aircraft_metadata_resolved`` and
``aircraft_classification`` — rather than hand-written SQL text or the full
live→sighting→persistence-worker pipeline. Driving a few thousand aircraft
through that pipeline would cost seconds per aircraft; a bulk insert of the
rows the pipeline eventually produces costs milliseconds and exercises
exactly the tables :mod:`flightsite.api.history` reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flightsite.db import Database
from flightsite.db.models import (
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    OperatorGroup,
)

#: A frozen "now" for stored ``updated_ms`` columns, well within the
#: fixture's own ``first_seen_ms``/``last_seen_ms`` range.
UPDATED_MS = 1_756_600_000_000


@dataclass(slots=True)
class SeedAircraft:
    """One row's worth of input across ``aircraft``, the resolved metadata,
    curated operator group and classification tables.

    A metadata field left at its default (``None``/``"unknown"``/``False``)
    means "no source claims this" — mirroring §2.7, that omits the field's
    row from ``aircraft_metadata_resolved``/``aircraft_classification``
    entirely for this airframe when *none* of that table's fields are set,
    the same way a real import does (`ResolvedMetadata.is_empty`,
    `Classification.is_unknown`). That is deliberate: it is what lets a test
    build the "never resolved" case for free by simply not setting any
    metadata fields.
    """

    icao24: str
    first_seen_ms: int
    last_seen_ms: int
    sighting_count: int = 1
    total_observed_ms: int = 60_000
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_alt_ft: int | None = None
    highest_alt_ft: int | None = None

    registration: str | None = None
    registration_src: str | None = "mictronics"
    type_code: str | None = None
    type_code_src: str | None = "mictronics"
    model: str | None = None
    model_src: str | None = "mictronics"
    manufacture_year: int | None = None
    year_src: str | None = "faa"
    operator_name: str | None = None
    operator_src: str | None = "mictronics"
    operator_group_slug: str | None = None
    owner: str | None = None
    owner_src: str | None = "faa"

    military: bool = False
    military_src: str | None = "mictronics"
    military_conf: float | None = 0.95
    government: bool = False
    government_src: str | None = "heuristic"
    government_conf: float | None = 0.7
    law_enforcement: bool = False
    law_enforcement_src: str | None = "heuristic"
    law_enforcement_conf: float | None = 0.7
    mission_category: str = "unknown"
    mission_src: str | None = "heuristic"
    mission_conf: float | None = 0.7
    icon_category: str = "unknown"

    def _resolved_populated(self) -> bool:
        return any(
            value is not None
            for value in (
                self.registration,
                self.type_code,
                self.model,
                self.manufacture_year,
                self.operator_name,
                self.owner,
            )
        )

    def _classification_populated(self) -> bool:
        return (
            self.military
            or self.government
            or self.law_enforcement
            or self.mission_category != "unknown"
            or self.icon_category != "unknown"
        )

    def aircraft_row(self) -> dict[str, Any]:
        return {
            "icao24": self.icao24,
            "first_seen_ms": self.first_seen_ms,
            "last_seen_ms": self.last_seen_ms,
            "sighting_count": self.sighting_count,
            "total_observed_ms": self.total_observed_ms,
            "closest_approach_nm": self.closest_approach_nm,
            "max_range_nm": self.max_range_nm,
            "lowest_alt_ft": self.lowest_alt_ft,
            "highest_alt_ft": self.highest_alt_ft,
        }

    def resolved_row(self, group_ids: dict[str, int]) -> dict[str, Any] | None:
        if not self._resolved_populated():
            return None
        group_id = None if self.operator_group_slug is None else group_ids[self.operator_group_slug]
        return {
            "icao24": self.icao24,
            "registration": self.registration,
            "registration_src": None if self.registration is None else self.registration_src,
            "type_code": self.type_code,
            "type_code_src": None if self.type_code is None else self.type_code_src,
            "model": self.model,
            "model_src": None if self.model is None else self.model_src,
            "manufacture_year": self.manufacture_year,
            "year_src": None if self.manufacture_year is None else self.year_src,
            "operator_name": self.operator_name,
            "operator_src": None if self.operator_name is None else self.operator_src,
            "operator_group_id": group_id,
            "owner": self.owner,
            "owner_src": None if self.owner is None else self.owner_src,
            "updated_ms": UPDATED_MS,
        }

    def classification_row(self) -> dict[str, Any] | None:
        if not self._classification_populated():
            return None
        return {
            "icao24": self.icao24,
            "military": int(self.military),
            "military_src": self.military_src if self.military else None,
            "military_conf": self.military_conf if self.military else None,
            "government": int(self.government),
            "government_src": self.government_src if self.government else None,
            "government_conf": self.government_conf if self.government else None,
            "law_enforcement": int(self.law_enforcement),
            "law_enforcement_src": self.law_enforcement_src if self.law_enforcement else None,
            "law_enforcement_conf": self.law_enforcement_conf if self.law_enforcement else None,
            "mission_category": self.mission_category,
            "mission_src": None if self.mission_category == "unknown" else self.mission_src,
            "mission_conf": None if self.mission_category == "unknown" else self.mission_conf,
            "icon_category": self.icon_category,
            "updated_ms": UPDATED_MS,
        }


async def seed_operator_groups(
    database: Database, groups: Sequence[tuple[str, str]]
) -> dict[str, int]:
    """Insert curated operator groups (idempotently) and return ``slug -> id``."""
    if not groups:
        return {}
    async with database.writer_session() as session:
        for slug, name in groups:
            await session.execute(
                sqlite_insert(OperatorGroup)
                .values(slug=slug, name=name)
                .on_conflict_do_nothing(index_elements=[OperatorGroup.slug])
            )
        rows = (
            await session.execute(
                select(OperatorGroup.id, OperatorGroup.slug).where(
                    OperatorGroup.slug.in_([slug for slug, _ in groups])
                )
            )
        ).all()
    return {slug: int(group_id) for group_id, slug in rows}


async def seed_aircraft(
    database: Database, rows: Sequence[SeedAircraft], *, group_ids: dict[str, int] | None = None
) -> None:
    """Insert every table's rows for ``rows`` in one writer transaction."""
    ids = group_ids or {}
    aircraft_rows = [row.aircraft_row() for row in rows]
    resolved_rows = [resolved for row in rows if (resolved := row.resolved_row(ids)) is not None]
    classification_rows = [
        classification for row in rows if (classification := row.classification_row()) is not None
    ]
    async with database.writer_session() as session:
        await session.execute(insert(Aircraft), aircraft_rows)
        if resolved_rows:
            await session.execute(insert(AircraftMetadataResolved), resolved_rows)
        if classification_rows:
            await session.execute(insert(AircraftClassification), classification_rows)


__all__ = ["SeedAircraft", "seed_aircraft", "seed_operator_groups"]
