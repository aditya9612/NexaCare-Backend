import uuid
from datetime import date
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models.hospital_model import Hospital
from app.models.inventory_model import InventoryItem, Warehouse
from app.models.department_model import Department
from app.models.pharmacy_model import Medicine
from app.repositories.inventory_repository import InventoryRepository
from app.services.pharmacy_service import PharmacyService
from app.schemas.pharmacy_schema import MedicineCreate, MedicineUpdate
from app.core.dependencies import resolve_tenant_id
from app.core.exceptions import ConflictException, BadRequestException, ForbiddenException
from scripts.inventory_data_recovery import run_audit_and_recovery


def make_barcode(uid: str) -> str:
    # 13 digit numeric barcode
    num = int(uid, 16) % 10000000000
    return f"890{num:010d}"


@pytest.mark.asyncio
async def test_scenario_1_create_medicine_consistent_hospital_ownership():
    """
    Scenario 1: Creating a medicine assigns consistent hospital ownership to both Medicine and InventoryItem.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        # Create hospital
        hosp = Hospital(name=f"Hosp Med {uid}", email=f"med_{uid}@h.com", phone="1", address="M")
        session.add(hosp)
        await session.flush()
        hosp_id = hosp.id

        service = PharmacyService(session)
        fake_user = type("FakeUser", (), {
            "id": 1,
            "hospital_id": hosp_id,
            "role": type("Role", (), {"name": "hospital_admin"})(),
        })()

        med_data = MedicineCreate(
            name=f"Paracetamol Test {uid}",
            generic_name="Paracetamol",
            category="Tablet",
            unit="Strips",
            unit_price=25.0,
            stock_quantity=100,
            reorder_level=10,
            barcode=make_barcode(uid),
            batch_number=f"BAT_{uid}",
            expiry_date=date(2028, 1, 1),
        )

        created_med = await service.create_medicine(med_data, current_user=fake_user, user_id=fake_user.id)
        await session.commit()

        # Verify Medicine hospital ownership in DB
        med_db = await session.scalar(select(Medicine).where(Medicine.id == created_med.id))
        assert med_db is not None
        assert med_db.hospital_id == hosp_id
        assert med_db.inventory_item_id is not None

        # Verify InventoryItem hospital ownership
        inv_item = await session.scalar(
            select(InventoryItem).where(InventoryItem.id == med_db.inventory_item_id)
        )
        assert inv_item is not None
        assert inv_item.hospital_id == hosp_id
        assert inv_item.name == med_db.name
        assert inv_item.quantity == 100
        assert inv_item.warehouse_id is not None


@pytest.mark.asyncio
async def test_scenario_2_cross_hospital_isolation():
    """
    Scenario 2: A hospital cannot retrieve another hospital's inventory items.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hA = Hospital(name=f"Hosp A {uid}", email=f"a_{uid}@h.com", phone="1", address="A")
        hB = Hospital(name=f"Hosp B {uid}", email=f"b_{uid}@h.com", phone="2", address="B")
        session.add_all([hA, hB])
        await session.flush()

        itemA = InventoryItem(
            name=f"Item A {uid}",
            sku=f"SKU_A_{uid}",
            category="Pharmaceuticals",
            hospital_id=hA.id,
            quantity=50,
            unit="box",
            unit_cost=10.0,
        )
        itemB = InventoryItem(
            name=f"Item B {uid}",
            sku=f"SKU_B_{uid}",
            category="Pharmaceuticals",
            hospital_id=hB.id,
            quantity=20,
            unit="box",
            unit_cost=15.0,
        )
        session.add_all([itemA, itemB])
        await session.commit()

        repo = InventoryRepository(session)

        # Hospital A query
        items_for_A = await repo.list_all(hospital_id=hA.id, limit=100)
        item_ids_for_A = {item.id for item in items_for_A}
        assert itemA.id in item_ids_for_A
        assert itemB.id not in item_ids_for_A

        # Hospital B query
        items_for_B = await repo.list_all(hospital_id=hB.id, limit=100)
        item_ids_for_B = {item.id for item in items_for_B}
        assert itemB.id in item_ids_for_B
        assert itemA.id not in item_ids_for_B

        # Direct get_by_id tenant check
        item_b_as_a = await repo.get_by_id(itemB.id, hospital_id=hA.id)
        assert item_b_as_a is None

        item_b_as_b = await repo.get_by_id(itemB.id, hospital_id=hB.id)
        assert item_b_as_b is not None
        assert item_b_as_b.id == itemB.id


