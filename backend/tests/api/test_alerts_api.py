"""The alert API surfaces: the §3.3 block, §3.4, §3.9, and internal rule CRUD.

Three surfaces, and each has one property worth stating:

* **The ``interesting`` block** is carried by the *same* serializer the live
  picture and the WebSocket already share, so it cannot appear on one and not
  the other. The agreement test lives beside the others in
  ``tests/api/test_rest_ws_agreement.py``; what is checked here is the block's
  shape and its ``null``-when-nothing-matches contract.
* **The read endpoints** are the shapes ``docs/API.md`` publishes, validated
  against the response models FastAPI serves them under.
* **Rule CRUD** validates through the same model the stored document is parsed
  with, which is what makes "a rule the API accepts is a rule the engine can
  evaluate" true by construction rather than by inspection.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from flightsite.alerts import AlertService, AlertSeverity
from flightsite.alerts.model import RuleConditions
from flightsite.app import create_app
from flightsite.ingest import AircraftStateUpdate, Position

from .conftest import LiveApp

RULES_PATH = "/api/internal/alert-rules"
TEMPLATES_PATH = "/api/internal/alert-templates"
INTERESTING_PATH = "/api/v1/aircraft/interesting"
MATCHES_PATH = "/api/v1/alerts/matches"

MILITARY_BODY: dict[str, Any] = {
    "name": "Military aircraft",
    "description": "Anything military",
    "severity": "high",
    "conditions": {"version": 1, "classification": {"military": True}},
}


@pytest.fixture
def client(isolated_data_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(isolated_data_dir)) as test_client:
        yield test_client


def _create(client: TestClient, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post(RULES_PATH, json=body if body is not None else MILITARY_BODY)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# ------------------------------------------------------------------ templates


def test_the_template_catalogue_is_served(client: TestClient) -> None:
    response = client.get(TEMPLATES_PATH)

    assert response.status_code == 200
    templates = response.json()["templates"]
    assert [template["key"] for template in templates] == [
        "military",
        "government",
        "police",
        "emergency_squawk",
        "first_ever",
        "locally_rare",
        "locally_rare_type",
        "watchlist",
    ]


def test_the_emergency_template_is_reported_as_built_in_with_no_conditions(
    client: TestClient,
) -> None:
    """A gallery must render it as a statement rather than as a switch: SPEC
    §47 makes it always on and unconfigurable."""
    templates = client.get(TEMPLATES_PATH).json()["templates"]
    emergency = next(template for template in templates if template["key"] == "emergency_squawk")

    assert emergency["builtin"] is True
    assert emergency["conditions"] is None
    assert emergency["severity"] == "critical"


def test_every_other_template_reports_the_conditions_it_would_create(
    client: TestClient,
) -> None:
    templates = client.get(TEMPLATES_PATH).json()["templates"]

    for template in templates:
        if not template["builtin"]:
            assert isinstance(template["conditions"], dict)
            assert template["conditions"]["version"] == 1


# ------------------------------------------------------- template instantiation


def test_instantiating_a_template_creates_a_rule_carrying_its_provenance(
    client: TestClient,
) -> None:
    response = client.post(f"{TEMPLATES_PATH}/military/rules")

    assert response.status_code == 201, response.text
    rule = response.json()
    assert rule["template_key"] == "military"
    assert rule["name"] == "Military aircraft"
    assert rule["severity"] == "high"
    assert rule["enabled"] is True
    assert rule["describes"] == ["military"]
    assert client.get(RULES_PATH).json()["rules"] == [rule]


def test_an_instantiated_template_says_exactly_what_the_gallery_showed(
    client: TestClient,
) -> None:
    """The gallery's preview and the rule it creates are one document.

    Slice 041's gallery renders ``GET /alert-templates``'s ``conditions``; this
    pins that the rule the ``POST`` creates carries that same document rather
    than a re-derivation of it.
    """
    templates = client.get(TEMPLATES_PATH).json()["templates"]

    for template in templates:
        if template["builtin"]:
            continue
        rule = client.post(f"{TEMPLATES_PATH}/{template['key']}/rules").json()
        assert rule["conditions"] == template["conditions"]
        assert rule["severity"] == template["severity"]
        assert rule["name"] == template["name"]


def test_instantiating_a_template_twice_is_refused(client: TestClient) -> None:
    assert client.post(f"{TEMPLATES_PATH}/military/rules").status_code == 201

    response = client.post(f"{TEMPLATES_PATH}/military/rules")

    assert response.status_code == 409
    assert len(client.get(RULES_PATH).json()["rules"]) == 1


def test_instantiating_the_built_in_emergency_template_is_refused(
    client: TestClient,
) -> None:
    """SPEC §47: emergency alerting is already on and has no rule to create."""
    response = client.post(f"{TEMPLATES_PATH}/emergency_squawk/rules")

    assert response.status_code == 409
    assert client.get(RULES_PATH).json()["rules"] == []


def test_instantiating_an_unknown_template_answers_404(client: TestClient) -> None:
    response = client.post(f"{TEMPLATES_PATH}/no_such_template/rules")

    assert response.status_code == 404


def test_a_deleted_template_rule_can_be_instantiated_again(client: TestClient) -> None:
    """Deleting a shipped rule is not a permanent ban on the template.

    Start-up instantiation deliberately never re-creates a deleted shipped rule
    (:mod:`flightsite.alerts.templates`); an explicit request from the gallery
    is the user asking for it back, which is a different act.
    """
    rule = client.post(f"{TEMPLATES_PATH}/military/rules").json()
    assert client.delete(f"{RULES_PATH}/{rule['id']}").status_code == 204

    response = client.post(f"{TEMPLATES_PATH}/military/rules")

    assert response.status_code == 201
    assert response.json()["template_key"] == "military"


def test_a_template_rule_keeps_its_provenance_when_customized(
    client: TestClient,
) -> None:
    """SPEC §45's "enable, then customize": tuning does not erase where it came from."""
    rule = client.post(f"{TEMPLATES_PATH}/locally_rare/rules").json()

    response = client.put(
        f"{RULES_PATH}/{rule['id']}",
        json={
            "name": "Rare here",
            "description": None,
            "severity": "high",
            "conditions": {"version": 1, "rare_aircraft": {"max_sightings": 5}},
            "enabled": False,
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["template_key"] == "locally_rare"
    assert updated["severity"] == "high"
    assert updated["enabled"] is False
    assert updated["conditions"]["rare_aircraft"] == {"max_sightings": 5}


def test_an_instantiated_rule_is_in_force_for_the_next_live_read(
    client: TestClient,
) -> None:
    """The gallery's "enable" recompiles the engine, like every other mutation."""
    client.post(f"{TEMPLATES_PATH}/watchlist/rules")

    rules = client.get(RULES_PATH).json()["rules"]

    assert [rule["template_key"] for rule in rules] == ["watchlist"]
    assert client.get(INTERESTING_PATH).status_code == 200


# ------------------------------------------------------- rule-builder round trip


#: The condition documents slice 041's visual rule builder composes, one per
#: kind it offers, exactly as ``conditionsToDocument`` emits them —
#: ``frontend/src/features/alerts/lib/conditions.ts``, whose own tests pin the
#: same shapes from the other side. Together the two halves are the contract
#: the roadmap states as "rules created in the UI evaluate identically to
#: API-created rules": the builder sends only these, and this file is where
#: they are proved to be documents the engine accepts unchanged.
BUILDER_CONDITION_BODIES: list[dict[str, Any]] = [
    {
        "version": 1,
        "classification": {"military": True, "government": False, "law_enforcement": False},
    },
    {
        "version": 1,
        "classification": {
            "military": False,
            "government": False,
            "law_enforcement": True,
            "mission": "medical",
        },
    },
    {"version": 1, "type_code": "C17"},
    {"version": 1, "model": "Globemaster"},
    {"version": 1, "watchlist_id": 1},
    {"version": 1, "watchlist_any": True},
    {"version": 1, "rare_aircraft": {"max_sightings": 2}},
    {"version": 1, "rare_type": {"max_sightings": 4}},
    {"version": 1, "min_distance_nm": 5, "max_distance_nm": 40},
    {"version": 1, "max_distance_nm": 40},
    {"version": 1, "min_alt_ft": 500, "max_alt_ft": 10000},
    {"version": 1, "max_alt_ft": 5000, "applies_on_ground": True},
    {
        "version": 1,
        "classification": {"military": True, "government": False, "law_enforcement": False},
        "max_alt_ft": 5000,
        "max_distance_nm": 40,
        "applies_on_ground": True,
    },
]


@pytest.mark.parametrize("conditions", BUILDER_CONDITION_BODIES)
def test_a_document_the_rule_builder_composes_is_accepted_unchanged(
    client: TestClient, conditions: dict[str, Any]
) -> None:
    """Every condition the builder can emit survives the round trip intact.

    Not merely "is accepted": each key the builder sent must come back
    carrying the value it sent, because a document quietly normalized on the
    way in would be a rule that does something other than what the user built.
    """
    created = _create(
        client,
        {
            "name": "Built in the UI",
            "description": None,
            "severity": "interesting",
            "conditions": conditions,
        },
    )

    echoed = created["conditions"]
    for key, value in conditions.items():
        assert echoed[key] == value, key
    assert created["describes"] != []


@pytest.mark.parametrize("conditions", BUILDER_CONDITION_BODIES)
def test_replaying_what_the_api_echoed_changes_nothing(
    client: TestClient, conditions: dict[str, Any]
) -> None:
    """Editing one field of a rule cannot silently reword the others.

    The builder loads a rule by parsing the *echoed* document back into its
    drafts and sends whatever those drafts compose. So the echo has to be a
    fixed point: send it back unchanged and the stored rule, and the prose it
    describes itself with, must be identical.
    """
    created = _create(
        client,
        {
            "name": "Built in the UI",
            "description": None,
            "severity": "interesting",
            "conditions": conditions,
        },
    )

    response = client.put(
        f"{RULES_PATH}/{created['id']}",
        json={
            "name": "Built in the UI",
            "description": None,
            "severity": "interesting",
            "conditions": created["conditions"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["conditions"] == created["conditions"]
    assert response.json()["describes"] == created["describes"]


def test_the_builder_cannot_compose_a_rule_the_api_refuses(client: TestClient) -> None:
    """The two validators agree on the cases the builder guards locally.

    Each of these is a rule that could never match anything, which the
    builder refuses to submit — this pins that the backend refuses it too, so
    the local check is a saved round trip rather than the only thing standing
    between a user and a rule that silently does nothing.
    """
    never_matching: list[dict[str, Any]] = [
        {"version": 1},
        {"version": 1, "applies_on_ground": True},
        {"version": 1, "min_distance_nm": 40, "max_distance_nm": 10},
        {"version": 1, "min_alt_ft": 10000, "max_alt_ft": 500},
        {"version": 1, "rare_aircraft": {"max_sightings": 0}},
        {
            "version": 1,
            "classification": {
                "military": False,
                "government": False,
                "law_enforcement": False,
            },
        },
    ]

    for conditions in never_matching:
        response = client.post(
            RULES_PATH,
            json={
                "name": "Never matches",
                "description": None,
                "severity": "info",
                "conditions": conditions,
            },
        )
        assert response.status_code == 422, conditions


# ------------------------------------------------------------------ rule CRUD


def test_rules_start_empty_on_an_install_with_no_enabled_templates(
    client: TestClient,
) -> None:
    response = client.get(RULES_PATH)

    assert response.status_code == 200
    assert response.json() == {"rules": []}


def test_a_created_rule_round_trips(client: TestClient) -> None:
    created = _create(client)

    assert created["name"] == "Military aircraft"
    assert created["severity"] == "high"
    assert created["enabled"] is True
    assert created["template_key"] is None
    assert created["conditions"]["classification"] == {
        "military": True,
        "government": False,
        "law_enforcement": False,
    }
    assert created["describes"] == ["military"]
    assert isinstance(created["created_at"], str)

    assert client.get(RULES_PATH).json()["rules"] == [created]


def test_a_rule_can_be_replaced(client: TestClient) -> None:
    created = _create(client)

    response = client.put(
        f"{RULES_PATH}/{created['id']}",
        json={
            "name": "Rare aircraft",
            "description": None,
            "severity": "interesting",
            "enabled": False,
            "conditions": {"version": 1, "rare_aircraft": {"max_sightings": 2}},
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Rare aircraft"
    assert updated["severity"] == "interesting"
    assert updated["enabled"] is False
    assert updated["describes"] == ["seen at most 2 time(s) here"]


def test_a_rule_can_be_deleted(client: TestClient) -> None:
    created = _create(client)

    assert client.delete(f"{RULES_PATH}/{created['id']}").status_code == 204
    assert client.get(RULES_PATH).json() == {"rules": []}


def test_replacing_a_rule_with_a_blank_name_is_refused(client: TestClient) -> None:
    """The same domain rule the create path applies, on the update path — it
    lives in the service, so it holds whichever verb reaches it."""
    created = _create(client)

    response = client.put(f"{RULES_PATH}/{created['id']}", json={**MILITARY_BODY, "name": "  "})

    assert response.status_code == 422


@pytest.mark.parametrize("method", ["put", "delete"])
def test_operations_on_an_unknown_rule_answer_404(client: TestClient, method: str) -> None:
    call = getattr(client, method)
    response = call(f"{RULES_PATH}/404", **({"json": MILITARY_BODY} if method == "put" else {}))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "conditions",
    [
        {"version": 1},
        {"version": 1, "rare_aircraft": {"max_sightings": 0}},
        {"version": 1, "min_distance_nm": 100.0, "max_distance_nm": 10.0},
        {"version": 1, "min_alt_ft": 30000.0, "max_alt_ft": 1000.0},
        {"version": 1, "classification": {}},
        {"version": 2, "watchlist_any": True},
        {"version": 1, "squawk": "7700"},
        {"version": 1, "max_distance_nm": 99999.0},
    ],
)
def test_an_unevaluable_or_never_matching_condition_set_is_refused(
    client: TestClient, conditions: dict[str, Any]
) -> None:
    """The condition set is validated by the very model the stored document is
    parsed with, so what the API accepts is exactly what the engine can
    evaluate — thresholds, bounds and the two "this can never match" checks
    included."""
    response = client.post(RULES_PATH, json={**MILITARY_BODY, "conditions": conditions})

    assert response.status_code == 422, response.text


def test_a_blank_name_is_refused(client: TestClient) -> None:
    response = client.post(RULES_PATH, json={**MILITARY_BODY, "name": "   "})

    assert response.status_code == 422


def test_an_unknown_severity_is_refused(client: TestClient) -> None:
    response = client.post(RULES_PATH, json={**MILITARY_BODY, "severity": "urgent"})

    assert response.status_code == 422


def test_an_unknown_body_key_is_refused(client: TestClient) -> None:
    response = client.post(RULES_PATH, json={**MILITARY_BODY, "colour": "red"})

    assert response.status_code == 422


def test_the_rule_endpoints_are_absent_from_the_published_schema(
    client: TestClient,
) -> None:
    """``/api/internal`` is an unsupported surface (ADR-0007, §5): the router is
    mounted with ``include_in_schema=False``, and mounting it *inside* the
    internal router rather than beside it must not have changed that."""
    paths = client.get("/api/v1/openapi.json").json()["paths"]

    assert not [path for path in paths if "alert-rule" in path or "alert-template" in path]


def test_a_created_rule_is_in_force_for_the_next_live_read(client: TestClient) -> None:
    """The propagation guarantee: the service recompiles the engine before the
    request answers, so there is no delay to reason about."""
    _create(client)

    service: AlertService = client.app.state.alerts  # type: ignore[attr-defined]
    assert [compiled.rule.name for compiled in service.engine.rules] == ["Military aircraft"]


# ---------------------------------------------------- the interesting surfaces


def _update(icao: str, *, squawk: str | None = None) -> AircraftStateUpdate:
    from datetime import UTC, datetime

    return AircraftStateUpdate(
        icao=icao,
        timestamp=datetime(2026, 6, 2, 14, 0, tzinfo=UTC),
        position=Position(latitude=47.6, longitude=-122.3),
        position_source="adsb",
        altitude_ft=25_000.0,
        squawk=squawk,
        on_ground=False,
    )


async def test_interesting_is_null_on_every_aircraft_when_nothing_matches(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(_update("ae1463"))

    body = (await rest.get("/api/v1/aircraft/current")).json()

    assert [aircraft["interesting"] for aircraft in body["items"]] == [None]


async def test_the_interesting_list_is_empty_when_nothing_matches(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(_update("ae1463"))

    response = await rest.get(INTERESTING_PATH)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_an_emergency_squawk_populates_the_block_and_the_list(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """Zero configuration, end to end through the real app: a 7700 reaches the
    §3.3 block on the live picture and the §3.4 list."""
    live_app.feed(_update("ae1463", squawk="7700"), _update("000002"))
    await live_app.evaluate_alerts()

    listed = (await rest.get(INTERESTING_PATH)).json()
    current = (await rest.get("/api/v1/aircraft/current")).json()

    assert listed["total"] == 1
    (interesting,) = listed["items"]
    assert interesting["icao"] == "ae1463"
    assert interesting["interesting"]["severity"] == "critical"
    assert interesting["interesting"]["reasons"] == ["Emergency squawk 7700 (general emergency)"]
    by_icao = {aircraft["icao"]: aircraft["interesting"] for aircraft in current["items"]}
    assert by_icao["ae1463"] == interesting["interesting"]
    assert by_icao["000002"] is None


async def test_the_interesting_list_orders_by_severity_then_distance(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """SPEC §49's panel ordering, and §3.4's own statement of it."""
    service: AlertService = live_app.app.state.alerts
    await service.create_rule(
        name="Everything nearby",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=RuleConditions(max_distance_nm=5_000.0),
    )
    live_app.feed(
        _update("000001"),
        AircraftStateUpdate(
            icao="000002",
            timestamp=_update("000002").timestamp,
            position=Position(latitude=48.6, longitude=-122.3),
            position_source="adsb",
            altitude_ft=25_000.0,
            on_ground=False,
        ),
        _update("000003", squawk="7700"),
    )
    await live_app.evaluate_alerts()

    items = (await rest.get(INTERESTING_PATH)).json()["items"]

    # Critical first; then the two info matches by distance ascending.
    assert [aircraft["icao"] for aircraft in items] == ["000003", "000001", "000002"]


async def test_the_websocket_snapshot_carries_the_same_interesting_block(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """§3.3's "the same shape used by the WebSocket", extended to this field:
    one serializer builds both, so they cannot disagree."""
    from .conftest import WebSocketProbe

    live_app.feed(_update("ae1463", squawk="7500"))
    await live_app.evaluate_alerts()

    probe = WebSocketProbe(app=live_app.app)
    await probe.connect()
    try:
        snapshot = await probe.frame()
    finally:
        await probe.disconnect()
    rest_body = (await rest.get("/api/v1/aircraft/current")).json()

    assert snapshot["type"] == "snapshot"
    assert snapshot["data"]["aircraft"] == rest_body["items"]
    assert snapshot["data"]["aircraft"][0]["interesting"]["severity"] == "critical"


# ------------------------------------------------------------- match history


async def test_the_match_history_starts_empty(rest: AsyncClient) -> None:
    response = await rest.get(MATCHES_PATH)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": None, "limit": 50, "offset": 0}


async def test_a_fired_emergency_appears_in_the_match_history(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(_update("ae1463", squawk="7600"))
    await live_app.evaluate_alerts()

    (match,) = (await rest.get(MATCHES_PATH)).json()["items"]

    assert match["icao"] == "ae1463"
    assert match["severity"] == "critical"
    assert match["reason"] == "Emergency squawk 7600 (radio failure)"
    assert match["builtin_key"] == "emergency_7600"
    assert match["rule"] is None
    assert match["notified"] is False
    assert isinstance(match["sighting_id"], int)
    assert match["at"].endswith("Z")


async def test_a_rule_match_names_its_rule_in_the_history(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    service: AlertService = live_app.app.state.alerts
    created = await service.create_rule(
        name="Everything nearby",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=RuleConditions(max_distance_nm=5_000.0),
    )
    live_app.feed(_update("ae1463"))
    await live_app.evaluate_alerts()

    (match,) = (await rest.get(MATCHES_PATH)).json()["items"]

    assert match["rule"] == {"id": created.id, "name": "Everything nearby"}
    assert match["builtin_key"] is None
    assert match["reason"] == "Rule: Everything nearby"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("severity=critical", 1),
        ("severity=info", 0),
        ("icao=ae1463", 1),
        ("icao=000002", 0),
    ],
)
async def test_the_match_history_filters(
    live_app: LiveApp, rest: AsyncClient, query: str, expected: int
) -> None:
    live_app.feed(_update("ae1463", squawk="7700"))
    await live_app.evaluate_alerts()

    body = (await rest.get(f"{MATCHES_PATH}?{query}")).json()

    assert len(body["items"]) == expected


async def test_the_match_history_rejects_a_malformed_icao(rest: AsyncClient) -> None:
    """§2.9's path/query parameter constraint, applied to the filter."""
    response = await rest.get(f"{MATCHES_PATH}?icao=NOTHEX")

    assert response.status_code == 422


# ------------------------------------------------------------ notified marker


def _notified_path(match_id: int) -> str:
    return f"/api/internal/alerts/matches/{match_id}/notified"


async def _one_match(live_app: LiveApp, rest: AsyncClient) -> dict[str, Any]:
    """Fire one built-in emergency and return the history row it produced."""
    live_app.feed(_update("ae1463", squawk="7600"))
    await live_app.evaluate_alerts()
    (match,) = (await rest.get(MATCHES_PATH)).json()["items"]
    row: dict[str, Any] = match
    return row


async def test_marking_a_match_notified_is_visible_in_the_history(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """Issue #104. Until this endpoint existed the ``notified`` field could
    only ever read ``false``, so the Alerts page rendered a marker that was
    guaranteed to be wrong for every match a user had actually been shown."""
    match = await _one_match(live_app, rest)
    assert match["notified"] is False

    response = await rest.post(_notified_path(match["id"]))

    assert response.status_code == 204
    assert response.content == b""
    (after,) = (await rest.get(MATCHES_PATH)).json()["items"]
    assert after["notified"] is True


async def test_marking_a_match_notified_twice_is_a_no_op_success(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """Two tabs open on one receiver both deliver the same match and both
    report it; the second is not a conflict, because "someone was notified"
    does not become more true the second time it is asserted."""
    match = await _one_match(live_app, rest)
    await rest.post(_notified_path(match["id"]))

    response = await rest.post(_notified_path(match["id"]))

    assert response.status_code == 204
    (after,) = (await rest.get(MATCHES_PATH)).json()["items"]
    assert after["notified"] is True


async def test_marking_an_unknown_match_notified_is_a_404(rest: AsyncClient) -> None:
    response = await rest.post(_notified_path(4_242))

    assert response.status_code == 404
    assert "4242" in response.json()["detail"]


async def test_marking_a_match_notified_touches_no_other_row(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(_update("ae1463", squawk="7600"), _update("000002", squawk="7700"))
    await live_app.evaluate_alerts()
    matches = (await rest.get(MATCHES_PATH)).json()["items"]
    assert len(matches) == 2

    await rest.post(_notified_path(matches[0]["id"]))

    after = (await rest.get(MATCHES_PATH)).json()["items"]
    assert {row["id"]: row["notified"] for row in after} == {
        matches[0]["id"]: True,
        matches[1]["id"]: False,
    }


async def test_the_notified_endpoint_stays_off_the_published_schema(rest: AsyncClient) -> None:
    """ADR-0007: ``/api/internal`` is excluded from the OpenAPI document the
    app publishes for ``/api/v1``, and mounting a new router must not be a way
    around that."""
    paths = (await rest.get("/api/v1/openapi.json")).json()["paths"]

    assert not any("notified" in path for path in paths)


async def test_the_read_endpoints_are_in_the_published_schema(rest: AsyncClient) -> None:
    paths = (await rest.get("/api/v1/openapi.json")).json()["paths"]

    assert "/api/v1/aircraft/interesting" in paths
    assert "/api/v1/alerts/matches" in paths


async def test_the_interesting_route_does_not_collide_with_the_icao_route(
    rest: AsyncClient,
) -> None:
    """§2.9 notes that ``current`` and ``interesting`` can never match the
    6-hex-char ``{icao}`` pattern, so the literal routes and the parameterized
    one are unambiguous however they are declared."""
    response = await rest.get(INTERESTING_PATH)

    assert response.status_code == 200
    assert "items" in response.json()
