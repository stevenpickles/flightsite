"""The HTTP and WebSocket surface: routers, payload shapes, live broadcaster.

Four supporting modules, split by what changes for what reason:

* :mod:`flightsite.api.serializers` — domain records to the JSON shapes
  ``docs/API.md`` documents. Pure functions, no application state.
* :mod:`flightsite.api.schemas` — the Pydantic models those shapes are
  published and validated as, which is what ``/api/v1/openapi.json`` describes.
* :mod:`flightsite.api.context` — assembles payloads from a running app's
  state, so REST and the WebSocket answer from one implementation.
* :mod:`flightsite.api.ws` — the live WebSocket protocol and its broadcaster.

:mod:`flightsite.api.v1` mounts the documented read-only surface;
:mod:`flightsite.api.internal` mounts the unsupported mutation surface, which
is excluded from the published schema (ADR-0007).
"""

from __future__ import annotations