@pytest.mark.asyncio
async def test_scenario_3_unassigned_records_not_visible_globally():
    """
    Scenario 3: Unassigned inventory records (hospital_id IS NULL and no WH/Dept)
    are not automatically visible to any hospital.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hA = Hospital(name=f"Hosp A {uid}", email=f"a_{uid}@h.com", phone="1", address="A")
        session.add(hA)
        await session.flush()

        orphaned_item = InventoryItem(
            name=f"Orphaned Item {uid}",
            sku=f"ORPH_{uid}",
            category="Pharmaceuticals",
            hospital_id=None,
            warehouse_id=None,
            department_id=None,
            quantity=10,
            unit="box",
            unit_cost=5.0,
        )
        session.add(orphaned_item)
        await session.commit()

        repo = InventoryRepository(session)
        items_for_A = await repo.list_all(hospital_id=hA.id, limit=500)
        item_ids_for_A = {item.id for item in items_for_A}
        assert orphaned_item.id not in item_ids_for_A

        # get_by_id also does not return it for Hospital A
        assert await repo.get_by_id(orphaned_item.id, hospital_id=hA.id) is None


@pytest.mark.asyncio
async def test_scenario_4_warehouse_department_tenant_linkage():
    """
    Scenario 4: Inventory items with hospital_id IS NULL but linked to a valid hospital warehouse
    or department follow the documented ownership rules.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hA = Hospital(name=f"Hosp A {uid}", email=f"a_{uid}@h.com", phone="1", address="A")
        hB = Hospital(name=f"Hosp B {uid}", email=f"b_{uid}@h.com", phone="2", address="B")
        session.add_all([hA, hB])
        await session.flush()

        whA = Warehouse(name=f"WH A {uid}", code=f"W_{uid}", hospital_id=hA.id)
        session.add(whA)
        await session.flush()

        # Item has hospital_id=None, but warehouse belongs to hA
        item_in_whA = InventoryItem(
            name=f"Item in WH A {uid}",
            sku=f"SKU_WH_{uid}",
            category="Pharmaceuticals",
            hospital_id=None,
            warehouse_id=whA.id,
            quantity=30,
            unit="box",
            unit_cost=8.0,
        )
        session.add(item_in_whA)
        await session.commit()

        repo = InventoryRepository(session)

        # Visible to Hospital A
        items_for_A = await repo.list_all(hospital_id=hA.id, limit=500)
        assert item_in_whA.id in {item.id for item in items_for_A}
        assert await repo.get_by_id(item_in_whA.id, hospital_id=hA.id) is not None

        # Hidden from Hospital B
        items_for_B = await repo.list_all(hospital_id=hB.id, limit=500)
        assert item_in_whA.id not in {item.id for item in items_for_B}
        assert await repo.get_by_id(item_in_whA.id, hospital_id=hB.id) is None


