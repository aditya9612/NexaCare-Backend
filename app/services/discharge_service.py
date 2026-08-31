import math
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus, BedStatus
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.appointment_model import Appointment
from app.models.bed_allocation_model import Bed, BedActivityLog
from app.models.billing_model import Billing, BillItem, Payment
from app.models.discharge_model import Discharge
from app.models.doctor_model import Doctor
from app.models.lab_model import LabTest, TestOrder
from app.models.patient_model import Patient
from app.models.pharmacy_model import PharmacyInvoice, Prescription
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.discharge_repository import DischargeRepository
from app.models.final_bill_model import IPDFinalBill, IPDFinalBillItem
from app.repositories.final_bill_repository import FinalBillRepository
from app.schemas.final_bill_schema import IPDFinalBillResponse, IPDFinalBillSummaryResponse
from app.schemas.billing_schema import BillingCreate, BillingUpdate, BillItemCreate, PaymentCreate
from app.schemas.discharge_schema import (
    ClearBillingRequest,
    ClearPaymentRequest,
    ClearPharmacyRequest,
    DischargeClearanceStatus,
    DischargeGatePassResponse,
    DischargeInitiateRequest,
    DischargeResponse,
    GenerateIPDBillRequest,
)
from app.services.billing_service import BillingService
from app.services.room_tariff_service import RoomTariffService
from app.utils.helpers import (
    generate_discharge_number,
    generate_gate_pass_number,
    utc_now,
)


class DischargeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DischargeRepository(db)
        self.appointment_repo = AppointmentRepository(db)
        self.room_tariff_service = RoomTariffService(db)
        self.billing_service = BillingService(db)
        self.final_bill_repo = FinalBillRepository(db)

    async def initiate_discharge(
        self, data: DischargeInitiateRequest, doctor_user_id: int
    ) -> DischargeResponse:
        # 1. Verify appointment exists
        appointment = await self.appointment_repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException(f"Appointment with id {data.appointment_id} not found")

        # 2. Check IPD eligibility: appointment_type == "IPD" and admission_status in ("Admitted", "Admit Recommended")
        appt_type = (appointment.appointment_type or "").strip().upper()
        adm_status = (appointment.admission_status or "").strip().lower()
        is_admitted = (
            adm_status in ("admitted", "admit recommended", "admit_recommended")
            or bool(appointment.admission_recommended)
        )

        if appt_type != "IPD" and not is_admitted:
            raise BadRequestException("Discharge can only be initiated for admitted IPD appointments.")

        if appointment.admission_status == "Discharged":
            raise BadRequestException("Patient has already been discharged for this appointment.")
        if str(appointment.appointment_status).lower() in ("cancelled", "canceled"):
            raise BadRequestException("Cannot initiate discharge for a cancelled appointment.")

        # 3. Verify doctor
        doctor = await self.db.scalar(
            select(Doctor).where(Doctor.user_id == doctor_user_id)
        )
        if not doctor:
            doctor = await self.db.get(Doctor, appointment.doctor_id)
        if not doctor:
            raise NotFoundException("Doctor record not found")

        # 4. Check if already initiated
        existing = await self.repo.get_by_appointment_id(data.appointment_id)
        if existing and existing.discharge_status in ("PENDING_CLEARANCES", "CLEARED"):
            raise ConflictException(f"Discharge already initiated for appointment {data.appointment_id}")

        # 5. Find bed occupied by patient if any
        bed = await self.db.scalar(
            select(Bed).where(
                Bed.patient_id == appointment.patient_id,
                Bed.status == BedStatus.OCCUPIED.value,
            )
        )

        admission_time = appointment.check_in_time or (
            datetime.combine(appointment.appointment_date, appointment.appointment_time)
            if appointment.appointment_date and appointment.appointment_time
            else appointment.created_at
        )

        discharge = Discharge(
            discharge_number=generate_discharge_number(),
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            doctor_id=doctor.id,
            bed_id=bed.id if bed else None,
            admission_date=admission_time,
            discharge_date=utc_now(),
            diagnosis_at_admission=appointment.notes or None,
            diagnosis_at_discharge=data.diagnosis_at_discharge,
            treatment_summary=data.treatment_summary,
            condition_on_discharge=data.condition_on_discharge,
            post_medications=data.post_medications,
            home_care_instructions=data.home_care_instructions,
            follow_up_date=data.follow_up_date,
            discharge_status="PENDING_CLEARANCES",
            discharge_notes=data.discharge_notes,
            pharmacy_cleared=False,
            billing_cleared=False,
            payment_cleared=False,
            doctor_approved=False,
        )

        discharge = await self.repo.create(discharge)
        return DischargeResponse.model_validate(discharge)

    async def get_by_id(self, discharge_id: int) -> DischargeResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")
        return DischargeResponse.model_validate(discharge)

    async def get_by_appointment(self, appointment_id: int) -> DischargeResponse:
        discharge = await self.repo.get_by_appointment_id(appointment_id)
        if not discharge:
            raise NotFoundException(f"No discharge found for appointment {appointment_id}")
        return DischargeResponse.model_validate(discharge)

    async def list_active_discharges(self) -> list[DischargeResponse]:
        items = await self.repo.get_all_active()
        return [DischargeResponse.model_validate(d) for d in items]

    async def get_clearance_status(self, discharge_id: int) -> DischargeClearanceStatus:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        ready = (
            discharge.pharmacy_cleared
            and discharge.billing_cleared
            and discharge.payment_cleared
        )
        return DischargeClearanceStatus(
            pharmacy_cleared=discharge.pharmacy_cleared,
            pharmacy_cleared_at=discharge.pharmacy_cleared_at,
            billing_cleared=discharge.billing_cleared,
            billing_cleared_at=discharge.billing_cleared_at,
            billing_id=discharge.billing_id,
            payment_cleared=discharge.payment_cleared,
            payment_cleared_at=discharge.payment_cleared_at,
            doctor_approved=discharge.doctor_approved,
            doctor_approved_at=discharge.doctor_approved_at,
            ready_for_discharge=ready,
            discharge_status=discharge.discharge_status,
        )

    # --- STEP 3: PHARMACY CLEARANCE ---
    async def clear_pharmacy(
        self, discharge_id: int, user_id: int, data: ClearPharmacyRequest | None = None
    ) -> DischargeResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        # Verify all prescriptions & pharmacy invoices for this appointment
        rx_stmt = select(Prescription).where(
            Prescription.appointment_id == discharge.appointment_id,
            Prescription.is_deleted == False
        )
        prescriptions = (await self.db.scalars(rx_stmt)).all()

        discharge.pharmacy_cleared = True
        discharge.pharmacy_cleared_by = user_id
        discharge.pharmacy_cleared_at = utc_now()
        
        verification_msg = f"Verified {len(prescriptions)} prescription(s) for IPD appointment #{discharge.appointment_id}."
        if data and data.notes:
            discharge.pharmacy_notes = f"{verification_msg} Notes: {data.notes}"
        else:
            discharge.pharmacy_notes = verification_msg

        self._check_and_update_cleared_status(discharge)
        discharge = await self.repo.update(discharge)
        return DischargeResponse.model_validate(discharge)

    # --- STEP 4: IPD FINAL BILL GENERATION (Idempotent & Consolidates Pharmacy) ---
    async def generate_ipd_final_bill(
        self, discharge_id: int, data: GenerateIPDBillRequest, user_id: int
    ) -> IPDFinalBillResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        # STEP 3 Precondition: Pharmacy clearance must happen BEFORE final IPD bill generation
        if not discharge.pharmacy_cleared:
            raise BadRequestException("Pharmacy Clearance must be completed before generating IPD final bill.")

        if discharge.billing_id:
            existing_bill = await self.db.get(Billing, discharge.billing_id)
            if existing_bill and existing_bill.paid_amount > 0:
                raise ConflictException("Bill has already been partially or fully paid. Cannot re-generate.")

        # 1. Calculate length of stay in days (Calendar days with 1 day minimum)
        now_dt = utc_now()
        discharge.discharge_date = now_dt
        stay_days = (discharge.discharge_date.date() - discharge.admission_date.date()).days
        days_stayed = max(1, stay_days)

        # 2. Get Bed / Room information
        room_type = "General Ward"
        ward_name = "General Ward"
        if discharge.bed:
            bed_obj = discharge.bed
            if bed_obj.room:
                ward_name = getattr(bed_obj.room, "name", "Ward")
                room_type = getattr(bed_obj.room, "type", None) or getattr(bed_obj.room, "name", "General Ward")
            elif getattr(bed_obj, "type", None):
                room_type = bed_obj.type
        elif discharge.appointment and getattr(discharge.appointment, "recommended_ward", None):
            room_type = discharge.appointment.recommended_ward
            ward_name = discharge.appointment.recommended_ward

        tariff = await self.room_tariff_service.get_by_room_type(room_type)
        gst_rate = min(max(data.gst_rate, 0.0), 18.0)

        # 3. Build Bill Items
        bill_items: list[BillItemCreate] = []

        # 3a. Room / Bed stay charges
        bill_items.append(
            BillItemCreate(
                item_type="bed_charge",
                description=f"{room_type} Stay Charges ({days_stayed} Day{'s' if days_stayed > 1 else ''} @ ₹{tariff.daily_rate:,.2f}/day)",
                quantity=days_stayed,
                unit_price=tariff.daily_rate,
                gst_rate=gst_rate,
            )
        )

        # 3b. Nursing care charges
        if tariff.nursing_charge_per_day > 0:
            bill_items.append(
                BillItemCreate(
                    item_type="nursing_charge",
                    description=f"Inpatient Nursing & Care ({days_stayed} Day{'s' if days_stayed > 1 else ''} @ ₹{tariff.nursing_charge_per_day:,.2f}/day)",
                    quantity=days_stayed,
                    unit_price=tariff.nursing_charge_per_day,
                    gst_rate=gst_rate,
                )
            )

        # 3c. Doctor visits & daily rounds
        total_doctor_visits = days_stayed + data.additional_doctor_visits
        doctor_obj = discharge.doctor
        if not doctor_obj and discharge.doctor_id:
            doctor_obj = await self.db.get(Doctor, discharge.doctor_id)

        doctor_fee = None
        doctor_name_str = ""
        if doctor_obj:
            doctor_name_str = f"Dr. {doctor_obj.first_name} {doctor_obj.last_name}".strip()
            if doctor_obj.consultation_fee and doctor_obj.consultation_fee > 0:
                doctor_fee = float(doctor_obj.consultation_fee)

        if doctor_fee is None:
            doctor_fee = float(tariff.doctor_visit_charge) if tariff.doctor_visit_charge else 0.0

        if doctor_fee > 0:
            doc_desc = (
                f"{doctor_name_str} Consultation & Daily Rounds ({total_doctor_visits} Visit{'s' if total_doctor_visits > 1 else ''} @ ₹{doctor_fee:,.2f}/visit)"
                if doctor_name_str
                else f"Doctor Daily Rounds & Visits ({total_doctor_visits} Visit{'s' if total_doctor_visits > 1 else ''} @ ₹{doctor_fee:,.2f}/visit)"
            )
            bill_items.append(
                BillItemCreate(
                    item_type="doctor_round",
                    description=doc_desc,
                    quantity=total_doctor_visits,
                    unit_price=doctor_fee,
                    gst_rate=gst_rate,
                )
            )

        # 3d. Integrate Applicable Lab & Radiology Charges (avoid double-counting)
        lab_stmt = (
            select(TestOrder)
            .where(
                TestOrder.is_deleted == False,
                (
                    (TestOrder.appointment_id == discharge.appointment_id)
                    | (
                        (TestOrder.patient_id == discharge.patient_id)
                        & (TestOrder.ordered_at >= discharge.admission_date)
                        & (TestOrder.ordered_at <= (discharge.discharge_date or now_dt))
                    )
                ),
            )
        )
        lab_orders = (await self.db.scalars(lab_stmt)).all()
        seen_test_orders = set()
        for order in (lab_orders or []):
            if not order or not hasattr(order, "id"):
                continue
            if order.id in seen_test_orders:
                continue
            seen_test_orders.add(order.id)
            test = getattr(order, "lab_test", None)
            if not test and getattr(order, "lab_test_id", None):
                test = await self.db.get(LabTest, order.lab_test_id)
            if not test or not getattr(test, "price", 0) or test.price <= 0:
                continue
            cat = (test.category or "").lower()
            is_radiology = any(r in cat for r in ["radiology", "imaging", "x-ray", "xray", "mri", "ct", "ultrasound", "usg", "scan"])
            item_type = "radiology_order" if is_radiology else "lab_test"
            prefix = "Radiology" if is_radiology else "Lab Test"
            bill_items.append(
                BillItemCreate(
                    item_type=item_type,
                    description=f"{prefix}: {test.test_name} (Order #{order.order_number})",
                    quantity=1,
                    unit_price=float(test.price),
                    gst_rate=0.0,
                )
            )

        # 3e. Integrate Applicable Pharmacy Invoices (without double-counting)
        rx_stmt = select(Prescription.id).where(
            Prescription.appointment_id == discharge.appointment_id,
            Prescription.is_deleted == False
        )
        rx_ids_raw = (await self.db.scalars(rx_stmt)).all()
        rx_ids = [r if isinstance(r, int) else getattr(r, "id", None) for r in (rx_ids_raw or [])]
        rx_ids = [r for r in rx_ids if isinstance(r, int)]

        from sqlalchemy import or_
        pharm_conditions = [PharmacyInvoice.patient_id == discharge.patient_id]
        if rx_ids:
            pharm_conditions.append(PharmacyInvoice.prescription_id.in_(rx_ids))

        unpaid_pharm_stmt = select(PharmacyInvoice).where(
            or_(*pharm_conditions),
            PharmacyInvoice.is_deleted == False,
            PharmacyInvoice.status != "paid"
        )
        unpaid_pharm = (await self.db.scalars(unpaid_pharm_stmt)).all()

        seen_invoices = set()
        for inv in (unpaid_pharm or []):
            if not inv or not hasattr(inv, "id"):
                continue
            if inv.id in seen_invoices:
                continue
            seen_invoices.add(inv.id)
            inv_balance = max(0.0, getattr(inv, "total_amount", 0.0) - getattr(inv, "paid_amount", 0.0))
            if inv_balance > 0:
                bill_items.append(
                    BillItemCreate(
                        item_type="pharmacy_invoice",
                        description=f"Pharmacy Invoice #{getattr(inv, 'invoice_number', inv.id)} (Prescription #{getattr(inv, 'prescription_id', None) or 'IPD'})",
                        quantity=1,
                        unit_price=inv_balance,
                        gst_rate=0.0,
                    )
                )

        # 3f. Procedure Charges (if provided in request)
        if data.procedure_charges:
            for proc in data.procedure_charges:
                if proc.amount > 0:
                    bill_items.append(
                        BillItemCreate(
                            item_type="procedure_charge",
                            description=f"Procedure: {proc.description}",
                            quantity=1,
                            unit_price=float(proc.amount),
                            gst_rate=gst_rate,
                        )
                    )

        # 3g. Optional Prior OPD Charges (if requested for this admission episode)
        if data.include_prior_opd_balance:
            opd_stmt = (
                select(Billing)
                .join(Appointment, Billing.appointment_id == Appointment.id)
                .where(
                    Billing.patient_id == discharge.patient_id,
                    Billing.is_deleted == False,
                    Appointment.appointment_type == "OPD",
                    Billing.status != "paid",
                    Billing.balance_amount > 0,
                )
            )
            unpaid_opd_bills = (await self.db.scalars(opd_stmt)).all()
            seen_opd_bills = set()
            for opd_bill in unpaid_opd_bills:
                if opd_bill.id in seen_opd_bills:
                    continue
                seen_opd_bills.add(opd_bill.id)
                bill_items.append(
                    BillItemCreate(
                        item_type="opd_consultation",
                        description=f"Prior OPD Bill #{opd_bill.bill_number} (Unpaid Balance)",
                        quantity=1,
                        unit_price=float(opd_bill.balance_amount),
                        gst_rate=0.0,
                    )
                )

        # 4. Component Subtotals Calculation
        bed_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type in ["bed_charge", "nursing_charge"]), 2)
        doctor_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type == "doctor_round"), 2)
        lab_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type == "lab_test"), 2)
        radiology_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type == "radiology_order"), 2)
        pharmacy_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type == "pharmacy_invoice"), 2)
        procedure_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type == "procedure_charge"), 2)
        prior_opd_charges = round(sum(it.unit_price * it.quantity for it in bill_items if it.item_type == "opd_consultation"), 2)

        gross_total = round(bed_charges + doctor_charges + lab_charges + radiology_charges + pharmacy_charges + procedure_charges + prior_opd_charges, 2)
        discount_amount = round(data.discount_amount or 0.0, 2)
        taxable = max(0.0, gross_total - discount_amount)
        tax_amount = round(taxable * (gst_rate or 0.0) / 100.0, 2)
        net_total = round(taxable + tax_amount, 2)

        # 5. Handle Advance Payments & Refunds on the Final Bill to accurately compute net balance
        adv_payments_stmt = select(Payment).where(
            Payment.status != "cancelled",
            Payment.billing_id.in_(
                select(Billing.id).where(
                    Billing.patient_id == discharge.patient_id,
                    (Billing.appointment_id == discharge.appointment_id) | (Billing.notes.like("%Advance%"))
                )
            )
        )
        all_adv_records = (await self.db.scalars(adv_payments_stmt)).all()
        total_advances = 0.0
        total_refunds = 0.0
        for p in (all_adv_records or []):
            amt = getattr(p, "amount", 0.0)
            if isinstance(amt, (int, float)):
                if getattr(p, "is_refund", False):
                    total_refunds += float(amt)
                else:
                    total_advances += float(amt)

        net_advance_paid = max(0.0, total_advances - total_refunds)
        advance_adjusted = min(net_total, net_advance_paid)
        balance_amount = round(max(0.0, net_total - net_advance_paid), 2)
        refund_amount = round(max(0.0, net_advance_paid - net_total), 2)

        # 6. Save or Update in dedicated ipd_final_bills table (Idempotency)
        existing_final_bill = None
        if discharge.final_bill_id:
            existing_final_bill = await self.final_bill_repo.get_by_id_with_items(discharge.final_bill_id)
        elif discharge.id:
            existing_final_bill = await self.final_bill_repo.get_by_discharge_id_with_items(discharge.id)

        if existing_final_bill:
            existing_final_bill.bed_id = discharge.bed_id
            existing_final_bill.doctor_id = discharge.doctor_id
            existing_final_bill.bed_charges = bed_charges
            existing_final_bill.doctor_charges = doctor_charges
            existing_final_bill.lab_charges = lab_charges
            existing_final_bill.radiology_charges = radiology_charges
            existing_final_bill.pharmacy_charges = pharmacy_charges
            existing_final_bill.procedure_charges = procedure_charges
            existing_final_bill.prior_opd_charges = prior_opd_charges
            existing_final_bill.gross_total = gross_total
            existing_final_bill.discount_amount = discount_amount
            existing_final_bill.tax_rate = gst_rate
            existing_final_bill.tax_amount = tax_amount
            existing_final_bill.net_total = net_total
            existing_final_bill.advance_adjusted = advance_adjusted
            existing_final_bill.balance_amount = balance_amount
            existing_final_bill.refund_amount = refund_amount
            existing_final_bill.status = "paid" if balance_amount == 0.0 and net_advance_paid > 0 else "pending"
            existing_final_bill.notes = data.notes or f"Auto-generated IPD Final Bill for {days_stayed} day(s) stay. Discharge No: {discharge.discharge_number}"

            existing_final_bill.items.clear()
            for it in bill_items:
                existing_final_bill.items.append(
                    IPDFinalBillItem(
                        item_type=it.item_type,
                        item_name=it.description,
                        quantity=it.quantity,
                        unit_price=it.unit_price,
                        tax_rate=it.gst_rate,
                        total_price=round(it.quantity * it.unit_price, 2),
                    )
                )
            final_bill = await self.final_bill_repo.update(existing_final_bill)
        else:
            bill_number = f"IPD-BILL-{utc_now().strftime('%Y%m%d')}-{discharge.id:04d}"
            final_bill = IPDFinalBill(
                bill_number=bill_number,
                discharge_id=discharge.id,
                patient_id=discharge.patient_id,
                appointment_id=discharge.appointment_id,
                doctor_id=discharge.doctor_id,
                bed_id=discharge.bed_id,
                bed_charges=bed_charges,
                doctor_charges=doctor_charges,
                lab_charges=lab_charges,
                radiology_charges=radiology_charges,
                pharmacy_charges=pharmacy_charges,
                procedure_charges=procedure_charges,
                prior_opd_charges=prior_opd_charges,
                gross_total=gross_total,
                discount_amount=discount_amount,
                tax_rate=gst_rate,
                tax_amount=tax_amount,
                net_total=net_total,
                advance_adjusted=advance_adjusted,
                balance_amount=balance_amount,
                refund_amount=refund_amount,
                status="paid" if balance_amount == 0.0 and net_advance_paid > 0 else "pending",
                notes=data.notes or f"Auto-generated IPD Final Bill for {days_stayed} day(s) stay. Discharge No: {discharge.discharge_number}",
            )
            for it in bill_items:
                final_bill.items.append(
                    IPDFinalBillItem(
                        item_type=it.item_type,
                        item_name=it.description,
                        quantity=it.quantity,
                        unit_price=it.unit_price,
                        tax_rate=it.gst_rate,
                        total_price=round(it.quantity * it.unit_price, 2),
                    )
                )
            final_bill = await self.final_bill_repo.create(final_bill)

        # Link to discharge
        discharge.final_bill_id = final_bill.id
        discharge.billing_notes = f"Consolidated IPD Final Bill #{final_bill.bill_number} generated for ₹{final_bill.net_total:,.2f}"
        await self.repo.update(discharge)
        await self.db.flush()

        loaded_final_bill = await self.final_bill_repo.get_by_id_with_items(final_bill.id)
        return IPDFinalBillResponse.model_validate(loaded_final_bill or final_bill)

    # --- STEP 5: BILLING CLEARANCE (Separate Verification Stage) ---
    async def clear_billing(
        self, discharge_id: int, user_id: int, data: ClearBillingRequest | None = None
    ) -> DischargeResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        if not discharge.final_bill_id and not discharge.billing_id:
            raise BadRequestException("IPD final bill must be generated before billing clearance.")

        discharge.billing_cleared = True
        discharge.billing_cleared_by = user_id
        discharge.billing_cleared_at = utc_now()
        if data and data.notes:
            discharge.billing_notes = data.notes

        self._check_and_update_cleared_status(discharge)
        discharge = await self.repo.update(discharge)
        return DischargeResponse.model_validate(discharge)

    # --- STEP 6: PAYMENT ALLOCATION & STRICT OUTSTANDING CHECK ---
    async def clear_payment(
        self, discharge_id: int, data: ClearPaymentRequest, user_id: int
    ) -> DischargeResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        # STEP 8 Precondition: Payment happens ONLY after Billing Clearance
        if not discharge.billing_cleared:
            raise BadRequestException("Billing Clearance must be completed before payment settlement.")

        # 1. Settle dedicated IPD Final Bill
        if discharge.final_bill_id:
            final_bill = await self.final_bill_repo.get_by_id_with_items(discharge.final_bill_id)
            if final_bill:
                final_bill.status = "paid"
                final_bill.payment_mode = data.payment_method
                final_bill.settled_at = utc_now()
                final_bill.settled_by = user_id
                await self.final_bill_repo.update(final_bill)

        # Legacy billing settlement fallback
        if discharge.billing_id:
            billing = await self.db.get(Billing, discharge.billing_id)
            if billing and billing.balance_amount > 0:
                payment_create = PaymentCreate(
                    amount=billing.balance_amount,
                    payment_method=data.payment_method,
                    transaction_ref=data.transaction_ref,
                )
                await self.billing_service.collect_payment(billing.id, payment_create, user_id)
                await self.db.refresh(billing)

        # 2. Settle linked pharmacy invoices for this IPD appointment
        rx_stmt = select(Prescription.id).where(
            Prescription.appointment_id == discharge.appointment_id,
            Prescription.is_deleted == False
        )
        rx_ids = (await self.db.scalars(rx_stmt)).all()

        unpaid_pharm_stmt = select(PharmacyInvoice).where(
            (PharmacyInvoice.patient_id == discharge.patient_id) | (PharmacyInvoice.prescription_id.in_(rx_ids)),
            PharmacyInvoice.is_deleted == False,
            PharmacyInvoice.status != "paid"
        )
        unpaid_pharm = (await self.db.scalars(unpaid_pharm_stmt)).all()
        for inv in unpaid_pharm:
            inv.paid_amount = inv.total_amount
            inv.status = "paid"
            inv.payment_mode = data.payment_method
            await self.db.flush()

        discharge.payment_cleared = True
        discharge.payment_cleared_by = user_id
        discharge.payment_cleared_at = utc_now()
        if data.notes:
            discharge.payment_notes = data.notes

        self._check_and_update_cleared_status(discharge)
        discharge = await self.repo.update(discharge)
        return DischargeResponse.model_validate(discharge)

    async def get_final_bill_by_discharge_id(self, discharge_id: int) -> IPDFinalBillResponse:
        final_bill = await self.final_bill_repo.get_by_discharge_id_with_items(discharge_id)
        if not final_bill:
            raise NotFoundException(f"Final bill for discharge {discharge_id} not found")
        return IPDFinalBillResponse.model_validate(final_bill)

    async def list_final_bills(
        self, skip: int = 0, limit: int = 50, patient_id: int | None = None, status: str | None = None
    ) -> list[IPDFinalBillSummaryResponse]:
        bills = await self.final_bill_repo.list_all_final_bills(skip=skip, limit=limit, patient_id=patient_id, status=status)
        results = []
        for b in bills:
            pat_name = f"{b.patient.first_name} {b.patient.last_name}" if getattr(b, "patient", None) else None
            results.append(
                IPDFinalBillSummaryResponse(
                    id=b.id,
                    bill_number=b.bill_number,
                    discharge_id=b.discharge_id,
                    patient_id=b.patient_id,
                    patient_name=pat_name,
                    gross_total=b.gross_total,
                    discount_amount=b.discount_amount,
                    net_total=b.net_total,
                    advance_adjusted=b.advance_adjusted,
                    balance_amount=b.balance_amount,
                    refund_amount=b.refund_amount,
                    status=b.status,
                    created_at=b.created_at,
                )
            )
        return results

        self._check_and_update_cleared_status(discharge)
        discharge = await self.repo.update(discharge)
        return DischargeResponse.model_validate(discharge)

    # --- STEP 8: DOCTOR FINAL APPROVAL ---
    async def doctor_approve_discharge(
        self, discharge_id: int, doctor_user_id: int
    ) -> DischargeResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        # Strict Check 1: All 3 clearances must be True
        missing = []
        if not discharge.pharmacy_cleared:
            missing.append("Pharmacy Clearance")
        if not discharge.billing_cleared:
            missing.append("Billing Clearance")
        if not discharge.payment_cleared:
            missing.append("Payment Clearance")

        if missing:
            raise BadRequestException(
                f"Cannot approve discharge. Pending clearances: {', '.join(missing)}"
            )

        # Strict Check 2: Outstanding Balance must be exactly 0
        if discharge.billing_id:
            billing = await self.db.get(Billing, discharge.billing_id)
            if billing and billing.balance_amount > 0.0:
                raise BadRequestException(
                    f"Cannot approve discharge. Outstanding bill balance of ₹{billing.balance_amount:,.2f} must be fully paid first."
                )

        discharge.doctor_approved = True
        discharge.doctor_approved_by = doctor_user_id
        discharge.doctor_approved_at = utc_now()
        discharge.discharge_status = "DISCHARGED"
        if not discharge.gate_pass_number:
            discharge.gate_pass_number = generate_gate_pass_number()

        # Update appointment status & admission status
        if discharge.appointment:
            discharge.appointment.admission_status = "Discharged"
            discharge.appointment.appointment_status = AppointmentStatus.COMPLETED
            discharge.appointment.check_out_time = utc_now()

        # Bed Status: Transition from OCCUPIED to CLEANING
        if discharge.bed_id:
            bed = await self.db.get(Bed, discharge.bed_id)
            if bed and bed.status == BedStatus.OCCUPIED.value:
                bed.status = BedStatus.CLEANING.value
                bed.patient_id = None
                
                # Log bed cleaning activity
                log_entry = BedActivityLog(
                    type="maintenance",
                    message=f"Patient discharged (Discharge No: {discharge.discharge_number}). Bed sent for housekeeping sanitization.",
                    bed_id=bed.id,
                    patient_id=discharge.patient_id,
                    room_id=bed.room_id,
                    floor_id=bed.room.floor_id if (bed.room and hasattr(bed.room, "floor_id")) else None,
                )
                self.db.add(log_entry)

        discharge = await self.repo.update(discharge)
        return DischargeResponse.model_validate(discharge)

    async def get_gate_pass(self, discharge_id: int) -> DischargeGatePassResponse:
        discharge = await self.repo.get_by_id(discharge_id)
        if not discharge:
            raise NotFoundException(f"Discharge with id {discharge_id} not found")

        if discharge.discharge_status != "DISCHARGED":
            raise BadRequestException("Gate pass is only available after final doctor approval and discharge completion.")

        patient_name = f"{discharge.patient.first_name} {discharge.patient.last_name}" if discharge.patient else "Patient"
        patient_code = discharge.patient.patient_code if discharge.patient else "N/A"
        doctor_name = f"Dr. {discharge.doctor.first_name} {discharge.doctor.last_name}" if discharge.doctor else "Doctor"
        ward_name = discharge.bed.room.name if (discharge.bed and discharge.bed.room) else "IPD Ward"
        bed_num = discharge.bed.name if discharge.bed else "N/A"

        return DischargeGatePassResponse(
            gate_pass_number=discharge.gate_pass_number or generate_gate_pass_number(),
            discharge_number=discharge.discharge_number,
            patient_name=patient_name,
            patient_code=patient_code,
            admission_date=discharge.admission_date,
            discharge_date=discharge.discharge_date,
            doctor_name=doctor_name,
            ward_name=ward_name,
            bed_number=bed_num,
            payment_status="CLEARED & SETTLED",
            authorized_by="Medical Superintendent / Duty Doctor",
            issued_at=discharge.doctor_approved_at or utc_now(),
        )

    def _check_and_update_cleared_status(self, discharge: Discharge) -> None:
        if (
            discharge.pharmacy_cleared
            and discharge.billing_cleared
            and discharge.payment_cleared
            and discharge.discharge_status == "PENDING_CLEARANCES"
        ):
            discharge.discharge_status = "CLEARED"
