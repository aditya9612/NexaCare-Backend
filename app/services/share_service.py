import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import NotFoundException, BadRequestException
from app.core.constants import LabReportStatus
from app.utils.email_sender import send_email
from app.schemas.share_schema import ShareEmailRequest


class ShareService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def dispatch_share(self, data: ShareEmailRequest, current_user) -> None:
        if data.purpose == "lab_report":
            await self._share_lab_report(data.resource_id, data.custom_email, current_user)
        else:
            raise BadRequestException(f"Unsupported sharing purpose: {data.purpose}")

    async def _share_lab_report(self, resource_id: int, custom_email: str | None, current_user) -> None:
        from app.models.lab_model import LabReport, TestResult
        from app.repositories.lab_repository import LabReportRepository, TestOrderRepository
        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        from app.utils.pdf_generator import generate_lab_report_html
        from app.utils.helpers import utc_now

        # 1. Fetch the lab report
        report_repo = LabReportRepository(self.db)
        report = await report_repo.get_by_id(resource_id)
        if not report:
            raise NotFoundException(f"Lab report with ID {resource_id} not found")

        # 2. Check if the report is approved
        if report.status != LabReportStatus.APPROVED:
            raise BadRequestException("Cannot share a lab report that has not been approved.")

        # 3. Fetch related test order and patient details
        order_repo = TestOrderRepository(self.db)
        order = await order_repo.get_by_id(report.test_order_id)
        if not order:
            raise NotFoundException("Associated test order not found")

        patient = await self.db.get(Patient, order.patient_id)
        if not patient:
            raise NotFoundException("Associated patient record not found")

        recipient_email = custom_email or patient.email
        if not recipient_email:
            raise BadRequestException("No email address available for the patient. Please provide a custom_email.")

        # 4. Resolve and verify PDF file path
        def resolve_disk_path(path_str: str | None) -> str | None:
            if not path_str:
                return None
            p = path_str.replace("\\", "/")
            if p.startswith("/"):
                p = p.lstrip("/")
            if p.startswith("uploads/"):
                return os.path.join("app", p)
            return p

        disk_path = resolve_disk_path(report.report_path)
        need_generation = False
        if not disk_path or not report.report_path.endswith(".pdf") or not os.path.exists(disk_path):
            need_generation = True

        # 5. Generate PDF if missing
        if need_generation:
            doctor = await self.db.get(Doctor, order.doctor_id) if order.doctor_id else None
            result_objs = await self.db.execute(select(TestResult).where(TestResult.test_order_id == order.id))
            results = list(result_objs.scalars().all())

            columns = ["Parameter", "Result Value", "Unit", "Normal Range", "Is Critical"]
            rows = [
                [
                    r.parameter_name,
                    r.result_value,
                    r.unit or "-",
                    r.normal_range or "-",
                    "Yes" if r.is_critical else "No"
                ]
                for r in results
            ]

            report_data = {
                "order_number": order.order_number,
                "status": report.status,
                "generated_at": report.approved_at.strftime("%Y-%m-%d %H:%M:%S") if report.approved_at else utc_now().strftime("%Y-%m-%d %H:%M:%S"),
                "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Unknown",
                "patient_code": patient.patient_code if patient else "Unknown",
                "patient_gender": patient.gender if patient else "Unknown",
                "patient_dob": str(patient.dob) if patient and patient.dob else "Unknown",
                "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "",
                "doctor_code": doctor.doctor_code if doctor else "",
                "test_name": order.lab_test.test_name if order.lab_test else "Unknown",
                "test_category": order.lab_test.category if order.lab_test else "Unknown",
                "summary": report.summary or "",
                "columns": columns,
                "rows": rows,
            }

            path = await generate_lab_report_html(
                report.report_number,
                report_data,
            )
            report.report_path = path
            await report_repo.update(report)
            disk_path = resolve_disk_path(report.report_path)

        if not disk_path or not os.path.exists(disk_path):
            raise NotFoundException("Report PDF file could not be generated or found on the server.")

        # 6. Send the Email
        subject = f"Lab Report: {report.report_number} - {order.lab_test.test_name if order.lab_test else 'Test Result'}"
        body = f"""
        <h3>Hello {patient.first_name} {patient.last_name},</h3>
        <p>Your lab report for test order <b>{order.order_number}</b> has been approved and is attached to this email.</p>
        <p><b>Summary / Remarks:</b> {report.summary or 'No summary remarks provided.'}</p>
        <p>Regards,<br/><b>NexaCare HMS Team</b></p>
        """

        success = await send_email(
            to=recipient_email,
            subject=subject,
            body=body,
            attachment_path=disk_path
        )
        if not success:
            raise BadRequestException("Failed to dispatch report email. Please check SMTP server settings.")
