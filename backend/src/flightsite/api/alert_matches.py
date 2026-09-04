"""Internal alert-match delivery state: ``/api/internal/alerts/matches``.

A router module of its own, mounted from :mod:`flightsite.api.internal` with a
single ``include_router`` line, for the reason
:mod:`flightsite.api.alert_rules` states: the internal surface is a shared file
several slices extend at once, so each new group gets its own module and the
shared file gets one line. The mount carries ``include_in_schema=False`` from
the app-level inclusion (ADR-0007, ``docs/API.md`` §5), so nothing here reaches
the published OpenAPI document.

Why the *client* writes this
----------------------------

``alert_matches.notified`` is the one field on a match that is not a fact about
the match. It means *"at least one FlightSite client actually showed a browser
``Notification`` for this"* — and the server is in no position to say so. What
the backend knows is that it put an ``activity_batch`` frame on a socket
(``docs/API.md`` §4.4); whether that became a notification depends on the
browser's permission state, on the user's per-severity preferences, and on
whether the tab had already shown that event. Setting the flag on broadcast
would make it a second, worse name for "an alert was recorded", which
``GET /api/v1/alerts/matches`` already reports in full.

So the write is a client assertion, made once, immediately after
``new Notification(...)`` returned — see
``frontend/src/features/notifications/lib/dispatch.ts``. It is fire-and-forget
there: a marker that failed to reach the database must never delay or undo a
notification the user has already seen.

Idempotence is the endpoint's, not the caller's. Two tabs open on one receiver
both deliver the same match, and both post; the second is a no-op success
rather than a conflict, because "someone was notified" does not become more
true or less true the second time it is asserted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from flightsite.alerts import AlertService

router = APIRouter()

MATCHES_PATH = "/alerts/matches"


def _service(request: Request) -> AlertService:
    service: AlertService = request.app.state.alerts
    return service


@router.post(f"{MATCHES_PATH}/{{match_id}}/notified", status_code=status.HTTP_204_NO_CONTENT)
async def mark_alert_match_notified(request: Request, match_id: int) -> None:
    """Record that a browser notification was shown for this match (issue #104).

    ``POST`` to the match's ``notified`` sub-resource rather than a ``PATCH``
    of the match itself: there is exactly one transition, it only ever runs one
    way, and the body is empty because the assertion *is* the request. A client
    cannot un-notify a match, and nothing here accepts a value to set.

    Statuses: ``204`` whether this call marked the row or found it already
    marked — the transition is idempotent, so a repeat is a success with
    nothing to say — and ``404`` for a match id this install has no row for,
    which is the one answer a client could act on.
    """
    if not await _service(request).mark_match_notified(match_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no alert match with id {match_id}")
