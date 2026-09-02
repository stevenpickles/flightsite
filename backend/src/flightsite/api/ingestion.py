"""Starting decoder ingestion: at boot, and on the save that first configures it.

Two callers, one implementation:

* :func:`flightsite.app._start_ingestion`, once, from the lifespan hook;
* :func:`flightsite.api.internal._apply_live_settings`, when ``PUT
  /api/internal/config`` writes the configuration a first-run install did not
  have.

Why the second caller exists (issue #122)
-----------------------------------------

A first-run install starts no ingestion — there is no ``config.yaml``, so
there is no receiver the user has actually chosen, and polling model defaults
would report a decoder ``down`` before the setup wizard had even been opened.
That guard was right, but it was permanent: ``app.state.ingestion`` stayed
``None`` for the life of the process, so the very save that ended the
first-run state changed nothing until someone restarted the backend. A user
who completed the wizard watched an empty map and was told, correctly but
uselessly, that their install was working.

So the save that ends the first-run state now starts ingestion against the
receiver it just wrote — which is exactly what the *next* boot would have
done with the same file. That equivalence is the point, and it is why this
module builds the endpoint from ``app.state.settings`` rather than from the
request body: hot-start and cold-start must not be two ways to decide what to
poll.

Hot-**start** only
------------------

Nothing → running. This module never restarts, reconfigures or replaces a
service that is already running, and :func:`ingestion_startable` refuses to
even build a second one. Changing the endpoint of a *running* adapter is a
different problem — an in-flight poll, a health history and a readiness
registration all belong to the old endpoint — and it stays restart-required,
which is what the Settings UI's decoder and receiver sections say on their
badges. The narrow case fixed here is the one where there is nothing running
to disturb.

Mid-life readiness registration is safe
---------------------------------------

:meth:`~flightsite.ingest.service.IngestionService.start` registers the
``ingestion`` subsystem and marks it ready, and on this path that happens
*after* ``mark_startup_complete()``. It cannot make ``/api/v1/ready`` flap:
:meth:`~flightsite.readiness.ReadinessRegistry.register` seeds the subsystem
not-ready, but the ``mark_ready`` that follows it runs in the same synchronous
block with no ``await`` between the two, and the ``/ready`` handler is a
coroutine on the same event loop — so no request can be served in the window
where the new subsystem is registered but not yet ready. The registry's own
lock keeps the pair atomic for any non-``asyncio`` reader.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from flightsite.config import ConfigStore, Settings
from flightsite.ingest import DecoderEndpoint, IngestionService, build_ingestion_service
from flightsite.live import LiveStore

logger = structlog.get_logger(__name__)


def decoder_endpoint(settings: Settings) -> DecoderEndpoint:
    """Translate the receiver section of settings into an ingestion endpoint."""
    receiver = settings.receiver
    return DecoderEndpoint(
        host=receiver.host,
        port=receiver.port,
        path=receiver.path,
        poll_interval_s=receiver.poll_interval_s,
    )


def ingestion_startable(app: FastAPI) -> bool:
    """True when there is nothing ingesting and a saved configuration to ingest from.

    Three conditions, and all three are about *this* process's state rather
    than about what changed in the request:

    * nothing is running. A service that already exists owns the adapter, the
      task and the readiness registration; this module never displaces one.
      This is also what makes a second save a no-op rather than a second
      service — ``IngestionService.start`` is idempotent, but the guard is
      here so a redundant service is never constructed to begin with.
    * not demo mode. Demo ingestion is started unconditionally at boot from
      :class:`~flightsite.demo.DemoAdapter` and has no endpoint to configure;
      a config save must not swap simulated traffic for a real decoder poll
      under a user who set ``FLIGHTSITE_DEMO=1``.
    * the install is no longer on its first run, i.e. ``config.yaml`` now
      exists. That is the same condition the boot path tests, and it is what
      "the user has chosen a receiver" actually means: the receiver section is
      always complete after validation (its fields carry model defaults), so
      the fact worth testing is whether a configuration was ever saved, not
      whether the endpoint differs from the defaults.
    """
    if getattr(app.state, "ingestion", None) is not None:
        return False
    if app.state.demo_enabled:
        return False
    store: ConfigStore = app.state.config_store
    return not store.first_run


async def start_decoder_ingestion(app: FastAPI) -> IngestionService:
    """Build, start and install the decoder ingestion service.

    The live store is the sole consumer: every normalized batch goes straight
    into the in-memory registry, and nothing on this path touches the database
    (``docs/ARCHITECTURE.md`` §3.1).

    ``app.state.ingestion`` is assigned here, last, so that a failed
    ``start()`` leaves it ``None`` and a later save can try again — and so
    that there is one place that decides what "ingestion is now running" means
    for application state. Both readers pick the assignment up with no further
    wiring: :func:`flightsite.app._decoder_health` reads it lazily on every
    probe, and the lifespan hook's shutdown reads it when it stops.
    """
    live: LiveStore = app.state.live
    service = build_ingestion_service(
        decoder_endpoint(app.state.settings),
        readiness=app.state.readiness,
        consumers=(live.apply,),
    )
    await service.start()
    app.state.ingestion = service
    return service


__all__ = ["decoder_endpoint", "ingestion_startable", "start_decoder_ingestion"]