@pytest.mark.asyncio
async def test_scenario_5_conflicting_ownership_securely_rejected():
    """
    Scenario 5: Conflicting hospital ownership (Item hospital_id=A, Warehouse hospital_id=B)
    is securely rejected and does not leak to Hospital B or Hospital A.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hA = Hospital(name=f"Hosp A {uid}", email=f"a_{uid}@h.com", phone="1", address="A")
        hB = Hospital(name=f"Hosp B {uid}", email=f"b_{uid}@h.com", phone="2", address="B")
        session.add_all([hA, hB])
        await session.flush()

        whB = Warehouse(name=f"WH B {uid}", code=f"WB_{uid}", hospital_id=hB.id)
        session.add(whB)
        await session.flush()

        # Conflicting item: Owned by Hospital A, but pointing to Hospital B's warehouse
        conflict_item = InventoryItem(
            name=f"Conflict Item {uid}",
            sku=f"CONF_{uid}",
            category="Pharmaceuticals",
            hospital_id=hA.id,
            warehouse_id=whB.id,
            quantity=25,
            unit="box",
            unit_cost=12.0,
        )
        session.add(conflict_item)
        await session.commit()

        repo = InventoryRepository(session)

        # Must NOT leak to Hospital B (the warehouse owner)
        items_for_B = await repo.list_all(hospital_id=hB.id, limit=500)
        assert conflict_item.id not in {item.id for item in items_for_B}
        assert await repo.get_by_id(conflict_item.id, hospital_id=hB.id) is None

        # Must NOT be accessed through Hospital A either (warehouse tenant mismatch prevented by _tenant_filter)
        items_for_A = await repo.list_all(hospital_id=hA.id, limit=500)
        assert conflict_item.id not in {item.id for item in items_for_A}


@pytest.mark.asyncio
async def test_scenario_6_existing_inventory_links_reused():
    """
    Scenario 6: Updating a medicine synchronizes and reuses the existing inventory link
    rather than creating duplicates.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp Med {uid}", email=f"med_{uid}@h.com", phone="1", address="M")
        session.add(hosp)
        await session.flush()
        hosp_id = hosp.id

        inv_item = InventoryItem(
            name=f"Old Item Name {uid}",
            sku=f"SKU_{uid}",
            category="Pharmaceuticals",
            hospital_id=hosp_id,
            quantity=15,
            unit="bottle",
            unit_cost=50.0,
        )
        session.add(inv_item)
        await session.flush()

        med = Medicine(
            name=f"Old Med Name {uid}",
            generic_name="Old Generic",
            category="Tablet",
            unit="Strips",
            sku=f"MED_{uid}",
            hospital_id=hosp_id,
            inventory_item_id=inv_item.id,
            stock_quantity=15,
            unit_price=50.0,
        )
        session.add(med)
        await session.commit()

        service = PharmacyService(session)
        fake_user = type("FakeUser", (), {
            "id": 1,
            "hospital_id": hosp_id,
            "role": type("Role", (), {"name": "hospital_admin"})(),
        })()

        update_data = MedicineUpdate(name=f"Updated Med Name {uid}", unit_price=65.0)
        await service.update_medicine(med.id, update_data, current_user=fake_user, user_id=fake_user.id)
        await session.commit()

        # Verify no duplicate inventory item was created
        all_items_res = await session.execute(
            select(InventoryItem).where(InventoryItem.hospital_id == hosp_id)
        )
        items = all_items_res.scalars().all()
        assert len(items) == 1
        assert items[0].id == inv_item.id
        assert items[0].name == f"Updated Med Name {uid}"
        assert items[0].unit_cost == 65.0


@pytest.mark.asyncio
async def test_scenario_7_failed_medicine_creation_rolls_back():
    """
    Scenario 7: Failed medicine creation rolls back both Medicine and InventoryItem atomically.
    """
    uid = uuid.uuid4().hex[:8]
    bar = make_barcode(uid)
    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp Rollback {uid}", email=f"rb_{uid}@h.com", phone="1", address="R")
        session.add(hosp)
        await session.flush()
        hosp_id = hosp.id

        service = PharmacyService(session)
        fake_user = type("FakeUser", (), {
            "id": 1,
            "hospital_id": hosp_id,
            "role": type("Role", (), {"name": "hospital_admin"})(),
        })()

        # Create medicine with valid data first
        med_data1 = MedicineCreate(
            name=f"Unique Med {uid}",
            generic_name="Unique Generic",
            category="Tablet",
            unit="Strips",
            unit_price=10.0,
            stock_quantity=5,
            reorder_level=5,
            barcode=bar,
            batch_number=f"BAT_{uid}",
            expiry_date=date(2028, 1, 1),
        )
        await service.create_medicine(med_data1, current_user=fake_user, user_id=fake_user.id)
        await session.commit()

        # Attempt to create duplicate barcode medicine which causes ConflictException
        med_data_dup = MedicineCreate(
            name=f"Dup Barcode Med {uid}",
            generic_name="Dup Generic",
            category="Tablet",
            unit="Strips",
            unit_price=15.0,
            stock_quantity=5,
            reorder_level=5,
            barcode=bar,
            batch_number=f"BAT_DUP_{uid}",
            expiry_date=date(2028, 1, 1),
        )

        with pytest.raises(ConflictException):
            await service.create_medicine(med_data_dup, current_user=fake_user, user_id=fake_user.id)

        # Rollback session
        await session.rollback()

        # Verify only the first medicine and its inventory item exist
        items = (await session.execute(
            select(InventoryItem).where(InventoryItem.hospital_id == hosp_id)
        )).scalars().all()
        assert len(items) == 1
        assert items[0].name == f"Unique Med {uid}"


