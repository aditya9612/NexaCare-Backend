import pytest


@pytest.mark.asyncio
async def test_doctors_require_auth(client):
    response = await client.get("/api/v1/doctors/")
    assert response.status_code == 401
