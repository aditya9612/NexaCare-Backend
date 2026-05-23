import pytest


@pytest.mark.asyncio
async def test_patients_require_auth(client):
    response = await client.get("/api/v1/patients/")
    assert response.status_code == 401