@pytest.mark.asyncio
async def test_scenario_8_pagination_sorting_count_consistency():
    """
    Scenario 8: Pagination, sorting, total, and pages are consistent and filtered strictly by tenant.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hA = Hospital(name=f"Hosp Pag {uid}", email=f"pag_{uid}@h.com", phone="1", address="P")
        hB = Hospital(name=f"Hosp Other {uid}", email=f"oth_{uid}@h.com", phone="2", address="O")
        session.add_all([hA, hB])
        await session.flush()
        hA_id = hA.id
        hB_id = hB.id

        # Add 5 items for hA and 3 items for hB
        for i in range(5):
            session.add(InventoryItem(
                name=f"Item {i} {uid}",
                sku=f"SKU_{i}_{uid}",
                category="Pharmaceuticals",
                hospital_id=hA_id,
                quantity=10 * (i + 1),
                unit="box",
                unit_cost=5.0 * (i + 1),
            ))
        for j in range(3):
            session.add(InventoryItem(
                name=f"Other Item {j} {uid}",
                sku=f"SKU_OTH_{j}_{uid}",
                category="Pharmaceuticals",
                hospital_id=hB_id,
                quantity=10,
                unit="box",
                unit_cost=5.0,
            ))
        await session.commit()

        repo = InventoryRepository(session)

        # Check total count for hA
        total_A = await repo.count_all(hospital_id=hA_id)
        assert total_A == 5

        # Check page 1, size 2
        page1 = await repo.list_all(
            hospital_id=hA_id,
            limit=2,
            skip=0,
            sort_by="unit_cost",
            sort_order="asc",
        )
        assert len(page1) == 2
        assert page1[0].unit_cost < page1[1].unit_cost

        # Check page 3, size 2 (should return 1 item)
        page3 = await repo.list_all(
            hospital_id=hA_id,
            limit=2,
            skip=4,
            sort_by="unit_cost",
            sort_order="asc",
        )
        assert len(page3) == 1
        assert page3[0].unit_cost == 25.0


@pytest.mark.asyncio
async def test_scenario_9_dry_run_data_repair_makes_zero_changes():
    """
    Scenario 9: Dry-run data repair identifies repairable records but commits ZERO database changes.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp DryRun {uid}", email=f"dry_{uid}@h.com", phone="1", address="D")
        session.add(hosp)
        await session.flush()
        hosp_id = hosp.id

        inv_item = InventoryItem(
            name=f"DryRun Item {uid}",
            sku=f"DRY_{uid}",
            category="Pharmaceuticals",
            hospital_id=None,  # Orphaned
            quantity=10,
            unit="box",
            unit_cost=5.0,
        )
        session.add(inv_item)
        await session.flush()

        med = Medicine(
            name=f"DryRun Med {uid}",
            generic_name="Generic Dry",
            category="Tablet",
            unit="Strips",
            sku=f"MED_DRY_{uid}",
            hospital_id=hosp_id,
            inventory_item_id=inv_item.id,
        )
        session.add(med)
        await session.commit()

        item_id = inv_item.id

    # Execute recovery tool in dry-run mode
    stats = await run_audit_and_recovery(apply_changes=False, hospital_id_filter=hosp_id)
    assert len(stats["orphaned_items_repaired_via_medicine"]) == 1

    # Verify database was NOT changed
    async with AsyncSessionLocal() as session:
        recheck_item = await session.scalar(
            select(InventoryItem).where(InventoryItem.id == item_id)
        )
        assert recheck_item is not None
        assert recheck_item.hospital_id is None, "Dry run must NOT persist hospital_id change"


