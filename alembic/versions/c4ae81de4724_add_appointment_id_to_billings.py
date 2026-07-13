"""add_appointment_id_to_billings

Revision ID: c4ae81de4724
Revises: 4a59273b8083
Create Date: 2026-07-13 10:38:52.831821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import mysql

revision: str = 'c4ae81de4724'
down_revision: Union[str, None] = '4a59273b8083'
"""add_appointment_id_to_billings

Revision ID: c4ae81de4724
Revises: 4a59273b8083
Create Date: 2026-07-13 10:38:52.831821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import mysql

revision: str = 'c4ae81de4724'
down_revision: Union[str, None] = '4a59273b8083'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)

    # 1. Billings table changes
    billings_cols = [col['name'] for col in insp.get_columns('billings')]
    if 'appointment_id' not in billings_cols:
        op.add_column('billings', sa.Column('appointment_id', sa.Integer(), nullable=True))
        
    billings_fks = insp.get_foreign_keys('billings')
    has_apt_fk = any('appointment_id' in fk['constrained_columns'] for fk in billings_fks)
    if not has_apt_fk:
        op.create_foreign_key(None, 'billings', 'appointments', ['appointment_id'], ['id'])

    # 2. Indexes creation helper
    def safe_create_index(index_name, table_name, columns, unique=False):
        indexes = insp.get_indexes(table_name)
        existing = [idx['name'] for idx in indexes]
        if index_name not in existing:
            op.create_index(op.f(index_name), table_name, columns, unique=unique)

    def safe_drop_index(index_name, table_name):
        indexes = insp.get_indexes(table_name)
        existing = [idx['name'] for idx in indexes]
        if index_name in existing:
            op.drop_index(op.f(index_name), table_name=table_name)

    safe_create_index('ix_clinical_records_created_at', 'clinical_records', ['created_at'])
    safe_create_index('ix_doctor_medical_records_created_at', 'doctor_medical_records', ['created_at'])
    safe_create_index('ix_icu_devices_id', 'icu_devices', ['id'])
    safe_create_index('ix_icu_telemetry_alerts_id', 'icu_telemetry_alerts', ['id'])
    
    safe_drop_index('ix_icu_vital_readings_bed_recorded', 'icu_vital_readings')
    safe_create_index('ix_icu_vital_readings_id', 'icu_vital_readings', ['id'])

    # 3. Alter columns nullability helper
    def safe_alter_column(table_name, column_name, nullable, type_):
        cols = insp.get_columns(table_name)
        for col in cols:
            if col['name'] == column_name:
                if col['nullable'] != nullable:
                    op.alter_column(table_name, column_name, existing_type=type_, nullable=nullable)

    safe_alter_column('pharmacy_invoices', 'discount_percentage', nullable=False, type_=mysql.FLOAT())
    safe_alter_column('pharmacy_invoices', 'tax_percentage', nullable=False, type_=mysql.FLOAT())
    safe_alter_column('pharmacy_invoices', 'tax_amount', nullable=False, type_=mysql.FLOAT())
    safe_alter_column('staff', 'department_id', nullable=True, type_=mysql.INTEGER())

    safe_create_index('ix_staff_created_at', 'staff', ['created_at'])

    # 4. Subscriptions table changes (Already safe)
    fks = insp.get_foreign_keys('subscriptions')
    for fk in fks:
        if 'hospital_id' in fk['constrained_columns']:
            op.drop_constraint(fk['name'], 'subscriptions', type_='foreignkey')
    
    indexes = insp.get_indexes('subscriptions')
    index_names = [idx['name'] for idx in indexes]
    if 'ix_subscriptions_hospital_id' in index_names:
        op.drop_index('ix_subscriptions_hospital_id', table_name='subscriptions')
        
    columns = [col['name'] for col in insp.get_columns('subscriptions')]
    if 'hospital_id' in columns:
        op.drop_column('subscriptions', 'hospital_id')

    # 5. Transaction history indexes
    safe_create_index('ix_transaction_history_created_at', 'transaction_history', ['created_at'])
    safe_create_index('ix_transaction_history_is_deleted', 'transaction_history', ['is_deleted'])


def downgrade() -> None:
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)

    def safe_create_index(index_name, table_name, columns, unique=False):
        indexes = insp.get_indexes(table_name)
        existing = [idx['name'] for idx in indexes]
        if index_name not in existing:
            op.create_index(op.f(index_name), table_name, columns, unique=unique)

    def safe_drop_index(index_name, table_name):
        indexes = insp.get_indexes(table_name)
        existing = [idx['name'] for idx in indexes]
        if index_name in existing:
            op.drop_index(op.f(index_name), table_name=table_name)

    def safe_alter_column(table_name, column_name, nullable, type_):
        cols = insp.get_columns(table_name)
        for col in cols:
            if col['name'] == column_name:
                if col['nullable'] != nullable:
                    op.alter_column(table_name, column_name, existing_type=type_, nullable=nullable)

    # 1. Transaction history
    safe_drop_index('ix_transaction_history_is_deleted', 'transaction_history')
    safe_drop_index('ix_transaction_history_created_at', 'transaction_history')

    # 2. Subscriptions
    columns = [col['name'] for col in insp.get_columns('subscriptions')]
    if 'hospital_id' not in columns:
        op.add_column('subscriptions', sa.Column('hospital_id', mysql.INTEGER(), autoincrement=False, nullable=False))
        
    fks = insp.get_foreign_keys('subscriptions')
    has_hospital_fk = any('hospital_id' in fk['constrained_columns'] for fk in fks)
    if not has_hospital_fk:
        op.create_foreign_key(op.f('subscriptions_ibfk_1'), 'subscriptions', 'hospitals', ['hospital_id'], ['id'], ondelete='CASCADE')

    safe_create_index('ix_subscriptions_hospital_id', 'subscriptions', ['hospital_id'])

    # 3. Staff and Pharmacy Invoices
    safe_drop_index('ix_staff_created_at', 'staff')
    safe_alter_column('staff', 'department_id', nullable=False, type_=mysql.INTEGER())
    safe_alter_column('pharmacy_invoices', 'tax_amount', nullable=True, type_=mysql.FLOAT())
    safe_alter_column('pharmacy_invoices', 'tax_percentage', nullable=True, type_=mysql.FLOAT())
    safe_alter_column('pharmacy_invoices', 'discount_percentage', nullable=True, type_=mysql.FLOAT())

    # 4. ICU Vitals and Telemetry Alerts
    safe_drop_index('ix_icu_vital_readings_id', 'icu_vital_readings')
    safe_create_index('ix_icu_vital_readings_bed_recorded', 'icu_vital_readings', ['bed_id', 'recorded_at'])
    safe_drop_index('ix_icu_telemetry_alerts_id', 'icu_telemetry_alerts')
    safe_drop_index('ix_icu_devices_id', 'icu_devices')

    # 5. Doctor Medical Records & Clinical Records
    safe_drop_index('ix_doctor_medical_records_created_at', 'doctor_medical_records')
    safe_drop_index('ix_clinical_records_created_at', 'clinical_records')

    # 6. Billings
    billings_fks = insp.get_foreign_keys('billings')
    for fk in billings_fks:
        if 'appointment_id' in fk['constrained_columns']:
            op.drop_constraint(fk['name'], 'billings', type_='foreignkey')

    billings_cols = [col['name'] for col in insp.get_columns('billings')]
    if 'appointment_id' in billings_cols:
        op.drop_column('billings', 'appointment_id')
    # ### end Alembic commands ###
