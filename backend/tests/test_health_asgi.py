"""Endpoint tests driven directly through httpx's ASGI transport.

Complements the ``fastapi.testclient.TestClient``-based tests (which also use
httpx's ASGI transport under the hood) by exercising the app over the async
httpx client and the app's lifespan context explicitly.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from flightsite import __version__
from flightsite.app import create_app


async def test_health_via_asgi_transport() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


async def test_ready_via_asgi_transport_is_ready_after_lifespan_startup() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True