@pytest.mark.asyncio
async def test_scenario_10_rerunning_repair_is_idempotent():
    """
    Scenario 10: Applying data repair persists safe changes, and running a second time
    finds zero remaining records to repair (idempotent).
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp Idemp {uid}", email=f"idem_{uid}@h.com", phone="1", address="I")
        session.add(hosp)
        await session.flush()
        hosp_id = hosp.id

        inv_item = InventoryItem(
            name=f"Idemp Item {uid}",
            sku=f"IDEM_{uid}",
            category="Pharmaceuticals",
            hospital_id=None,
            quantity=10,
            unit="box",
            unit_cost=5.0,
        )
        session.add(inv_item)
        await session.flush()

        med = Medicine(
            name=f"Idemp Med {uid}",
            generic_name="Generic Idemp",
            category="Tablet",
            unit="Strips",
            sku=f"MED_IDEM_{uid}",
            hospital_id=hosp_id,
            inventory_item_id=inv_item.id,
        )
        session.add(med)
        await session.commit()
        item_id = inv_item.id

    # First run with apply_changes=True
    stats_pass1 = await run_audit_and_recovery(apply_changes=True, hospital_id_filter=hosp_id)
    assert len(stats_pass1["orphaned_items_repaired_via_medicine"]) == 1

    # Verify item was repaired
    async with AsyncSessionLocal() as session:
        repaired_item = await session.scalar(
            select(InventoryItem).where(InventoryItem.id == item_id)
        )
        assert repaired_item is not None
        assert repaired_item.hospital_id == hosp_id

    # Second run with apply_changes=True
    stats_pass2 = await run_audit_and_recovery(apply_changes=True, hospital_id_filter=hosp_id)
    assert len(stats_pass2["orphaned_items_repaired_via_medicine"]) == 0, "Second pass must find 0 items to repair"


def test_scenario_11_tenant_resolution_security():
    """
    Scenario 11: Comprehensive tenant resolution and security checks.
    - Regular users are scoped to user.hospital_id.
    - Regular users cannot override tenant with X-Hospital-Id.
    - Invalid X-Hospital-Id (<= 0) raises BadRequestException (HTTP 400).
    - Super Admin can switch tenant context using X-Hospital-Id.
    - Super Admin falls back to active_hospital_id or None.
    """
    regular_role = type("Role", (), {"name": "hospital_staff"})()
    super_admin_role = type("Role", (), {"name": "super_admin"})()

    # 1. Regular user scoped to user.hospital_id
    user_reg = type("User", (), {"id": 10, "hospital_id": 5, "role": regular_role})()
    assert resolve_tenant_id(user_reg) == 5

    # 2. Regular user passing matching header succeeds
    assert resolve_tenant_id(user_reg, x_hospital_id=5) == 5

    # 3. Regular user attempting to override header with different tenant raises 403 Forbidden
    with pytest.raises(ForbiddenException):
        resolve_tenant_id(user_reg, x_hospital_id=8)

    # 4. Regular user with no hospital_id attempting to pass header raises 403 Forbidden
    user_no_hosp = type("User", (), {"id": 11, "hospital_id": None, "role": regular_role})()
    with pytest.raises(ForbiddenException):
        resolve_tenant_id(user_no_hosp, x_hospital_id=5)

    # 5. Invalid X-Hospital-Id (<= 0) raises 400 BadRequest
    with pytest.raises(BadRequestException):
        resolve_tenant_id(user_reg, x_hospital_id=0)

    with pytest.raises(BadRequestException):
        resolve_tenant_id(user_reg, x_hospital_id=-1)

    # 6. Super Admin can switch tenant context to any valid hospital_id
    admin_user = type("User", (), {"id": 1, "hospital_id": None, "active_hospital_id": 2, "role": super_admin_role})()
    assert resolve_tenant_id(admin_user, x_hospital_id=9) == 9

    # 7. Super Admin without header uses active_hospital_id
    assert resolve_tenant_id(admin_user) == 2

    # 8. Super Admin without header and without active_hospital_id returns None (global view)
    admin_user_global = type("User", (), {"id": 1, "hospital_id": None, "active_hospital_id": None, "role": super_admin_role})()
    assert resolve_tenant_id(admin_user_global) == None

    # 9. None user returns None
    assert resolve_tenant_id(None) is None


@pytest.mark.asyncio
async def test_scenario_12_cross_warehouse_department_leakage_prevented():
    """
    Scenario 12: An item linked to another hospital's warehouse or department cannot leak across tenants.
    Even if an item is created with hospital_id=hA, if its warehouse belongs to hB,
    it must be strictly excluded from hA's query.
    """
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hA = Hospital(name=f"Hosp A WH {uid}", email=f"awh_{uid}@h.com", phone="1", address="A")
        hB = Hospital(name=f"Hosp B WH {uid}", email=f"bwh_{uid}@h.com", phone="2", address="B")
        session.add_all([hA, hB])
        await session.flush()

        whB = Warehouse(name=f"WH B {uid}", code=f"WHB_{uid}", hospital_id=hB.id)
        session.add(whB)
        await session.flush()

        # Item ostensibly for Hospital A, but tied to Warehouse belonging to Hospital B
        leaked_item = InventoryItem(
            name=f"Leaked Item {uid}",
            sku=f"LEAK_{uid}",
            category="Pharmaceuticals",
            hospital_id=hA.id,
            warehouse_id=whB.id,
            quantity=10,
            unit="box",
            unit_cost=10.0,
        )
        session.add(leaked_item)
        await session.commit()

        repo = InventoryRepository(session)
        items_for_A = await repo.list_all(hospital_id=hA.id, limit=100)
        items_for_A_ids = {item.id for item in items_for_A}

        # Item MUST NOT leak into Hospital A's inventory list
        assert leaked_item.id not in items_for_A_ids

