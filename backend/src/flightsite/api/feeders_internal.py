"""Internal feeder stats links: ``/api/internal/feeders/{name}/stats-link``.

A router module of its own, mounted from :mod:`flightsite.api.internal` with a
single ``include_router`` line, for the reason :mod:`flightsite.api.alert_rules`
states: the internal surface is a shared file several slices extend at once.
The mount carries ``include_in_schema=False`` from the app-level inclusion
(ADR-0007, ``docs/API.md`` §5).

Why a redirect
--------------

A per-feeder stats URL names the owner's account on that network — the
FlightAware user and site, the FR24 feeder page, the OpenSky receiver id. The
owner pastes them into ``secrets.yaml`` (``feeders.stats_urls.<name>``) and
they are ``SecretStr`` from then on: never in ``/api/v1``, never in a log line,
never in the rendered page. The Feeders page's "View stats" link points *here*
instead, and the browser learns the real URL only from the ``Location`` header
of this one response, at the moment the owner clicks it. FlightAware's own
``status.json`` names the same page; when no URL is configured for a piaware
feeder, that is used as the fallback, through the same redirect.

``302`` rather than ``301``/``308``: the target is configuration, and a
browser must not cache it past the owner changing it. ``Cache-Control:
no-store`` for the same reason, and ``Referrer-Policy: no-referrer`` so the
network's page is not told which FlightSite URL sent the visitor.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from flightsite.feeders import FeederService

router = APIRouter()

FEEDERS_PATH = "/feeders"


@router.get(f"{FEEDERS_PATH}/{{name}}/stats-link", status_code=status.HTTP_302_FOUND)
async def feeder_stats_link(request: Request, name: str) -> RedirectResponse:
    """Redirect to the feeder's configured stats page; ``404`` when there is none.

    The 404 is deliberately the same for "no such feeder" and "no link for
    this feeder": neither tells a caller anything worth distinguishing, and
    the page only offers the link when ``stats_link`` is ``true``.
    """
    service: FeederService | None = getattr(request.app.state, "feeders", None)
    target = None if service is None else service.stats_url(name)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no stats link for this feeder")
    return RedirectResponse(
        target,
        status_code=status.HTTP_302_FOUND,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


__all__ = ["FEEDERS_PATH", "router"]
