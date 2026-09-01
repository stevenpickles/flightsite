"""One place where API payloads are assembled from application state.

``GET /api/v1/aircraft/current`` and the WebSocket's ``snapshot`` frame must
describe the same instant identically — roadmap slice 010's first acceptance
criterion — and the cheapest way to guarantee that is to give them one
implementation rather than two that agree by inspection. Both call
:meth:`LiveApiContext.aircraft`; the same is true of the receiver block, which
appears in ``GET /api/v1/receiver`` and in every snapshot.

The context reads ``app.state`` lazily on every call rather than capturing its
contents at construction. That is not indirection for its own sake: ``PUT
/api/internal/config`` replaces ``app.state.settings`` on a running app, so a
captured ``Settings`` would serve a stale receiver block for the rest of the
process's life. Reading late also means the context can be built before the
lifespan hook has started anything.

Nothing here touches SQLite on the aircraft path — the live registry answers
from memory and so does the metadata cache, which is the invariant
``docs/ARCHITECTURE.md`` §3.1 states as "no live request or decoder poll ever
waits on SQLite" and §3.3 restates as "metadata joins and rarity checks hit a
cache, not the database". The one database read in this module is T0 for the
receiver block, which is a single indexed lookup on a write-once key, made on a
REST request or a WebSocket connect and never per frame.

An aircraft the cache has not resolved yet serializes with ``null`` metadata
rather than waiting for it. That is the deliberate trade of ``docs/API.md``
§2.7: metadata is enrichment, a live aircraft is fully usable without it, and a
frame that blocked on a lookup would trade the live picture's latency for a
field that will arrive a fraction of a second later anyway.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import structlog
from fastapi import FastAPI

from flightsite.api.history import AircraftHistoryRepository
from flightsite.api.serializers import (
    aircraft_detail_payload,
    aircraft_history_row_payload,
    aircraft_payload,
    receiver_payload,
)
from flightsite.config import Settings
from flightsite.db import Database, MetaRepository, from_epoch_ms
from flightsite.live import LiveAircraft, LiveStore
from flightsite.metadata import MetadataCache, MetadataService
from flightsite.sightings import PersistenceWorker

logger = structlog.get_logger(__name__)


def _wanted(record: LiveAircraft, positioned: bool | None) -> bool:
    """Apply the §3.3 ``positioned`` filter; ``None`` means "everything"."""
    return positioned is None or record.has_position is positioned


class LiveApiContext:
    """Assembles the live API payloads from a running app's state.

    Args:
        app: the application whose ``state`` holds the live registry, the
            persistence worker, the database and the effective settings.
    """

    __slots__ = ("_app",)

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    # ----------------------------------------------------------------- state

    @property
    def live(self) -> LiveStore:
        """The in-memory live aircraft registry."""
        store: LiveStore = self._app.state.live
        return store

    @property
    def settings(self) -> Settings:
        """The currently effective configuration."""
        settings: Settings = self._app.state.settings
        return settings

    @property
    def demo_mode(self) -> bool:
        """True when this process serves simulated traffic (SPEC §76)."""
        demo: bool = self._app.state.demo_enabled
        return demo

    @property
    def metadata(self) -> MetadataCache:
        """The in-memory metadata, rarity and classification cache.

        Read on the aircraft path, which is why it is the *cache* and not the
        service: :meth:`~flightsite.metadata.cache.MetadataCache.get` is a dict
        lookup with no ``await`` and no session, so the invariant this module's
        docstring states — nothing here touches SQLite on the aircraft path —
        survives metadata joining the payload.
        """
        service: MetadataService = self._app.state.metadata
        return service.cache

    # -------------------------------------------------------------- payloads

    def aircraft(self, *, positioned: bool | None = None) -> list[dict[str, Any]]:
        """The live set as §3.3 aircraft objects, ordered by ICAO address.

        Sorted so that two reads of the same instant — one over REST, one over
        the WebSocket — are identical documents rather than merely equal sets.
        Sorting a few hundred already-interned strings costs far less than the
        serialization it accompanies.

        Args:
            positioned: ``True`` for aircraft with a known position, ``False``
                for those tracked without one (SPEC §20), ``None`` for the full
                live picture, which is the default and the documented one.
        """
        worker: PersistenceWorker = self._app.state.persistence
        cache = self.metadata
        records = sorted(self.live.snapshot(), key=lambda record: record.icao)
        return [
            aircraft_payload(
                record,
                sighting_id=worker.sighting_id_for(record.icao),
                metadata=cache.get(record.icao),
            )
            for record in records
            if _wanted(record, positioned)
        ]

    def aircraft_for(self, icaos: Iterable[str]) -> list[dict[str, Any]]:
        """Serialize the named aircraft, in the order given, skipping absentees.

        Used to build a delta's ``updated`` list from the ICAOs one tick's
        events named. The payload is read from the live store *now* rather than
        from the records the events carried, so a burst of updates for one
        aircraft costs one serialization of its latest state instead of several
        of its intermediate ones. An ICAO that left the live set between the
        event and this call is simply absent — the same tick's ``removed`` list
        is the notice that matters.
        """
        worker: PersistenceWorker = self._app.state.persistence
        live = self.live
        cache = self.metadata
        payloads: list[dict[str, Any]] = []
        for icao in icaos:
            record = live.get(icao)
            if record is not None:
                payloads.append(
                    aircraft_payload(
                        record,
                        sighting_id=worker.sighting_id_for(icao),
                        metadata=cache.get(icao),
                    )
                )
        return payloads

    @property
    def history(self) -> AircraftHistoryRepository:
        """The Aircraft page's query layer, built from the running database."""
        database: Database = self._app.state.database
        return AircraftHistoryRepository(database)

    async def aircraft_history(
        self,
        *,
        limit: int,
        offset: int,
        sort: str,
        order: str,
        classification: str | None = None,
        operator_group: str | None = None,
        type_code: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of the Aircraft page's list, serialized — §3.5."""
        rows, total = await self.history.list_aircraft(
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            classification=classification,
            operator_group=operator_group,
            type_code=type_code,
        )
        return [aircraft_history_row_payload(row) for row in rows], total

    async def aircraft_detail(self, icao24: str) -> dict[str, Any] | None:
        """One airframe's full detail, or ``None`` if never sighted — §3.5.

        ``live`` reads the live registry at the moment of the request rather
        than anything the history query touched: the two are different data
        sources answering the same instant, exactly as
        :meth:`aircraft` and the WebSocket snapshot do.
        """
        row = await self.history.get_aircraft(icao24)
        if row is None:
            return None
        return aircraft_detail_payload(row, live=self.live.get(icao24) is not None)

    async def receiver(self) -> dict[str, Any]:
        """The §3.2 receiver info block, including T0.

        The location comes from the live store rather than from settings: it
        is the position distances and bearings are actually measured from, so
        it is the one a client should draw its receiver marker and range rings
        at. They differ only in demo mode, which injects a location into an
        otherwise unconfigured install.
        """
        return receiver_payload(
            self.settings,
            demo_mode=self.demo_mode,
            t0=await self._t0(),
            location=self.live.receiver_location,
        )

    async def _t0(self) -> datetime | None:
        """T0 as an aware UTC datetime, or ``None`` if it is unavailable.

        A database that failed to migrate leaves ``/api/v1/ready`` answering
        503 but must not take the receiver block down with it: the rest of that
        payload is pure configuration, and the live picture behind it is fine.
        An unreadable T0 is therefore reported as "unknown" (§2.7) rather than
        as a 500, with the reason logged once per read.
        """
        database: Database = self._app.state.database
        try:
            t0_ms = await MetaRepository(database).get_t0()
        except Exception as exc:
            logger.warning("t0_unavailable", error=str(exc), error_type=type(exc).__name__)
            return None
        return None if t0_ms is None else from_epoch_ms(t0_ms)


__all__ = ["LiveApiContext"]
