"""``/api/internal/alert-rules`` with the version 2 conditions (slice 089).

The rule endpoints validate through :class:`flightsite.alerts.model.
RuleConditions`, so most of what is new is checked as model tests in
``tests/alerts/test_conditions_v2.py``. What is pinned here is what only the
HTTP surface can show:

* every new field is accepted, echoed back unchanged in the shape the rule
  builder sends (sorted sets, closed ring), and replaying the echo is a fixed
  point — the round-trip property ``test_alerts_api.py`` pins for v1;
* each invalid value is a ``422`` *naming the field* it is about, so the
  builder can put the message next to the right input;
* a client still sending version 1 gets its rule back as version 2 with the
  same conditions, and a stored v1 row reads back upgraded and is rewritten as
  v2 on its next save.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from flightsite.app import create_app
from flightsite.db import Database, database_path

RULES_PATH = "/api/internal/alert-rules"

SQUARE_RING = [[-2.0, 50.0], [-1.0, 50.0], [-1.0, 51.0], [-2.0, 51.0], [-2.0, 50.0]]

#: The documents the rule builder composes for the new condition kinds,
#: exactly as ``conditionsToDocument`` in
#: ``frontend/src/features/alerts/lib/conditions.ts`` emits them.
BUILDER_V2_BODIES: list[dict[str, Any]] = [
    {"version": 2, "squawk_in": ["1200", "7000"]},
    {"version": 2, "callsign_glob": "RCH*"},
    {"version": 2, "registration_glob": "N?23AB"},
    {"version": 2, "min_ground_speed_kt": 80, "max_ground_speed_kt": 250},
    {"version": 2, "max_ground_speed_kt": 120},
    {"version": 2, "min_vertical_rate_fpm": -3000, "max_vertical_rate_fpm": -1000},
    {"version": 2, "min_vertical_rate_fpm": 1500},
    {"version": 2, "emitter_category_in": ["A1", "A7"]},
    {"version": 2, "within_area": {"type": "Polygon", "coordinates": [SQUARE_RING]}},
    {
        "version": 2,
        "classification": {"military": True, "government": False, "law_enforcement": False},
        "callsign_glob": "RCH*",
        "max_ground_speed_kt": 250,
        "within_area": {"type": "Polygon", "coordinates": [SQUARE_RING]},
    },
]


@pytest.fixture
def client(isolated_data_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(isolated_data_dir)) as test_client:
        yield test_client


def _body(conditions: dict[str, Any], name: str = "Built in the UI") -> dict[str, Any]:
    return {"name": name, "description": None, "severity": "interesting", "conditions": conditions}


def _create(client: TestClient, conditions: dict[str, Any]) -> dict[str, Any]:
    response = client.post(RULES_PATH, json=_body(conditions))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.mark.parametrize("conditions", BUILDER_V2_BODIES)
def test_a_v2_document_the_builder_composes_is_accepted_unchanged(
    client: TestClient, conditions: dict[str, Any]
) -> None:
    created = _create(client, conditions)

    echoed = created["conditions"]
    for key, value in conditions.items():
        assert echoed[key] == value, key
    assert created["describes"] != []


@pytest.mark.parametrize("conditions", BUILDER_V2_BODIES)
def test_replaying_a_v2_echo_changes_nothing(
    client: TestClient, conditions: dict[str, Any]
) -> None:
    created = _create(client, conditions)

    response = client.put(f"{RULES_PATH}/{created['id']}", json=_body(created["conditions"]))

    assert response.status_code == 200, response.text
    assert response.json()["conditions"] == created["conditions"]
    assert response.json()["describes"] == created["describes"]


def test_an_unclosed_ring_is_echoed_closed(client: TestClient) -> None:
    created = _create(
        client,
        {"version": 2, "within_area": {"type": "Polygon", "coordinates": [SQUARE_RING[:-1]]}},
    )

    assert created["conditions"]["within_area"]["coordinates"] == [SQUARE_RING]
    assert created["describes"] == ["inside a drawn area of 4 vertices"]


def test_a_version_1_body_is_answered_as_version_2(client: TestClient) -> None:
    created = _create(client, {"version": 1, "type_code": "C17", "max_alt_ft": 5000})

    assert created["conditions"]["version"] == 2
    assert created["conditions"]["type_code"] == "C17"
    assert created["conditions"]["max_alt_ft"] == 5000
    assert created["describes"] == ["type C17", "at or below 5000 ft"]


@pytest.mark.parametrize(
    ("field", "conditions"),
    [
        ("squawk_in", {"squawk_in": ["7800"]}),
        ("squawk_in", {"squawk_in": []}),
        ("squawk_in", {"squawk_in": [f"{n:04o}" for n in range(17)]}),
        ("callsign_glob", {"callsign_glob": "RCH 1"}),
        ("callsign_glob", {"callsign_glob": "X" * 33}),
        ("registration_glob", {"registration_glob": ""}),
        ("min_ground_speed_kt", {"min_ground_speed_kt": -5}),
        ("max_ground_speed_kt", {"max_ground_speed_kt": 2500}),
        ("min_vertical_rate_fpm", {"min_vertical_rate_fpm": -25000}),
        ("max_vertical_rate_fpm", {"max_vertical_rate_fpm": 25000}),
        ("emitter_category_in", {"emitter_category_in": ["E1"]}),
        ("within_area", {"within_area": {"type": "Polygon", "coordinates": []}}),
        (
            "within_area",
            {
                "within_area": {
                    "type": "Polygon",
                    "coordinates": [[[179.5, 10], [-179.5, 10], [-179.5, 11], [179.5, 11]]],
                }
            },
        ),
        (
            "within_area",
            {
                "within_area": {
                    "type": "Polygon",
                    "coordinates": [SQUARE_RING, [[-1.8, 50.2], [-1.2, 50.2], [-1.5, 50.8]]],
                }
            },
        ),
        ("not_a_condition", {"not_a_condition": True, "callsign_glob": "RCH*"}),
    ],
)
def test_each_invalid_v2_field_is_a_422_naming_it(
    client: TestClient, field: str, conditions: dict[str, Any]
) -> None:
    response = client.post(RULES_PATH, json=_body({"version": 2, **conditions}))

    assert response.status_code == 422, response.text
    locations = [error["loc"] for error in response.json()["detail"]]
    assert any(field in location for location in locations), locations


@pytest.mark.parametrize(
    "conditions",
    [
        {"min_ground_speed_kt": 300, "max_ground_speed_kt": 200},
        {"min_vertical_rate_fpm": 500, "max_vertical_rate_fpm": -500},
        {"version": 1, "callsign_glob": "RCH*"},
    ],
)
def test_never_matching_or_mislabelled_v2_documents_are_refused(
    client: TestClient, conditions: dict[str, Any]
) -> None:
    response = client.post(RULES_PATH, json=_body({"version": 2, **conditions}))

    assert response.status_code == 422, response.text


# ------------------------------------------------- a stored v1 row, read back

V1_ROW = (
    '{"applies_on_ground":false,"max_distance_nm":40.0,"type_code":"C17",'
    '"version":1,"watchlist_any":false}'
)


async def _stored_text(data_dir: Path, rule_id: int) -> str:
    database = Database(database_path(data_dir))
    try:
        async with database.read_session() as session:
            result = await session.execute(
                text("SELECT conditions_json FROM alert_rules WHERE id = :id"), {"id": rule_id}
            )
            return str(result.scalar_one())
    finally:
        await database.dispose()


async def _store_text(data_dir: Path, rule_id: int, document: str) -> None:
    database = Database(database_path(data_dir))
    try:
        async with database.writer_session() as session:
            await session.execute(
                text("UPDATE alert_rules SET conditions_json = :doc WHERE id = :id"),
                {"doc": document, "id": rule_id},
            )
    finally:
        await database.dispose()


async def test_a_stored_v1_row_reads_back_upgraded_and_is_rewritten_on_save(
    isolated_data_dir: Path,
) -> None:
    """No migration rewrites ``alert_rules``: a v1 row stays v1 text until its
    rule is saved, reads as v2 in the meantime, and saving writes v2."""
    with TestClient(create_app(isolated_data_dir)) as client:
        created = _create(client, {"version": 2, "type_code": "C17", "max_distance_nm": 40})
    rule_id = created["id"]
    await _store_text(isolated_data_dir, rule_id, V1_ROW)

    with TestClient(create_app(isolated_data_dir)) as client:
        (listed,) = client.get(RULES_PATH).json()["rules"]
        assert listed["conditions"] == {
            "version": 2,
            "type_code": "C17",
            "max_distance_nm": 40.0,
            "applies_on_ground": False,
            "watchlist_any": False,
        }
        assert listed["describes"] == ["type C17", "within 40 nm"]
        assert json.loads(await _stored_text(isolated_data_dir, rule_id))["version"] == 1

        saved = client.put(f"{RULES_PATH}/{rule_id}", json=_body(listed["conditions"]))
        assert saved.status_code == 200, saved.text

    assert json.loads(await _stored_text(isolated_data_dir, rule_id)) == {
        **json.loads(V1_ROW),
        "version": 2,
    }
