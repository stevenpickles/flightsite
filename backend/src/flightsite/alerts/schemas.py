"""Request bodies for ``/api/internal/alert-rules`` (``docs/API.md`` §5).

The split :mod:`flightsite.watchlists.schemas` draws, drawn the same way:
Pydantic validates *shape* here — a body is a JSON object with the right keys
and JSON types, ``severity`` is one of the four recognized strings — which is
what FastAPI needs to reject a malformed request before it reaches the service.

The condition set is the exception, and deliberately so: it is validated by
:class:`flightsite.alerts.model.RuleConditions` itself, the same model the
stored document is parsed with. A rule submitted over the API and a rule read
back out of ``alert_rules`` therefore pass through one validator, so a
condition set the API accepts is by construction one the engine can evaluate —
which is the round-trip property slice 041's rule builder will be tested
against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flightsite.alerts.model import MAX_DESCRIPTION_LENGTH, MAX_NAME_LENGTH, RuleConditions
from flightsite.alerts.vocabulary import AlertSeverity


class _Model(BaseModel):
    """Base for the request models: no extra keys, no silent coercion."""

    model_config = ConfigDict(extra="forbid")


class AlertRuleWriteRequest(_Model):
    """``POST`` and ``PUT /api/internal/alert-rules`` body.

    One model for both, because ``PUT`` is a full replace rather than a patch
    — the same choice ``PUT /api/internal/watchlists/{id}`` makes, and for a
    stronger reason here: a partial update of an ``AND`` condition set is
    ambiguous about whether an omitted condition was meant to be removed.
    """

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    severity: AlertSeverity
    conditions: RuleConditions
    enabled: bool = True


__all__ = ["AlertRuleWriteRequest"]
