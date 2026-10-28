"""
Inventory Data Recovery & Audit Maintenance Script
=================================================
Production-safe, idempotent audit and recovery tool for NexaCare Backend.

Features:
- Read-only audit mode by default (--dry-run).
- Safe, verified ownership recovery for unassigned InventoryItems where:
    a) Linked to a Medicine with verified hospital_id.
    b) Associated with a Warehouse with verified hospital_id.
    c) Associated with a Department with verified hospital_id.
- Strict conflict detection: Conflicting hospital references are flagged and skipped.
- Ambiguous records (no hospital reference anywhere) are reported for manual review and left unchanged.
- Medicines without inventory_item_id are audited; matching unlinked inventory items in the same hospital
  can be safely linked without duplicating stock or records.
- Transactional integrity: all updates happen inside a single transaction; rolled back if dry-run or error.
- Idempotent: safe to run multiple times with zero changes on subsequent runs.
- Does NOT hardcode any hospital ID.

Usage:
  python scripts/inventory_data_recovery.py
  python scripts/inventory_data_recovery.py --apply
  python scripts/inventory_data_recovery.py --hospital-id 6 --apply
  python scripts/inventory_data_recovery.py --link-medicines --apply
"""

import argparse
import asyncio
import os
import sys
from typing import Any

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Add application to path if run standalone
from app.core.database import AsyncSessionLocal
from app.models.department_model import Department
from app.models.inventory_model import InventoryItem, Warehouse, WarehouseStock
from app.models.pharmacy_model import Medicine


