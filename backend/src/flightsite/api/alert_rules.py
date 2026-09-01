"""Internal alert-rule CRUD: ``/api/internal/alert-rules`` and ``/alert-templates``.

A router module of its own, mounted from :mod:`flightsite.api.internal` with a
single ``include_router`` line. That is deliberate and not merely tidy: the
internal surface is a shared file that several slices extend at once, and a
slice that appends a few hundred lines to the end of it collides with every
other slice doing the same. One line in the shared file and everything else
here means this slice's additions and the next one's cannot touch the same
region. The mount keeps ``include_in_schema=False`` from the app-level
inclusion (ADR-0007, ``docs/API.md`` §5), so nothing here reaches the published
OpenAPI document.

Where validation happens, and where it does not
------------------------------------------------

Shape validation is Pydantic's, in :mod:`flightsite.alerts.schemas`, and the
condition set is validated by the very model the stored document is parsed with
(:class:`flightsite.alerts.model.RuleConditions`). So a rule this endpoint
accepts is by construction one the engine can evaluate — including the
threshold bounds and the two "this rule can never match anything" checks (an
empty condition set, an inverted distance or altitude window), which are
validation errors at the moment a rule is written rather than a mystery at the
moment it fails to fire.

*Domain* rules — a blank name, a rule id that does not exist — belong to
:class:`flightsite.alerts.service.AlertService`, which applies them identically
whichever caller reaches it, and they arrive here as
:mod:`flightsite.alerts.errors` exceptions to be mapped onto statuses. The same
split :mod:`flightsite.watchlists` draws.

Every mutation goes through the service, which recompiles the engine's rule set
before returning — so a client that just created a rule sees the live picture
reflect it on its very next read, with no propagation delay to reason about.
That is the same guarantee the watchlist endpoints give, and slice 041's
round-trip test ("rules created in the UI evaluate identically to API-created
rules") rests on it.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request, status

from flightsite.alerts import (
    SHIPPED_TEMPLATES,
    AlertRuleNotFoundError,
    AlertRuleRecord,
    AlertRuleValueError,
    AlertRuleWriteRequest,
    AlertService,
    AlertTemplate,
)
from flightsite.api.serializers import iso_utc
from flightsite.db import from_epoch_ms

router = APIRouter()


def _service(request: Request) -> AlertService:
    service: AlertService = request.app.state.alerts
    return service


def _rule_payload(record: AlertRuleRecord) -> dict[str, Any]:
    """One rule as the Alerts page's list/detail row (``docs/API.md`` §5).

    ``conditions`` is echoed as the validated document rather than as the
    stored text, so a client always reads the same shape it would have to send
    back — and ``describes`` beside it is the rule stated in prose, which is
    what a list row shows under the name without every client re-implementing
    :meth:`~flightsite.alerts.model.RuleConditions.describe`.
    """
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "severity": record.severity.value,
        "enabled": record.enabled,
        "template_key": record.template_key,
        "conditions": record.conditions.model_dump(mode="json", exclude_none=True),
        "describes": list(record.conditions.describe()),
        "created_at": iso_utc(from_epoch_ms(record.created_ms)),
        "updated_at": iso_utc(from_epoch_ms(record.updated_ms)),
    }


def _template_payload(template: AlertTemplate) -> dict[str, Any]:
    """One shipped template, as the template gallery reads it (SPEC §45).

    ``builtin`` is the field that matters: a built-in template describes
    behaviour that is already on and cannot be turned off (SPEC §47's emergency
    squawks), so a gallery must render it as a statement rather than as a
    switch. Its ``conditions`` are ``null`` because there is no rule to create.
    """
    conditions = template.conditions
    return {
        "key": template.key,
        "name": template.name,
        "description": template.description,
        "severity": template.severity.value,
        "builtin": template.builtin,
        "conditions": (
            None if conditions is None else conditions.model_dump(mode="json", exclude_none=True)
        ),
    }


@router.get("/alert-templates")
async def list_alert_templates() -> dict[str, Any]:
    """Every shipped template this build knows (SPEC §45, ``docs/API.md`` §5).

    Static data — the catalogue is code, not a table — so this takes no
    database at all. What a user has *enabled* is
    ``alerts.enabled_templates`` in the configuration, read through
    ``GET /api/internal/config``; what has been *instantiated* is the rule list
    below, where a shipped rule carries its ``template_key``.
    """
    return {"templates": [_template_payload(template) for template in SHIPPED_TEMPLATES]}


@router.get("/alert-rules")
async def list_alert_rules(request: Request) -> dict[str, Any]:
    """Every alert rule, by id."""
    rules = await _service(request).list_rules()
    return {"rules": [_rule_payload(rule) for rule in rules]}


@router.post("/alert-rules", status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    request: Request, body: Annotated[AlertRuleWriteRequest, Body()]
) -> dict[str, Any]:
    """Create a rule. The engine's rule set is recompiled before this returns."""
    try:
        record = await _service(request).create_rule(
            name=body.name,
            description=body.description,
            severity=body.severity,
            conditions=body.conditions,
            enabled=body.enabled,
        )
    except AlertRuleValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _rule_payload(record)


@router.put("/alert-rules/{rule_id}")
async def update_alert_rule(
    request: Request, rule_id: int, body: Annotated[AlertRuleWriteRequest, Body()]
) -> dict[str, Any]:
    """Replace a rule's definition. A full replace, not a patch.

    ``template_key`` is not replaceable: provenance is a statement about where
    a rule came from, and tuning a shipped rule does not make it stop having
    been shipped.
    """
    try:
        record = await _service(request).update_rule(
            rule_id,
            name=body.name,
            description=body.description,
            severity=body.severity,
            conditions=body.conditions,
            enabled=body.enabled,
        )
    except AlertRuleValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _rule_payload(record)


@router.delete("/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(request: Request, rule_id: int) -> None:
    """Delete a rule and the matches it produced.

    The matches go with it because ``alert_matches.rule_id`` has no
    ``ON DELETE`` action (``docs/DATA_MODEL.md`` §4.3) and foreign keys are
    enforced (ADR-0001). Less is lost than that suggests: the sightings keep
    their ``max_alert_severity`` and their ``alert_matched`` events, and the
    activity feed keeps every ``alert_triggered`` row with the rule's name and
    the reason it gave.
    """
    if not await _service(request).delete_rule(rule_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no alert rule with id {rule_id}")
