import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert "x-request-id" in response.headers


async def test_unknown_route_uses_error_format(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found", "code": "http_404"}
