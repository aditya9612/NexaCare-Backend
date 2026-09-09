import uuid
from datetime import date
import pytest

from app.core.database import AsyncSessionLocal
from app.models.patient_model import Patient
from app.models.pharmacy_model import PharmacyInvoice
from app.services.pharmacy_service import PharmacyService
from app.utils.helpers import utc_now


@pytest.mark.asyncio
async def test_list_pharmacy_invoices_filters():
    uid = uuid.uuid4().hex[:8]
    today = date.today()

    async with AsyncSessionLocal() as session:
        # Create test patients
        patient1 = Patient(
            patient_code=f"PAT_{uid}_1",
            first_name="Hemant",
            last_name="Kumar",
            gender="male",
            status="active",
        )
        patient2 = Patient(
            patient_code=f"PAT_{uid}_2",
            first_name="Suresh",
            last_name="Raina",
            gender="male",
            status="active",
        )
        session.add_all([patient1, patient2])
        await session.commit()
        await session.refresh(patient1)
        await session.refresh(patient2)

        # Create test invoices
        invoice1 = PharmacyInvoice(
            invoice_number=f"INV_{uid}_1",
            patient_id=patient1.id,
            total_amount=500.0,
            paid_amount=500.0,
            status="paid",
            created_at=utc_now(),
        )
        invoice2 = PharmacyInvoice(
            invoice_number=f"INV_{uid}_2",
            patient_id=patient2.id,
            total_amount=300.0,
            paid_amount=0.0,
            status="pending",
            created_at=utc_now(),
        )
        session.add_all([invoice1, invoice2])
        await session.commit()
        await session.refresh(invoice1)
        await session.refresh(invoice2)

        service = PharmacyService(session)

        # 1. No filters
        res_all = await service.list_invoices(page=1, size=20)
        assert res_all is not None
        assert res_all.total >= 2
        inv_ids = [inv.id for inv in res_all.items]
        assert invoice1.id in inv_ids
        assert invoice2.id in inv_ids

        # 2. Filter by status="PAID" (case-insensitive)
        res_paid = await service.list_invoices(page=1, size=20, status="PAID")
        assert res_paid is not None
        paid_ids = [inv.id for inv in res_paid.items]
        assert invoice1.id in paid_ids
        assert invoice2.id not in paid_ids

        # 3. Filter by patient_name="Hemant"
        res_name = await service.list_invoices(page=1, size=20, patient_name="Hemant")
        assert res_name is not None
        name_ids = [inv.id for inv in res_name.items]
        assert invoice1.id in name_ids
        assert invoice2.id not in name_ids

        # 4. Filter by date
        res_date = await service.list_invoices(page=1, size=20, invoice_date=today)
        assert res_date is not None
        date_ids = [inv.id for inv in res_date.items]
        assert invoice1.id in date_ids
        assert invoice2.id in date_ids

        # 5. Combined filters (status=PAID, patient_name=Hemant, date=today)
        res_comb = await service.list_invoices(
            page=1, size=20, status="PAID", patient_name="Hemant", invoice_date=today
        )
        assert res_comb is not None
        comb_ids = [inv.id for inv in res_comb.items]
        assert invoice1.id in comb_ids
        assert invoice2.id not in comb_ids

        # 6. Combined filters matching 0 records
        res_empty = await service.list_invoices(
            page=1, size=20, status="PENDING", patient_name="Hemant", invoice_date=today
        )
        assert res_empty is not None
        empty_ids = [inv.id for inv in res_empty.items]
        assert invoice1.id not in empty_ids
