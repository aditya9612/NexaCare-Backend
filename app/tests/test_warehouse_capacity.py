import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user_model import User
from app.core.dependencies import get_current_active_user, get_current_user
from unittest.mock import patch

@pytest.mark.asyncio
async def test_warehouse_capacity_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as ac:
        u = User(id=1, email='test@test.com', is_active=True, is_verified=True, hashed_password='pw', user_code='TEST1')
        app.dependency_overrides[get_current_active_user] = lambda: u
        app.dependency_overrides[get_current_user] = lambda: u

        with patch('app.core.dependencies.require_permission') as mock_req:
            mock_req.return_value = lambda: u
            with patch('app.core.dependencies.RBACRepository.get_user_permissions') as mock_rbac:
                mock_rbac.return_value = ['inventory:create', 'inventory:update', 'inventory:read']

                # 1. CREATE capacity=5000
                create_payload = {'name': 'CapTest WH', 'code': 'CAP1', 'capacity': 5000}
                resp1 = await ac.post('/api/v1/inventory/warehouses', json=create_payload)
                assert resp1.status_code == 201
                data1 = resp1.json()['data']
                assert data1['capacity'] == 5000
                w_id = data1['id']

                # 2. UPDATE VALID VALUE capacity=7500
                resp2 = await ac.put(f'/api/v1/inventory/warehouses/{w_id}', json={'capacity': 7500})
                assert resp2.status_code == 200
                assert resp2.json()['data']['capacity'] == 7500

                # Verify DB directly via GET
                resp2_get = await ac.get(f'/api/v1/inventory/warehouses/{w_id}')
                assert resp2_get.json()['data']['capacity'] == 7500

                # 3. UPDATE ZERO capacity=0
                resp3 = await ac.put(f'/api/v1/inventory/warehouses/{w_id}', json={'capacity': 0})
                assert resp3.status_code == 200
                assert resp3.json()['data']['capacity'] == 0

                # Verify DB directly via GET
                resp3_get = await ac.get(f'/api/v1/inventory/warehouses/{w_id}')
                assert resp3_get.json()['data']['capacity'] == 0

                # 4. UPDATE OMITTED (capacity remains 0)
                resp4 = await ac.put(f'/api/v1/inventory/warehouses/{w_id}', json={'name': 'CapTest Renamed'})
                assert resp4.status_code == 200
                assert resp4.json()['data']['name'] == 'CapTest Renamed'
                assert resp4.json()['data']['capacity'] == 0

                # 5. EXPLICIT NULL
                resp5 = await ac.put(f'/api/v1/inventory/warehouses/{w_id}', json={'capacity': None})
                assert resp5.status_code == 200
                assert resp5.json()['data']['capacity'] is None

                # Verify DB directly via GET
                resp5_get = await ac.get(f'/api/v1/inventory/warehouses/{w_id}')
                assert resp5_get.json()['data']['capacity'] is None

        app.dependency_overrides.clear()
