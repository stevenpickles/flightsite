"""Internal watchlists API tests: ``/api/internal/watchlists*`` (slice 037).

``docs/API.md`` §5's sketch: ``GET``/``POST /watchlists``,
``PUT``/``DELETE /watchlists/{id}``, and entry CRUD under
``/watchlists/{id}/entries``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app

WATCHLISTS_PATH = "/api/internal/watchlists"


@pytest.fixture
def client(isolated_data_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(isolated_data_dir)) as test_client:
        yield test_client


def _create(client: TestClient, name: str, description: str | None = None) -> dict[str, object]:
    response = client.post(WATCHLISTS_PATH, json={"name": name, "description": description})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


# ------------------------------------------------------------- watchlists


def test_list_watchlists_starts_empty(client: TestClient) -> None:
    response = client.get(WATCHLISTS_PATH)

    assert response.status_code == 200
    assert response.json() == {"watchlists": []}


def test_create_watchlist_round_trips(client: TestClient) -> None:
    body = _create(client, "Local Police", "patrol helicopters")

    assert body["name"] == "Local Police"
    assert body["description"] == "patrol helicopters"
    assert body["entry_count"] == 0
    assert isinstance(body["id"], int)
    assert isinstance(body["created_at"], str)

    listed = client.get(WATCHLISTS_PATH).json()["watchlists"]
    assert listed == [body]


def test_create_watchlist_trims_and_normalizes_name(client: TestClient) -> None:
    body = _create(client, "  Local Police  ")

    assert body["name"] == "Local Police"


def test_create_watchlist_rejects_a_blank_name(client: TestClient) -> None:
    response = client.post(WATCHLISTS_PATH, json={"name": "   "})

    assert response.status_code == 422
    assert "blank" in response.json()["detail"]


def test_create_watchlist_rejects_a_duplicate_name(client: TestClient) -> None:
    _create(client, "Local Police")

    response = client.post(WATCHLISTS_PATH, json={"name": "Local Police"})

    assert response.status_code == 409


def test_create_watchlist_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(WATCHLISTS_PATH, json={"name": "X", "bogus": True})

    assert response.status_code == 422


def test_update_watchlist_renames_it(client: TestClient) -> None:
    created = _create(client, "Old Name")

    response = client.put(
        f"{WATCHLISTS_PATH}/{created['id']}",
        json={"name": "New Name", "description": "updated"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    assert body["description"] == "updated"


def test_update_unknown_watchlist_returns_404(client: TestClient) -> None:
    response = client.put(f"{WATCHLISTS_PATH}/999", json={"name": "X"})

    assert response.status_code == 404


def test_update_watchlist_rejects_a_colliding_name(client: TestClient) -> None:
    _create(client, "Taken")
    other = _create(client, "Other")

    response = client.put(f"{WATCHLISTS_PATH}/{other['id']}", json={"name": "Taken"})

    assert response.status_code == 409


def test_delete_watchlist_removes_it(client: TestClient) -> None:
    created = _create(client, "Gone Soon")

    response = client.delete(f"{WATCHLISTS_PATH}/{created['id']}")

    assert response.status_code == 204
    assert client.get(WATCHLISTS_PATH).json()["watchlists"] == []


def test_delete_unknown_watchlist_returns_404(client: TestClient) -> None:
    response = client.delete(f"{WATCHLISTS_PATH}/999")

    assert response.status_code == 404


def test_list_watchlists_reports_entry_count(client: TestClient) -> None:
    created = _create(client, "W")
    client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries",
        json={"kind": "icao24", "value": "ae1463"},
    )

    listed = client.get(WATCHLISTS_PATH).json()["watchlists"]

    assert listed[0]["entry_count"] == 1


# ------------------------------------------------------------------ entries


def test_add_and_list_entries_round_trip(client: TestClient) -> None:
    created = _create(client, "W")

    response = client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries",
        json={"kind": "registration", "value": "n12345", "note": "a note"},
    )

    assert response.status_code == 201
    entry = response.json()
    assert entry["kind"] == "registration"
    assert entry["value"] == "N12345"
    assert entry["note"] == "a note"
    assert entry["watchlist_id"] == created["id"]

    listed = client.get(f"{WATCHLISTS_PATH}/{created['id']}/entries").json()["entries"]
    assert listed == [entry]


def test_list_entries_for_an_unknown_watchlist_returns_404(client: TestClient) -> None:
    response = client.get(f"{WATCHLISTS_PATH}/999/entries")

    assert response.status_code == 404


def test_add_entry_to_an_unknown_watchlist_returns_404(client: TestClient) -> None:
    response = client.post(
        f"{WATCHLISTS_PATH}/999/entries", json={"kind": "icao24", "value": "ae1463"}
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("icao24", "not-hex"),
        ("registration", ""),
        ("type_code", "toolongtype"),
        ("category", "unknown"),
        ("category", "not_a_real_category"),
    ],
)
def test_add_entry_rejects_an_invalid_value_per_kind(
    client: TestClient, kind: str, value: str
) -> None:
    created = _create(client, "W")

    response = client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries", json={"kind": kind, "value": value}
    )

    assert response.status_code == 422


def test_add_entry_rejects_an_unrecognized_kind(client: TestClient) -> None:
    created = _create(client, "W")

    response = client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries",
        json={"kind": "not_a_kind", "value": "x"},
    )

    assert response.status_code == 422


def test_add_duplicate_entry_returns_409(client: TestClient) -> None:
    created = _create(client, "W")
    client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries", json={"kind": "icao24", "value": "ae1463"}
    )

    response = client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries", json={"kind": "icao24", "value": "ae1463"}
    )

    assert response.status_code == 409


def test_remove_entry(client: TestClient) -> None:
    created = _create(client, "W")
    entry = client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries", json={"kind": "icao24", "value": "ae1463"}
    ).json()

    response = client.delete(f"{WATCHLISTS_PATH}/{created['id']}/entries/{entry['id']}")

    assert response.status_code == 204
    assert client.get(f"{WATCHLISTS_PATH}/{created['id']}/entries").json()["entries"] == []


def test_remove_entry_from_an_unknown_watchlist_returns_404(client: TestClient) -> None:
    response = client.delete(f"{WATCHLISTS_PATH}/999/entries/1")

    assert response.status_code == 404


def test_remove_unknown_entry_returns_404(client: TestClient) -> None:
    created = _create(client, "W")

    response = client.delete(f"{WATCHLISTS_PATH}/{created['id']}/entries/999")

    assert response.status_code == 404


def test_deleting_a_watchlist_removes_its_entries(client: TestClient) -> None:
    created = _create(client, "W")
    client.post(
        f"{WATCHLISTS_PATH}/{created['id']}/entries", json={"kind": "icao24", "value": "ae1463"}
    )

    client.delete(f"{WATCHLISTS_PATH}/{created['id']}")

    assert client.get(f"{WATCHLISTS_PATH}/{created['id']}/entries").status_code == 404


def test_watchlists_are_excluded_from_the_published_openapi_schema(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()

    assert not any("watchlist" in path for path in schema["paths"])
