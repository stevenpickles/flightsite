"""Request bodies for ``/api/internal/watchlists*`` (``docs/API.md`` §5).

Pydantic validates *shape* here — a body is a JSON object with the right
keys and JSON types, ``kind`` is one of the five recognized strings — exactly
what FastAPI needs to reject a malformed request before it reaches the
service layer. The *content* rules a value must satisfy for its kind — six
hex digits, a plausible tail number, a known mission category — live in
:mod:`flightsite.watchlists.vocabulary` and run inside
:class:`~flightsite.watchlists.service.WatchlistService`, not here, because
they are domain rules the service applies identically whichever caller
reaches it, not a property of the wire format.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flightsite.watchlists.vocabulary import WatchlistEntryKind


class _Model(BaseModel):
    """Base for the request models: no extra keys, no silent coercion."""

    model_config = ConfigDict(extra="forbid")


class WatchlistCreateRequest(_Model):
    """``POST /api/internal/watchlists`` body."""

    name: str = Field(min_length=1)
    description: str | None = None


class WatchlistUpdateRequest(_Model):
    """``PUT /api/internal/watchlists/{id}`` body — full replace, not a patch."""

    name: str = Field(min_length=1)
    description: str | None = None


class WatchlistEntryCreateRequest(_Model):
    """``POST /api/internal/watchlists/{id}/entries`` body."""

    kind: WatchlistEntryKind
    value: str = Field(min_length=1)
    note: str | None = None


__all__ = ["WatchlistCreateRequest", "WatchlistEntryCreateRequest", "WatchlistUpdateRequest"]
