import uuid
import pytest
from app.core.database import AsyncSessionLocal
from app.models.pharmacy_model import Medicine
from app.schemas.pharmacy_schema import MedicineCreate
from app.services.pharmacy_service import PharmacyService
from app.core.exceptions import ConflictException

@pytest.mark.asyncio
async def test_duplicate_validation():
    uid = uuid.uuid4().hex[:8]
    med_name = f"Med_{uid}"
    mfg_name = f"Mfg_{uid}"
    batch = f"Batch_{uid}"
    
    async with AsyncSessionLocal() as session:
        service = PharmacyService(session)
        
        # 1. Create first medicine
        data1 = MedicineCreate(
            name=med_name,
            category="Tablet",
            unit="Strip",
            unit_price=10.0,
            stock_quantity=100,
            reorder_level=10,
            manufacturer=mfg_name,
            batch_number=batch
        )
        await service.create_medicine(data1, 1)
        
        # 2. Try to create exactly the same -> Conflict
        data2 = data1.model_copy()
        with pytest.raises(ConflictException):
            await service.create_medicine(data2, 1)
            
        # 3. Same med, mfg, but different case batch -> Conflict
        data3 = data1.model_copy()
        data3.batch_number = batch.upper()
        with pytest.raises(ConflictException):
            await service.create_medicine(data3, 1)
            
        # 4. Same batch, different medicine -> Allowed
        data4 = data1.model_copy()
        data4.name = f"Med_Diff_{uid}"
        try:
            await service.create_medicine(data4, 1)
        except ConflictException:
            pytest.fail("Should allow same batch for different medicine")
            
        # 5. Same batch, same medicine, different manufacturer -> Allowed
        data5 = data1.model_copy()
        data5.manufacturer = f"Mfg_Diff_{uid}"
        try:
            await service.create_medicine(data5, 1)
        except ConflictException:
            pytest.fail("Should allow same batch for different manufacturer")
