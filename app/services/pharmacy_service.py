from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PharmacyStatus, PurchaseStatus
from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.models.pharmacy_model import (
    Medicine,
    PharmacyInvoice,
    PharmacyInvoiceItem,
    Prescription,
    PrescriptionItem,
    Purchase,
    PurchaseItem,
    Supplier,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.pharmacy_repository import (
    MedicineRepository,
    PharmacyInvoiceRepository,
    PrescriptionRepository,
    PurchaseRepository,
    SupplierRepository,
)
from app.schemas.pharmacy_schema import (
    ExpiryAlert,
    LowStockAlert,
    MedicineCreate,
    MedicineResponse,
    MedicineUpdate,
    PharmacyInvoiceCreate,
    PharmacyInvoiceResponse,
    PharmacyInvoiceItemResponse,
    PrescriptionCreate,
    PrescriptionItemResponse,
    PrescriptionResponse,
    PrescriptionUpdate,
    PurchaseCreate,
    PurchaseItemResponse,
    PurchaseResponse,
    SalesReport,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)
from app.utils.helpers import (
    calculate_gst_amount,
    generate_medicine_sku,
    generate_pharmacy_invoice_number,
    generate_prescription_number,
    generate_purchase_number,
    utc_now,
)
from app.utils.pagination import build_paginated_result


class PharmacyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.medicine_repo = MedicineRepository(db)
        self.prescription_repo = PrescriptionRepository(db)
        self.invoice_repo = PharmacyInvoiceRepository(db)
        self.supplier_repo = SupplierRepository(db)
        self.purchase_repo = PurchaseRepository(db)
        self.audit_repo = AuditRepository(db)
        self.patient_repo = PatientRepository(db)

    # --- Medicines ---
    async def create_medicine(self, data: MedicineCreate, user_id: int) -> MedicineResponse:
        if data.barcode:
            existing = await self.medicine_repo.get_by_barcode(data.barcode)
            if existing:
                raise ConflictException("Medicine with this barcode already exists")
        medicine = Medicine(sku=generate_medicine_sku(), **data.model_dump())
        medicine = await self.medicine_repo.create(medicine)
        await self.audit_repo.create("create", "pharmacy", user_id=user_id, resource_id=str(medicine.id))
        return MedicineResponse.model_validate(medicine)

    async def list_medicines(
        self, page: int = 1, size: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None,
    ):
        skip = (page - 1) * size
        items = await self.medicine_repo.list_all(skip=skip, limit=size, sort_by=sort_by,
                                                   sort_order=sort_order, category=category)
        total = await self.medicine_repo.count_all(category=category)
        return build_paginated_result([MedicineResponse.model_validate(m) for m in items], total, page, size)

    async def search_medicines(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.medicine_repo.search(q, skip=skip, limit=size)
        total = await self.medicine_repo.count_search(q)
        return build_paginated_result([MedicineResponse.model_validate(m) for m in items], total, page, size)

    async def get_medicine(self, medicine_id: int) -> MedicineResponse:
        medicine = await self.medicine_repo.get_by_id(medicine_id)
        if not medicine:
            raise NotFoundException("Medicine not found")
        return MedicineResponse.model_validate(medicine)

    async def update_medicine(self, medicine_id: int, data: MedicineUpdate, user_id: int) -> MedicineResponse:
        medicine = await self.medicine_repo.get_by_id(medicine_id)
        if not medicine:
            raise NotFoundException("Medicine not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(medicine, key, value)
        medicine = await self.medicine_repo.update(medicine)
        await self.audit_repo.create("update", "pharmacy", user_id=user_id, resource_id=str(medicine.id))
        return MedicineResponse.model_validate(medicine)

    async def delete_medicine(self, medicine_id: int, user_id: int) -> None:
        medicine = await self.medicine_repo.get_by_id(medicine_id)
        if not medicine:
            raise NotFoundException("Medicine not found")
        await self.medicine_repo.soft_delete(medicine)
        await self.audit_repo.create("delete", "pharmacy", user_id=user_id, resource_id=str(medicine.id))

    async def get_low_stock(self) -> list[LowStockAlert]:
        medicines = await self.medicine_repo.get_low_stock()
        return [
            LowStockAlert(
                medicine_id=m.id, name=m.name, sku=m.sku,
                stock_quantity=m.stock_quantity, reorder_level=m.reorder_level,
            )
            for m in medicines
        ]

    async def get_expiry_alerts(self, days: int = 30) -> list[ExpiryAlert]:
        medicines = await self.medicine_repo.get_expiry_alerts(days=days)
        today = date.today()
        return [
            ExpiryAlert(
                medicine_id=m.id, name=m.name, sku=m.sku,
                expiry_date=m.expiry_date,
                stock_quantity=m.stock_quantity,
                days_until_expiry=(m.expiry_date - today).days if m.expiry_date else 0,
            )
            for m in medicines
        ]

    # --- Prescriptions ---
    
    async def create_prescription(self, data: PrescriptionCreate, user_id: int) -> PrescriptionResponse:
        if not data.appointment_id:
            raise BadRequestException("Appointment ID is required to create prescription")
        if not data.items:
            raise BadRequestException("Prescription must contain at least one medicine item")
        items = [
            PrescriptionItem(**item.model_dump()) for item in data.items
        ]
        prescription = Prescription(
            patient_id=data.patient_id,
            doctor_id=data.doctor_id,
            appointment_id=data.appointment_id,
            prescription_number=generate_prescription_number(),
            instructions=data.instructions,
        )
        prescription = await self.prescription_repo.create(prescription, items)
        prescription = await self.prescription_repo.get_by_id(prescription.id)
        await self.audit_repo.create(
            "create",
            "pharmacy_prescription",
            user_id=user_id,
            resource_id=str(prescription.id)
        )
        return self._prescription_response(prescription)
    async def list_prescriptions(
        self,
        page: int = 1,
        size: int = 20,
        status: str | None = None
    ):
        skip = (page - 1) * size
        items = await self.prescription_repo.list_all(skip=skip, limit=size, status=status)
        total = await self.prescription_repo.count_all(status=status)

        return build_paginated_result(
            [self._prescription_response(p) for p in items],
            total,
            page,
            size
        )

    async def get_prescription(self, prescription_id: int, doctor_id: int | None = None) -> PrescriptionResponse:
        prescription = await self.prescription_repo.get_by_id(prescription_id)
        if not prescription:
            raise NotFoundException("Prescription not found")
        if doctor_id is not None and prescription.doctor_id != doctor_id:
            raise ForbiddenException("You do not have permission to access this prescription")
        return self._prescription_response(prescription)

    async def update_prescription(self, prescription_id: int, data: PrescriptionUpdate, doctor_id: int, user_id: int) -> PrescriptionResponse:
        prescription = await self.prescription_repo.get_by_id(prescription_id)
        if not prescription:
            raise NotFoundException("Prescription not found")
        if prescription.doctor_id != doctor_id:
            raise ForbiddenException("You do not have permission to modify this prescription")
        
        if data.patient_id is not None:
            prescription.patient_id = data.patient_id
        if data.instructions is not None:
            prescription.instructions = data.instructions
        if data.status is not None:
            prescription.status = data.status

        items = None
        if data.items is not None:
            items = [PrescriptionItem(**item.model_dump()) for item in data.items]

        prescription = await self.prescription_repo.update(prescription, items)
        prescription = await self.prescription_repo.get_by_id(prescription.id)
        await self.audit_repo.create("update", "pharmacy_prescription", user_id=user_id, resource_id=str(prescription.id))
        return self._prescription_response(prescription)

    async def delete_prescription(self, prescription_id: int, doctor_id: int, user_id: int) -> None:
        prescription = await self.prescription_repo.get_by_id(prescription_id)
        if not prescription:
            raise NotFoundException("Prescription not found")
        if prescription.doctor_id != doctor_id:
            raise ForbiddenException("You do not have permission to delete this prescription")
        await self.prescription_repo.soft_delete(prescription)
        await self.audit_repo.create("delete", "pharmacy_prescription", user_id=user_id, resource_id=str(prescription.id))


    def _prescription_response(
        self,
        prescription: Prescription
    ) -> PrescriptionResponse:
        resp = PrescriptionResponse.model_validate(prescription)
        resp.items = [
            PrescriptionItemResponse.model_validate(i)
            for i in prescription.items
        ]
        return resp

    async def get_prescription_by_id(self, prescription_id: int):
        prescription = await self.prescription_repo.get_by_id(prescription_id)

        if not prescription:
            raise NotFoundException("Prescription not found")

        return self._prescription_response(prescription)

    async def update_prescription(self, prescription_id: int, data):
        prescription = await self.prescription_repo.get_by_id(prescription_id)

        if not prescription:
            raise NotFoundException("Prescription not found")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(prescription, key, value)

        prescription = await self.prescription_repo.update(prescription)

        return self._prescription_response(prescription)

    async def delete_prescription(self, prescription_id: int):
        prescription = await self.prescription_repo.get_by_id(prescription_id)

        if not prescription:
            raise NotFoundException("Prescription not found")

        await self.prescription_repo.delete(prescription) 
        
           
    # --- Invoices ---
    async def create_invoice(self, data: PharmacyInvoiceCreate, user_id: int) -> PharmacyInvoiceResponse:
        if data.patient_id is not None:
            patient = await self.patient_repo.get_by_id(data.patient_id)
            if not patient:
                raise NotFoundException("Patient not found")

        if data.prescription_id is not None:
            prescription = await self.prescription_repo.get_by_id(data.prescription_id)
            if not prescription:
                raise NotFoundException("Prescription not found")

        subtotal = 0.0
        invoice_items: list[PharmacyInvoiceItem] = []
        for item_data in data.items:
            medicine = await self.medicine_repo.get_by_id(item_data.medicine_id)
            if not medicine:
                raise NotFoundException(f"Medicine {item_data.medicine_id} not found")
            if medicine.stock_quantity < item_data.quantity:
                raise BadRequestException(f"Insufficient stock for {medicine.name}")
            if medicine.expiry_date and medicine.expiry_date < date.today():
                raise BadRequestException(f"Medicine {medicine.name} has expired")
            unit_price = item_data.unit_price if item_data.unit_price is not None else medicine.unit_price
            line_total = round(item_data.quantity * unit_price, 2)
            subtotal += line_total
            invoice_items.append(PharmacyInvoiceItem(
                medicine_id=item_data.medicine_id,
                quantity=item_data.quantity,
                unit_price=unit_price,
                line_total=line_total,
            ))
            await self.medicine_repo.update_stock(item_data.medicine_id, -item_data.quantity)

        discount_amount = round((subtotal * data.discount_percentage) / 100, 2)
        tax_amount = round((subtotal - discount_amount) * data.tax_percentage / 100, 2)
        gst_amount = tax_amount
        total = round(subtotal - discount_amount + tax_amount, 2)
        invoice = PharmacyInvoice(
            invoice_number=generate_pharmacy_invoice_number(),
            patient_id=data.patient_id,
            prescription_id=data.prescription_id,
            subtotal=subtotal,
            discount_percentage=data.discount_percentage,
            discount_amount=discount_amount,
            tax_percentage=data.tax_percentage,
            tax_amount=tax_amount,
            gst_amount=gst_amount,
            total_amount=total,
            paid_amount=total,
            status="paid",
            created_by=user_id,
        )
        invoice = await self.invoice_repo.create(invoice, invoice_items)
        prescription.status = "completed"
        prescription.dispensed_at = utc_now()
        await self.prescription_repo.update(prescription)
        await self.audit_repo.create("create", "pharmacy_invoice", user_id=user_id, resource_id=str(invoice.id))
        return self._invoice_response(invoice)

    async def list_invoices(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.invoice_repo.list_all(skip=skip, limit=size)
        total = await self.invoice_repo.count_all()
        return build_paginated_result([self._invoice_response(i) for i in items], total, page, size)

    def _invoice_response(self, invoice: PharmacyInvoice) -> PharmacyInvoiceResponse:
        resp = PharmacyInvoiceResponse.model_validate(invoice)
        resp.items = [PharmacyInvoiceItemResponse.model_validate(i) for i in invoice.items]
        return resp
    
    async def get_invoice_by_id(self, invoice_id: int) -> PharmacyInvoiceResponse:
        invoice = await self.invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundException("Pharmacy invoice not found")
        return self._invoice_response(invoice)

    async def update_invoice(self, invoice_id: int, data: PharmacyInvoiceCreate) -> PharmacyInvoiceResponse:
        invoice = await self.invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundException("Pharmacy invoice not found")

        invoice.discount_percentage = data.discount_percentage
        invoice.tax_percentage = data.tax_percentage

        discount_amount = round((invoice.subtotal * data.discount_percentage) / 100, 2)
        tax_amount = round((invoice.subtotal - discount_amount) * data.tax_percentage / 100, 2)

        invoice.discount_amount = discount_amount
        invoice.tax_amount = tax_amount
        invoice.gst_amount = tax_amount
        invoice.total_amount = round(invoice.subtotal - discount_amount + tax_amount, 2)
        invoice.paid_amount = invoice.total_amount

        invoice = await self.invoice_repo.update(invoice)
        return self._invoice_response(invoice)

    async def delete_invoice(self, invoice_id: int) -> None:
        invoice = await self.invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundException("Pharmacy invoice not found")
        await self.invoice_repo.soft_delete(invoice)

    async def download_invoice(self, invoice_id: int):
        invoice = await self.invoice_repo.get_by_id(invoice_id)
        if not invoice:
            raise NotFoundException("Pharmacy invoice not found")
        return self._invoice_response(invoice)

    # --- Suppliers ---
    async def create_supplier(self, data: SupplierCreate, user_id: int) -> SupplierResponse:
        supplier = Supplier(**data.model_dump())
        supplier = await self.supplier_repo.create(supplier)
        await self.audit_repo.create("create", "pharmacy_supplier", user_id=user_id, resource_id=str(supplier.id))
        return SupplierResponse.model_validate(supplier)

    async def list_suppliers(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.supplier_repo.list_all(skip=skip, limit=size)
        total = await self.supplier_repo.count_all()
        return build_paginated_result([SupplierResponse.model_validate(s) for s in items], total, page, size)
    
     
    async def get_supplier(self, supplier_id: int) -> SupplierResponse:
        supplier = await self.supplier_repo.get_by_id(supplier_id)

        if not supplier:
            raise NotFoundException("Supplier not found")

        return SupplierResponse.model_validate(supplier)

    async def update_supplier(self, supplier_id: int, data: SupplierUpdate, user_id: int) -> SupplierResponse:
        supplier = await self.supplier_repo.get_by_id(supplier_id)

        if not supplier:
            raise NotFoundException("Supplier not found")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(supplier, key, value)

        supplier = await self.supplier_repo.update(supplier)
        await self.audit_repo.create(
            "update",
            "pharmacy_supplier",
             user_id=user_id,
             resource_id=str(supplier.id),
    )

        return SupplierResponse.model_validate(supplier)

    async def delete_supplier(self, supplier_id: int, user_id: int) -> None:
        supplier = await self.supplier_repo.get_by_id(supplier_id)

        if not supplier:
            raise NotFoundException("Supplier not found")

        await self.supplier_repo.soft_delete(supplier)
        await self.audit_repo.create(
            "delete",
            "pharmacy_supplier",
            user_id=user_id,
            resource_id=str(supplier.id),
        )
    # --- Purchases ---
    async def create_purchase(self, data: PurchaseCreate, user_id: int) -> PurchaseResponse:
        total = 0.0
        purchase_items: list[PurchaseItem] = []
        for item_data in data.items:
            line_total = round(item_data.quantity * item_data.unit_price, 2)
            total += line_total
            purchase_items.append(PurchaseItem(
                medicine_id=item_data.medicine_id,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                expiry_date=item_data.expiry_date,
                line_total=line_total,
            ))
        purchase = Purchase(
            purchase_number=generate_purchase_number(),
            supplier_id=data.supplier_id,
            total_amount=total,
            ordered_at=utc_now(),
            notes=data.notes,
            created_by=user_id,
        )
        purchase = await self.purchase_repo.create(purchase, purchase_items)
        for item in purchase_items:
            await self.medicine_repo.update_stock(item.medicine_id, item.quantity)
        
        purchase = await self.purchase_repo.get_by_id(purchase.id)
        await self.audit_repo.create("create", "pharmacy_purchase", user_id=user_id, resource_id=str(purchase.id))
        return self._purchase_response(purchase)

    async def list_purchases(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.purchase_repo.list_all(skip=skip, limit=size)
        total = await self.purchase_repo.count_all()
        return build_paginated_result([self._purchase_response(p) for p in items], total, page, size)

    def _purchase_response(self, purchase: Purchase) -> PurchaseResponse:
        resp = PurchaseResponse.model_validate(purchase)
        resp.items = [PurchaseItemResponse.model_validate(i) for i in purchase.items]
        return resp

    async def get_purchase(self, purchase_id: int) -> PurchaseResponse:
        purchase = await self.purchase_repo.get_by_id(purchase_id)

        if not purchase:
            raise NotFoundException("Purchase not found")

        return self._purchase_response(purchase)


    async def update_purchase(
        self,
        purchase_id: int,
        data: PurchaseCreate,
        user_id: int,
    ) -> PurchaseResponse:
        purchase = await self.purchase_repo.get_by_id(purchase_id)

        if not purchase:
            raise NotFoundException("Purchase not found")

        purchase.supplier_id = data.supplier_id
        purchase.notes = data.notes

        purchase = await self.purchase_repo.update(purchase)

        await self.audit_repo.create(
            "update",
            "pharmacy_purchase",
            user_id=user_id,
            resource_id=str(purchase.id),
        )

        purchase = await self.purchase_repo.get_by_id(purchase.id)
        return self._purchase_response(purchase)


    async def delete_purchase(self, purchase_id: int, user_id: int) -> None:
        purchase = await self.purchase_repo.get_by_id(purchase_id)

        if not purchase:
            raise NotFoundException("Purchase not found")

        await self.purchase_repo.soft_delete(purchase)

        await self.audit_repo.create(
            "delete",
            "pharmacy_purchase",
            user_id=user_id,
            resource_id=str(purchase.id),
        )    

    async def get_sales_report(self, period: str = "monthly") -> SalesReport:
        now = utc_now()
        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "yearly":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        data = await self.invoice_repo.get_sales_report(start, now)
        return SalesReport(period=period, top_medicines=[], **data)
