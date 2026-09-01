"""The historical Aircraft page's queries — ``docs/API.md`` §3.5, SPEC §53/§56.

Unlike the live path (:mod:`flightsite.api.context`), this module reads
SQLite directly and on the request path: the Aircraft page is a paginated,
sortable view over ``aircraft`` joined to the resolved metadata and
classification tables, and there is no in-memory structure that could answer
"every aircraft this receiver has ever seen, sorted by closest approach"
without a query. Every read goes through
:meth:`~flightsite.db.engine.Database.read_session` (ADR-0001), so it can
never become a second writer and never blocks the persistence worker.

One query shape, two callers
-----------------------------

:func:`_joined_query` is the single ``SELECT`` both the list and the detail
endpoint build on: ``aircraft`` LEFT JOINed to
``aircraft_metadata_resolved`` (identity/metadata), ``operator_groups``
(the resolved operator's curated group name) and ``aircraft_classification``
(SPEC §39). ``aircraft`` is the driving table — a row here is exactly "this
receiver has heard this airframe at least once" (SPEC §53), which is what
makes the Aircraft page a *receiver history* rather than a dump of every
airframe the metadata database happens to know about. The two joined tables
cover the whole metadata database and may have no matching row for a given
address (a freshly-seen airframe with no metadata import yet, or one no
source has ever heard of); LEFT JOIN is what keeps such a row on the page
with ``null`` fields rather than dropping it (§2.7).

Sorting and pagination
-----------------------

§2.4 offset pagination over a documented column set (§3.5). Every sort adds
``icao24`` ascending as a final tiebreaker: SQLite's plan for a tied sort key
is not guaranteed stable across two reads with different ``LIMIT``/``OFFSET``
values, and an unstable tiebreak would let the same row appear on two pages
or vanish from both.

Total is computed, not omitted
-------------------------------

§2.4 allows ``/aircraft`` to omit or approximate ``total`` because an exact
filtered count can be too expensive at multi-year scale. The Aircraft page's
own table is bounded by *unique airframes ever heard*, not by sighting
volume — it grows by one row per new aircraft, not per sighting — so even
years of history keep it in the thousands, not the millions that make
``/sightings``' count expensive. One ``COUNT(*)`` over the same filtered
join is cheap at that scale, so it is computed exactly rather than omitted;
:mod:`tests.api.test_aircraft_history_perf` is the sanity check that this
premise still holds against a several-thousand-row fixture.

Existing indexes only
----------------------

No migration ships with this slice. ``ix_aircraft_first_seen``,
``ix_aircraft_last_seen`` and ``ix_aircraft_sightings`` (``docs/DATA_MODEL.md``
§2.2) cover three of the ten documented sort keys directly; the rest —
notably ``closest_approach_nm`` and ``max_range_nm``, which carry no index —
fall back to SQLite sorting the filtered result set in memory. That is an
acceptable cost at the row counts this table reaches (see above), which the
perf test measures rather than assumes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.engine import RowMapping

from flightsite.db import Database
from flightsite.db.models import (
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    OperatorGroup,
)

#: §3.5's documented sort keys, mapped to the column each one orders by.
#: Typed ``Any`` rather than ``ColumnElement[Any]``: a mapped class's
#: attributes are ``InstrumentedAttribute``, which behaves as a column
#: everywhere SQLAlchemy Core accepts one but is not itself a
#: ``ColumnElement`` subtype mypy will unify a mixed collection of them into.
SORT_COLUMNS: Final[Mapping[str, Any]] = {
    "registration": AircraftMetadataResolved.registration,
    "icao": Aircraft.icao24,
    "type": AircraftMetadataResolved.type_code,
    "operator": AircraftMetadataResolved.operator_name,
    "classification": AircraftClassification.mission_category,
    "first_seen": Aircraft.first_seen_ms,
    "last_seen": Aircraft.last_seen_ms,
    "sighting_count": Aircraft.sighting_count,
    "closest_approach_nm": Aircraft.closest_approach_nm,
    "max_range_nm": Aircraft.max_range_nm,
}

#: §3.5's documented default. Typed as the same literal
#: :data:`~flightsite.api.schemas.AircraftSortKey` / ``SortOrder`` values
#: rather than plain ``str`` so it type-checks directly as a default for
#: those query parameters.
DEFAULT_SORT: Final[Literal["last_seen"]] = "last_seen"
DEFAULT_ORDER: Final[Literal["desc"]] = "desc"

#: Every column either payload (list row or detail) needs. Selected once so
#: the list and detail queries can never drift into reading a different
#: shape of row than their shared serializers expect.
_COLUMNS: Final[tuple[Any, ...]] = (
    Aircraft.icao24,
    Aircraft.first_seen_ms,
    Aircraft.last_seen_ms,
    Aircraft.sighting_count,
    Aircraft.total_observed_ms,
    Aircraft.closest_approach_nm,
    Aircraft.max_range_nm,
    Aircraft.lowest_alt_ft,
    Aircraft.highest_alt_ft,
    AircraftMetadataResolved.registration,
    AircraftMetadataResolved.registration_src,
    AircraftMetadataResolved.type_code,
    AircraftMetadataResolved.type_code_src,
    AircraftMetadataResolved.model,
    AircraftMetadataResolved.model_src,
    AircraftMetadataResolved.manufacture_year,
    AircraftMetadataResolved.year_src,
    AircraftMetadataResolved.operator_name,
    AircraftMetadataResolved.operator_src,
    AircraftMetadataResolved.owner,
    AircraftMetadataResolved.owner_src,
    OperatorGroup.name.label("operator_group"),
    OperatorGroup.slug.label("operator_group_slug"),
    AircraftClassification.military,
    AircraftClassification.military_src,
    AircraftClassification.military_conf,
    AircraftClassification.government,
    AircraftClassification.government_src,
    AircraftClassification.government_conf,
    AircraftClassification.law_enforcement,
    AircraftClassification.law_enforcement_src,
    AircraftClassification.law_enforcement_conf,
    AircraftClassification.mission_category,
    AircraftClassification.mission_src,
    AircraftClassification.mission_conf,
    AircraftClassification.icon_category,
)


def _joined_query() -> Select[Any]:
    """The shared ``aircraft`` → resolved metadata → classification join.

    ``aircraft`` drives the join (see the module docstring); the other two
    are LEFT JOINed so an airframe with no resolved metadata or no
    classification row still appears, with ``null`` fields, rather than being
    silently dropped from a receiver's own history.
    """
    return (
        select(*_COLUMNS)
        .select_from(Aircraft)
        .outerjoin(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
        .outerjoin(OperatorGroup, OperatorGroup.id == AircraftMetadataResolved.operator_group_id)
        .outerjoin(AircraftClassification, AircraftClassification.icao24 == Aircraft.icao24)
    )


def _filters(
    *,
    classification: str | None,
    operator_group: str | None,
    type_code: str | None,
) -> list[ColumnElement[bool]]:
    """§3.5's documented filters as SQL predicates.

    ``classification`` matches ``mission_category`` exactly — the same
    column the ``classification`` sort key orders by, so a filtered,
    sorted column is one consistent notion of "classification" rather than
    two. ``operator_group`` matches the curated group's *slug* (the stable,
    URL-safe identifier — ``docs/DATA_MODEL.md`` §3.5), not its display name.
    ``type`` matches the resolved ICAO type designator, normalized to
    upper case the way every stored one is.
    """
    conditions: list[ColumnElement[bool]] = []
    if classification is not None:
        conditions.append(AircraftClassification.mission_category == classification)
    if operator_group is not None:
        conditions.append(OperatorGroup.slug == operator_group)
    if type_code is not None:
        conditions.append(AircraftMetadataResolved.type_code == type_code.upper())
    return conditions


class AircraftHistoryRepository:
    """Reads the Aircraft page's list and detail queries through the database."""

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_aircraft(
        self,
        *,
        limit: int,
        offset: int,
        sort: str = DEFAULT_SORT,
        order: str = DEFAULT_ORDER,
        classification: str | None = None,
        operator_group: str | None = None,
        type_code: str | None = None,
    ) -> tuple[Sequence[RowMapping], int]:
        """One page of the historical aircraft list, plus the filtered total.

        Args:
            sort: one of :data:`SORT_COLUMNS`'s keys — validated by the
                caller (the endpoint's ``Literal`` query parameter), so an
                unrecognized key here would be a programming error, not user
                input; :exc:`KeyError` is deliberately not caught.
            order: ``"asc"`` or ``"desc"``.
        """
        conditions = _filters(
            classification=classification, operator_group=operator_group, type_code=type_code
        )
        column = SORT_COLUMNS[sort]
        direction = column.asc() if order == "asc" else column.desc()

        filtered = _joined_query().where(*conditions) if conditions else _joined_query()
        query = filtered.order_by(direction, Aircraft.icao24.asc()).limit(limit).offset(offset)
        # Counted from the same filtered join as a subquery, rather than a
        # bare `SELECT count(*) FROM aircraft`, so a filtered count always
        # agrees with what the filtered page actually contains.
        count_query = select(func.count()).select_from(filtered.subquery())

        async with self._database.read_session() as session:
            rows = (await session.execute(query)).mappings().all()
            total = await session.scalar(count_query)
        return rows, int(total or 0)

    async def get_aircraft(self, icao24: str) -> RowMapping | None:
        """The joined row for one airframe, or ``None`` if never sighted."""
        query = _joined_query().where(Aircraft.icao24 == icao24)
        async with self._database.read_session() as session:
            return (await session.execute(query)).mappings().first()


__all__ = [
    "DEFAULT_ORDER",
    "DEFAULT_SORT",
    "SORT_COLUMNS",
    "AircraftHistoryRepository",
]