async def run_audit_and_recovery(
    apply_changes: bool = False,
    hospital_id_filter: int | None = None,
    link_medicines: bool = False,
    backfill_medicines: bool = False,
) -> dict[str, Any]:
    stats = {
        "orphaned_items_repaired_via_medicine": [],
        "orphaned_items_repaired_via_warehouse": [],
        "orphaned_items_repaired_via_department": [],
        "conflicting_items_skipped": [],
        "ambiguous_items_unresolved": [],
        "medicines_linked_to_existing_inventory": [],
        "medicines_without_inventory": [],
        "medicines_backfilled_inventory": [],
    }

    async with AsyncSessionLocal() as session:
        print("=" * 80)
        mode_str = "APPLY LIVE CHANGES" if apply_changes else "DRY-RUN (NO CHANGES WILL BE COMMITTED)"
        print(f"NexaCare Inventory Data Recovery & Audit Tool - Mode: {mode_str}")
        if hospital_id_filter:
            print(f"Hospital Filter: ID {hospital_id_filter}")
        print("=" * 80)

        # -------------------------------------------------------------
        # STEP 1: Audit and Recover InventoryItems where hospital_id IS NULL
        # -------------------------------------------------------------
        print("\n[Step 1] Auditing InventoryItems with missing hospital ownership...")

        # Fetch all inventory items where hospital_id IS NULL
        stmt = (
            select(InventoryItem)
            .where(InventoryItem.hospital_id.is_(None))
            .order_by(InventoryItem.id)
        )
        res = await session.execute(stmt)
        null_items = res.scalars().all()
        print(f"Found {len(null_items)} inventory items with hospital_id IS NULL.")

        for item in null_items:
            evidence_sources: dict[str, int] = {}

            # Check linked Medicine
            med_res = await session.execute(
                select(Medicine).where(Medicine.inventory_item_id == item.id)
            )
            linked_med = med_res.scalar_one_or_none()
            if linked_med and linked_med.hospital_id is not None:
                evidence_sources["medicine"] = linked_med.hospital_id

            # Check linked Warehouse
            if item.warehouse_id:
                wh_res = await session.execute(
                    select(Warehouse).where(Warehouse.id == item.warehouse_id)
                )
                wh = wh_res.scalar_one_or_none()
                if wh and wh.hospital_id is not None:
                    evidence_sources["warehouse"] = wh.hospital_id

            # Check linked Department
            if item.department_id:
                dept_res = await session.execute(
                    select(Department).where(Department.department_id == item.department_id)
                )
                dept = dept_res.scalar_one_or_none()
                if dept and dept.hospital_id is not None:
                    evidence_sources["department"] = dept.hospital_id

            unique_hospitals = set(evidence_sources.values())

            if len(unique_hospitals) > 1:
                # Conflicting ownership!
                stats["conflicting_items_skipped"].append({
                    "item_id": item.id,
                    "item_name": item.name,
                    "sku": item.sku,
                    "conflicting_evidence": evidence_sources,
                })
                print(f"  [CONFLICT] Item #{item.id} ('{item.name}'): conflicting evidence {evidence_sources}. SKIPPING.")
                continue

            if len(unique_hospitals) == 1:
                target_hospital_id = unique_hospitals.pop()
                if hospital_id_filter and target_hospital_id != hospital_id_filter:
                    continue

                source_name = list(evidence_sources.keys())[0]
                if source_name == "medicine":
                    stats["orphaned_items_repaired_via_medicine"].append({
                        "item_id": item.id,
                        "item_name": item.name,
                        "sku": item.sku,
                        "target_hospital_id": target_hospital_id,
                        "medicine_id": linked_med.id,
                    })
                    print(f"  [REPAIR: MEDICINE] Item #{item.id} ('{item.name}'): assign hospital_id={target_hospital_id} via Medicine #{linked_med.id}.")
                elif source_name == "warehouse":
                    stats["orphaned_items_repaired_via_warehouse"].append({
                        "item_id": item.id,
                        "item_name": item.name,
                        "sku": item.sku,
                        "target_hospital_id": target_hospital_id,
                        "warehouse_id": item.warehouse_id,
                    })
                    print(f"  [REPAIR: WAREHOUSE] Item #{item.id} ('{item.name}'): assign hospital_id={target_hospital_id} via Warehouse #{item.warehouse_id}.")
                else:
                    stats["orphaned_items_repaired_via_department"].append({
                        "item_id": item.id,
                        "item_name": item.name,
                        "sku": item.sku,
                        "target_hospital_id": target_hospital_id,
                        "department_id": item.department_id,
                    })
                    print(f"  [REPAIR: DEPARTMENT] Item #{item.id} ('{item.name}'): assign hospital_id={target_hospital_id} via Department #{item.department_id}.")

                if apply_changes:
                    item.hospital_id = target_hospital_id
            else:
                # 0 sources of hospital ownership -> Ambiguous record (test fixture or unlinked item)
                stats["ambiguous_items_unresolved"].append({
                    "item_id": item.id,
                    "item_name": item.name,
                    "sku": item.sku,
                    "warehouse_id": item.warehouse_id,
                    "department_id": item.department_id,
                })

        # -------------------------------------------------------------
        # STEP 2: Audit Medicines where inventory_item_id IS NULL
        # -------------------------------------------------------------
        print("\n[Step 2] Auditing Medicines without inventory links (inventory_item_id IS NULL)...")
        med_query = select(Medicine).where(Medicine.inventory_item_id.is_(None))
        if hospital_id_filter:
            med_query = med_query.where(Medicine.hospital_id == hospital_id_filter)
        med_query = med_query.order_by(Medicine.id)
        med_res = await session.execute(med_query)
        unlinked_meds = med_res.scalars().all()
        print(f"Found {len(unlinked_meds)} medicines with inventory_item_id IS NULL.")

        for med in unlinked_meds:
            if med.hospital_id is None:
                stats["medicines_without_inventory"].append({
                    "medicine_id": med.id,
                    "name": med.name,
                    "sku": med.sku,
                    "hospital_id": None,
                    "reason": "Medicine has no hospital_id",
                })
                continue

            # Check if an existing inventory item in the SAME hospital has the exact same SKU or name & barcode
            candidate_conditions = [InventoryItem.sku == med.sku]
            if med.barcode:
                candidate_conditions.append(
                    and_(
                        InventoryItem.name == med.name,
                        InventoryItem.barcode == med.barcode,
                    )
                )
            candidate_stmt = (
                select(InventoryItem)
                .where(
                    InventoryItem.hospital_id == med.hospital_id,
                    InventoryItem.is_deleted.is_(False),
                    or_(*candidate_conditions),
                )
            )
            candidate_res = await session.execute(candidate_stmt)
            candidates = candidate_res.scalars().all()

            if len(candidates) == 1 and link_medicines:
                candidate = candidates[0]
                # Verify no other medicine is already using this inventory_item_id
                existing_link_res = await session.execute(
                    select(Medicine).where(
                        Medicine.inventory_item_id == candidate.id,
                        Medicine.id != med.id,
                    )
                )
                if existing_link_res.first() is None:
                    stats["medicines_linked_to_existing_inventory"].append({
                        "medicine_id": med.id,
                        "medicine_name": med.name,
                        "inventory_item_id": candidate.id,
                        "inventory_name": candidate.name,
                        "hospital_id": med.hospital_id,
                    })
                    print(f"  [LINK: MEDICINE->INVENTORY] Medicine #{med.id} ('{med.name}') matched to InventoryItem #{candidate.id} (Hospital {med.hospital_id}).")
                    if apply_changes:
                        med.inventory_item_id = candidate.id
                    continue

            if backfill_medicines:
                stats["medicines_backfilled_inventory"].append({
                    "medicine_id": med.id,
                    "medicine_name": med.name,
                    "hospital_id": med.hospital_id,
                })
                print(f"  [BACKFILL PROPOSED] Backfill InventoryItem for Medicine #{med.id} ('{med.name}') in Hospital {med.hospital_id}.")
                if apply_changes:
                    new_item = InventoryItem(
                        name=med.name,
                        sku=med.sku or f"MED-{med.id}",
                        barcode=med.barcode,
                        category=med.category or "Pharmaceuticals",
                        quantity=med.stock_quantity or 0,
                        unit=med.unit or "Unit",
                        unit_cost=med.unit_price or 0.0,
                        reorder_level=med.reorder_level if med.reorder_level is not None else 10,
                        expiry_date=med.expiry_date,
                        hospital_id=med.hospital_id,
                    )
                    session.add(new_item)
                    await session.flush()
                    med.inventory_item_id = new_item.id

                    if (med.stock_quantity or 0) > 0:
                        wh_res = await session.execute(
                            select(Warehouse.id).where(
                                Warehouse.code == 'PHARMACY',
                                Warehouse.hospital_id == med.hospital_id,
                            )
                        )
                        wh_id = wh_res.scalar()
                        if not wh_id:
                            wh = Warehouse(
                                name="Pharmacy Warehouse",
                                code="PHARMACY",
                                hospital_id=med.hospital_id,
                                is_active=True,
                            )
                            session.add(wh)
                            await session.flush()
                            wh_id = wh.id

                        new_item.warehouse_id = wh_id
                        ws = WarehouseStock(
                            warehouse_id=wh_id,
                            inventory_item_id=new_item.id,
                            quantity=med.stock_quantity,
                        )
                        session.add(ws)
            else:
                stats["medicines_without_inventory"].append({
                    "medicine_id": med.id,
                    "name": med.name,
                    "sku": med.sku,
                    "hospital_id": med.hospital_id,
                    "reason": "No linked inventory item (dry-run audit)",
                })

        # Print summary report
        print("\n" + "=" * 80)
        print("AUDIT & RECOVERY SUMMARY")
        print("=" * 80)
        print(f"Items with ownership repairable via Medicine    : {len(stats['orphaned_items_repaired_via_medicine'])}")
        print(f"Items with ownership repairable via Warehouse   : {len(stats['orphaned_items_repaired_via_warehouse'])}")
        print(f"Items with ownership repairable via Department  : {len(stats['orphaned_items_repaired_via_department'])}")
        print(f"Items with conflicting tenant ownership (SKIPPED): {len(stats['conflicting_items_skipped'])}")
        print(f"Ambiguous items without tenant evidence (SKIPPED): {len(stats['ambiguous_items_unresolved'])}")
        print(f"Medicines linked to existing inventory items   : {len(stats['medicines_linked_to_existing_inventory'])}")
        print(f"Medicines backfilled with new inventory item   : {len(stats['medicines_backfilled_inventory'])}")
        print(f"Medicines remaining without inventory item      : {len(stats['medicines_without_inventory'])}")
        print("=" * 80)

        if stats["ambiguous_items_unresolved"]:
            print(f"\nAMBIGUOUS ITEMS REQUIRING MANUAL REVIEW ({len(stats['ambiguous_items_unresolved'])} records):")
            for amb in stats["ambiguous_items_unresolved"][:10]:
                print(f"  - Item #{amb['item_id']} | SKU: {amb['sku']} | Name: {amb['item_name']} | WH: {amb['warehouse_id']} | Dept: {amb['department_id']}")
            if len(stats["ambiguous_items_unresolved"]) > 10:
                print(f"  ... and {len(stats['ambiguous_items_unresolved']) - 10} more.")

        if apply_changes:
            await session.commit()
            print("\n>>> SUCCESS: All safe changes have been COMMITTED to the database.")
        else:
            await session.rollback()
            print("\n>>> DRY RUN COMPLETE: Session rolled back. ZERO changes made to the database.")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Audit and safely recover orphaned inventory data in NexaCare.")
    parser.add_argument("--apply", action="store_true", help="Apply verified changes to the database. If omitted, operates in dry-run mode.")
    parser.add_argument("--hospital-id", type=int, default=None, help="Filter audit/recovery to a specific hospital ID.")
    parser.add_argument("--link-medicines", action="store_true", help="Safely link unlinked medicines to existing matching inventory items in the same hospital.")
    parser.add_argument("--backfill-medicines", action="store_true", help="Backfill 1-to-1 inventory items for medicines that have none.")

    args = parser.parse_args()

    if args.apply:
        print("\n" + "!" * 80)
        print("WARNING: You have specified --apply. Database modifications will be persisted.")
        print("!" * 80)

    async def _runner():
        from app.core.database import engine
        try:
            await run_audit_and_recovery(
                apply_changes=args.apply,
                hospital_id_filter=args.hospital_id,
                link_medicines=args.link_medicines,
                backfill_medicines=args.backfill_medicines,
            )
        finally:
            await engine.dispose()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
