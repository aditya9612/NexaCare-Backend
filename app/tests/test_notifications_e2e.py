import uuid
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.notification_model import Notification
from app.models.user_model import User
from app.repositories.notification_repository import NotificationRepository
from app.services.notification_service import NotificationService
from app.tasks.notification_tasks import send_email_async, send_sms_async
from app.websocket.notification_socket import notification_manager


from app.models.role_model import Role

import uuid
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.notification_model import Notification
from app.models.user_model import User
from app.models.role_model import Role
from app.repositories.notification_repository import NotificationRepository
from app.services.notification_service import NotificationService
from app.tasks.notification_tasks import send_email_async, send_sms_async
from app.websocket.notification_socket import notification_manager


@pytest.mark.asyncio
async def test_notifications_all_features_e2e():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        # 1. Create or fetch role
        role_res = await session.execute(select(Role).limit(1))
        role = role_res.scalar_one_or_none()
        if not role:
            role = Role(name=f"Role_{uid}", description="Test Role")
            session.add(role)
            await session.commit()
            await session.refresh(role)

        # 2. Create a test user
        user = User(
            user_code=f"USR_{uid}_1",
            email=f"notif_user_{uid}@example.com",
            hashed_password="hashed_test_password",
            full_name=f"Notif User {uid}",
            role_id=role.id,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        repo = NotificationRepository(session)

        # 3. Create notifications via repository
        notif1 = Notification(
            user_id=user.id,
            title="Appointment Confirmed",
            message="Your appointment APPT-1001 is confirmed.",
            notification_type="APPOINTMENT_CONFIRMATION",
            reference_type="appointment",
            reference_id=101,
            priority="HIGH",
        )
        notif1 = await repo.create(notif1)

        notif2 = Notification(
            user_id=user.id,
            title="Invoice Generated",
            message="Invoice INV-2002 of $150 generated.",
            notification_type="INVOICE_GENERATED",
            reference_type="billing",
            reference_id=202,
            priority="NORMAL",
        )
        notif2 = await repo.create(notif2)

        assert notif1.id is not None
        assert notif2.id is not None
        assert notif1.is_read is False

        service = NotificationService(session)

        # 4. Test listing user notifications
        res_list = await service.list_user_notifications(user_id=user.id, page=1, limit=10)
        assert res_list.total >= 2
        retrieved_ids = [n.id for n in res_list.items]
        assert notif1.id in retrieved_ids
        assert notif2.id in retrieved_ids

        # 5. Test unread count
        unread_res = await service.get_unread_count(user_id=user.id)
        assert unread_res.unread_count >= 2

        # 6. Test category counts
        cat_counts = await service.get_category_counts(user_id=user.id)
        assert "all" in cat_counts
        assert "unread" in cat_counts
        assert cat_counts["all"] >= 2

        # 7. Test mark as read
        read_res = await service.mark_as_read(notif1.id, user_id=user.id)
        assert read_res.is_read is True

        # 8. Test mark all as read
        mark_all_res = await service.mark_all_as_read(user_id=user.id)
        assert mark_all_res["message"] is not None
        assert "updated_count" in mark_all_res

        unread_after = await service.get_unread_count(user_id=user.id)
        assert unread_after.unread_count == 0

        # 9. Test dispatching notifications for all notification event types
        event_types = [
            ("APPOINTMENT_CONFIRMATION", "Appointment Booking Confirmed", "Your appointment is confirmed.", "appointment"),
            ("APPOINTMENT_RESCHEDULE", "Appointment Rescheduled", "Your appointment has been rescheduled.", "appointment"),
            ("APPOINTMENT_CANCELLATION", "Appointment Cancelled", "Your appointment was cancelled.", "appointment"),
            ("QUEUE_ALERT", "Queue Token Called", "Doctor is calling token #5.", "queue"),
            ("PATIENT_ADMISSION", "Patient Admitted", "Patient admitted to Ward A.", "ipd"),
            ("PATIENT_DISCHARGE", "Patient Discharged", "Patient discharged successfully.", "ipd"),
            ("LAB_REPORT_READY", "Lab Report Approved", "Your lab test report is ready.", "lab"),
            ("PRESCRIPTION_ISSUED", "Prescription Issued", "Dr. Smith issued a new prescription.", "pharmacy"),
            ("PRESCRIPTION_DISPENSED", "Prescription Dispensed", "Your prescribed medicines are dispensed.", "pharmacy"),
            ("INVOICE_GENERATED", "Pharmacy Invoice Generated", "Invoice generated for your order.", "billing"),
            ("PAYMENT_RECEIVED", "Payment Received", "Payment of $100 received.", "billing"),
        ]

        dispatched_notifications = []

        for notif_type, title, message, ref_type in event_types:
            notif = await service.dispatch_notification(
                user_id=user.id,
                notification_type=notif_type,
                title=title,
                message=message,
                reference_type=ref_type,
                reference_id=100,
                priority="HIGH" if "CRITICAL" in notif_type or "CANCEL" in notif_type else "NORMAL",
            )
            assert notif is not None
            assert notif.user_id == user.id
            assert notif.notification_type == notif_type
            assert notif.title == title
            dispatched_notifications.append(notif)

        assert len(dispatched_notifications) == len(event_types)

        # 10. Verify WebSocket notification manager methods
        assert notification_manager is not None
        await notification_manager.send_to_user(
            user_id=user.id,
            message={"type": "TEST_NOTIFICATION", "message": "E2E Test Message"},
        )
        await notification_manager.broadcast(
            message={"type": "BROADCAST_TEST", "message": "Global Broadcast Test"},
        )

        # 11. Verify Celery notification tasks exist
        assert send_email_async is not None
        assert send_sms_async is not None

