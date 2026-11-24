# 10 DEVELOPER HANDOVER AND MAINTENANCE GUIDE

**Document Title:** Backend Architecture Handbook & Engineering Guidelines
**Target Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`
**Current Branch:** `tejas-feature`
**Audience:** Senior Backend Engineers, DevOps Leads, Application Developers
**Execution Timestamp:** 2026-11-23T21:16:00+05:30

---

## 1. Core Architecture Principles

Future engineers extending or maintaining NexaCare Backend must adhere to the following architectural rules:

### Rule 1: Never Trust Client Hospital IDs on Mutating Routes
- **Anti-Pattern:**
  ```python
  # DO NOT DO THIS: Vulnerable to tenant spoofing (IDOR)
  @router.post("/items")
  async def create_item(payload: ItemCreateSchema, db: AsyncSession = Depends(get_db)):
      item = Item(hospital_id=payload.hospital_id, name=payload.name)
      db.add(item)
  ```
- **Approved Pattern:**
  ```python
  # APPROVED: Enforces verified session hospital context
  @router.post("/items")
  async def create_item(
      payload: ItemCreateSchema,
      hospital_id: int = Depends(TenantWriteHospitalId),
      db: AsyncSession = Depends(get_db)
  ):
      item = Item(hospital_id=hospital_id, name=payload.name)
      db.add(item)
  ```

### Rule 2: Enforce Fail-Closed Module Entitlements
If an endpoint belongs to a modular feature (e.g., Pharmacy, Lab, Voice, Inventory), it **must** declare the module entitlement dependency:
```python
@router.post(
    "/prescriptions",
    dependencies=[Depends(require_module_enabled("PHARMACY"))]
)
async def create_prescription(...):
    ...
```

### Rule 3: Use Database Row Locks for Contended Resources
Whenever an operation modifies inventory, reserves beds, or books limited time slots, always acquire row locks inside an atomic transaction:
```python
# APPROVED: Prevents race conditions and overselling
stmt = select(Medicine).where(Medicine.id == med_id, Medicine.hospital_id == hospital_id).with_for_update()
medicine = (await session.execute(stmt)).scalar_one_or_none()
if not medicine or medicine.stock_quantity < requested_qty:
    raise BadRequestException("Insufficient stock available")
medicine.stock_quantity -= requested_qty
```

---

## 2. Critical Files Map

| File Path | Role & Importance | Maintenance Notes |
| :--- | :--- | :--- |
| `app/core/dependencies.py` | Central security & tenant dependency hub | Houses `TenantWriteHospitalId`, `require_module_enabled`, and `require_permission`. Never introduce fallbacks to default hospital IDs here. |
| `app/services/module_service.py` | SaaS module subscription engine | Evaluates active module subscriptions for hospital tenants. Cached via Redis. |
| `alembic/env.py` | Migration runner & offline SQL generator | Houses the offline mock inspector for dynamic migration scripts. Keep offline reflection stubs intact. |
| `app/core/database.py` | Connection pool & safe bootstrap | Configures `AsyncSessionLocal`, `pool_pre_ping=True`, and safe seeding. Ensure `allow_resync=False` remains set for production. |
| `app/main.py` | ASGI application lifecycle & middleware | Handles graceful startup/shutdown of Redis Pub/Sub listener and database engine disposal. |

---

## 3. Migration Guidelines

1. **Always Make Migrations Idempotent:** Use `if not existing:` checks before inserting permissions or tables to prevent crashes if migrations are re-run.
2. **Never Drop Existing Tenant Columns:** When modifying schemas, preserve backward compatibility for historical records.
3. **Avoid Dynamic Engine Reflection:** Write explicit Alembic schema operations (`op.add_column`, `op.create_table`) rather than invoking `sa.inspect(bind)` inside migration scripts.

---

## 4. Pre-Deployment Checklist

Before deploying changes to staging or production:
1. Run offline SQL generation: `alembic upgrade head --sql`.
2. Run test suites:
   - `pytest scratch/test_phase6d_route_wiring.py scratch/test_phase7_route_dispatch.py scratch/test_phase8_residual_remediation.py scratch/test_master_production_readiness.py`
   - `python -m unittest scratch/test_real_http_integration.py scratch/test_multi_hospital_staging.py scratch/test_load_and_concurrency.py`
   - `python scratch/test_mysql_real_db_concurrency.py`
3. Verify that all tests pass with zero errors before opening a pull request.
