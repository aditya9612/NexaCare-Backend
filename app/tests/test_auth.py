import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_validation(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "invalid", "password": "short", "full_name": "Test"},
    )
    assert response.status_code == 422
