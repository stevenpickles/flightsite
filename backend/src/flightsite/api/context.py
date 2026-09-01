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
from memory, which is the invariant ``docs/ARCHITECTURE.md`` §3.1 states as
"no live request or decoder poll ever waits on SQLite". The one database read
in this module is T0 for the receiver block, which is a single indexed lookup
on a write-once key, made on a REST request or a WebSocket connect and never
per frame.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import structlog
from fastapi import FastAPI

from flightsite.api.serializers import aircraft_payload, receiver_payload
from flightsite.config import Settings
from flightsite.db import Database, MetaRepository, from_epoch_ms
from flightsite.live import LiveAircraft, LiveStore
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
        records = sorted(self.live.snapshot(), key=lambda record: record.icao)
        return [
            aircraft_payload(record, sighting_id=worker.sighting_id_for(record.icao))
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
        payloads: list[dict[str, Any]] = []
        for icao in icaos:
            record = live.get(icao)
            if record is not None:
                payloads.append(aircraft_payload(record, sighting_id=worker.sighting_id_for(icao)))
        return payloads

    async def receiver(self) -> dict[str, Any]:
        """The §3.2 receiver info block, including T0."""
        return receiver_payload(self.settings, demo_mode=self.demo_mode, t0=await self._t0())

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
