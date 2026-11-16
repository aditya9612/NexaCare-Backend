import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.role_model import Role
from app.models.user_model import User
from app.models.notification_model import Notification
from app.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_case_1_successful_notification_persistence():
    """Case 1: Both business changes and notification are committed in outer transaction."""
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        # Create a test role if needed
        role_res = await session.execute(select(Role).limit(1))
        role = role_res.scalar_one_or_none()
        if not role:
            role = Role(name=f"Role_{uid}", description="Test Role")
            session.add(role)
            await session.commit()
            await session.refresh(role)

        # 1. Start outer transaction & add business record
        user = User(
            user_code=f"USR_C1_{uid}",
            email=f"c1_{uid}@example.com",
            hashed_password="hashed_pw",
            full_name=f"User C1 {uid}",
            role_id=role.id,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        # 2. Persist notification using NotificationService (engaging begin_nested)
        notif_service = NotificationService(session)
        created_notif = await notif_service.dispatch_notification(
            user_id=user.id,
            title="Case 1 Test",
            message="Message for case 1",
            notification_type="SYSTEM",
            priority="NORMAL",
        )
        assert created_notif is not None
        assert created_notif.id is not None

        # 3. Commit outer transaction
        await session.commit()

        # 4. Verify both are committed
        async with AsyncSessionLocal() as verify_session:
            v_user = await verify_session.get(User, user.id)
            v_notif = await verify_session.get(Notification, created_notif.id)
            assert v_user is not None
            assert v_notif is not None

            # Cleanup
            await verify_session.delete(v_notif)
            await verify_session.delete(v_user)
            await verify_session.commit()


@pytest.mark.asyncio
async def test_case_2_notification_insert_failure_after_savepoint_creation():
    """Case 2: Notification persistence failure inside savepoint does not crash outer transaction."""
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        role_res = await session.execute(select(Role).limit(1))
        role = role_res.scalar_one_or_none()
        if not role:
            role = Role(name=f"Role_{uid}", description="Test Role")
            session.add(role)
            await session.commit()
            await session.refresh(role)

        # 1. Start outer transaction & add valid business record
        user = User(
            user_code=f"USR_C2_{uid}",
            email=f"c2_{uid}@example.com",
            hashed_password="hashed_pw",
            full_name=f"User C2 {uid}",
            role_id=role.id,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        # 2. Trigger notification failure inside savepoint:
        # Pass non-existent foreign key user_id=99999999 to trigger foreign key IntegrityError
        notif_service = NotificationService(session)
        result = await notif_service.dispatch_notification(
            user_id=99999999,
            title="Case 2 Failing Alert",
            message="This should fail due to foreign key constraint",
            notification_type="SYSTEM",
        )
        # Verify notification failure was safely caught and returned None
        assert result is None

        # 3. Outer transaction remains completely healthy and unpoisoned
        # Commit the business operation
        await session.commit()

        # 4. Verify business record IS committed, and failed notification is absent
        async with AsyncSessionLocal() as verify_session:
            v_user = await verify_session.get(User, user.id)
            assert v_user is not None

            # Verify no notification exists with that non-existent user_id
            notif_res = await verify_session.execute(
                select(Notification).where(Notification.user_id == 99999999)
            )
            assert notif_res.scalar_one_or_none() is None

            # Cleanup
            await verify_session.delete(v_user)
            await verify_session.commit()


@pytest.mark.asyncio
async def test_case_3_pending_business_changes_flush_before_savepoint():
    """Case 3: Verify SQLAlchemy autoflush flushes pending changes before establishing savepoint."""
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        role_res = await session.execute(select(Role).limit(1))
        role = role_res.scalar_one_or_none()

        # Add a valid business record without manual flush
        user = User(
            user_code=f"USR_C3_{uid}",
            email=f"c3_{uid}@example.com",
            hashed_password="hashed_pw",
            full_name=f"User C3 {uid}",
            role_id=role.id if role else 1,
            is_active=True,
        )
        session.add(user)

        # Before begin_nested, user.id is None (unflushed)
        assert user.id is None

        # Calling begin_nested triggers autoflush
        async with session.begin_nested():
            # Now user.id is populated because autoflush executed before savepoint establishment
            assert user.id is not None

        await session.rollback()


@pytest.mark.asyncio
async def test_case_4_outer_transaction_rollback():
    """Case 4: Outer transaction rollback rolls back both business record and notification."""
    uid = uuid.uuid4().hex[:8]
    user_id = None
    notif_id = None

    async with AsyncSessionLocal() as session:
        role_res = await session.execute(select(Role).limit(1))
        role = role_res.scalar_one_or_none()

        user = User(
            user_code=f"USR_C4_{uid}",
            email=f"c4_{uid}@example.com",
            hashed_password="hashed_pw",
            full_name=f"User C4 {uid}",
            role_id=role.id if role else 1,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        user_id = user.id

        notif_service = NotificationService(session)
        created_notif = await notif_service.dispatch_notification(
            user_id=user.id,
            title="Case 4 Alert",
            message="Will be rolled back",
            notification_type="SYSTEM",
        )
        assert created_notif is not None
        notif_id = created_notif.id

        # Roll back outer transaction
        await session.rollback()

    # Verify neither record is in the database
    async with AsyncSessionLocal() as verify_session:
        v_user = await verify_session.get(User, user_id)
        v_notif = await verify_session.get(Notification, notif_id)
        assert v_user is None
        assert v_notif is None


@pytest.mark.asyncio
async def test_case_5_notification_persistence_failure_does_not_poison_session():
    """Case 5: A notification persistence failure does not poison session for subsequent valid operations."""
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        role_res = await session.execute(select(Role).limit(1))
        role = role_res.scalar_one_or_none()

        # 1. Valid business record A
        user_a = User(
            user_code=f"USR_C5A_{uid}",
            email=f"c5a_{uid}@example.com",
            hashed_password="hashed_pw",
            full_name=f"User C5A {uid}",
            role_id=role.id if role else 1,
            is_active=True,
        )
        session.add(user_a)
        await session.flush()

        # 2. Failed notification inside savepoint
        notif_service = NotificationService(session)
        failed_res = await notif_service.dispatch_notification(
            user_id=99999999,
            title="Failing Alert",
            message="Fails FK check",
            notification_type="SYSTEM",
        )
        assert failed_res is None

        # 3. Valid business record B in the SAME session
        user_b = User(
            user_code=f"USR_C5B_{uid}",
            email=f"c5b_{uid}@example.com",
            hashed_password="hashed_pw",
            full_name=f"User C5B {uid}",
            role_id=role.id if role else 1,
            is_active=True,
        )
        session.add(user_b)
        await session.flush()

        # 4. Commit session successfully
        await session.commit()

        # 5. Verify both records A and B are committed
        async with AsyncSessionLocal() as verify_session:
            va = await verify_session.get(User, user_a.id)
            vb = await verify_session.get(User, user_b.id)
            assert va is not None
            assert vb is not None

            # Cleanup
            await verify_session.delete(va)
            await verify_session.delete(vb)
            await verify_session.commit()
