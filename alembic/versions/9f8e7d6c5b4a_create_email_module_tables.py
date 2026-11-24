"""create_email_module_tables

Revision ID: e1a2b3c4d5e6
Revises: 0c0455c0724a
Create Date: 2026-11-19 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = 'e1a2b3c4d5e6'
down_revision: Union[str, None] = '0c0455c0724a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. email_templates
    if 'email_templates' not in existing_tables:
        op.create_table(
            'email_templates',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('hospital_id', sa.Integer(), nullable=True),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('subject', sa.String(length=255), nullable=False),
            sa.Column('body_html', sa.Text(), nullable=False),
            sa.Column('body_text', sa.Text(), nullable=True),
            sa.Column('language', sa.String(length=20), server_default='en', nullable=False),
            sa.Column('variables', sa.JSON(), nullable=True),
            sa.Column('category', sa.String(length=50), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_email_templates_hospital_id'), 'email_templates', ['hospital_id'], unique=False)
        op.create_index(op.f('ix_email_templates_name'), 'email_templates', ['name'], unique=False)
        op.create_index(op.f('ix_email_templates_is_active'), 'email_templates', ['is_active'], unique=False)
        op.create_index(op.f('ix_email_templates_created_at'), 'email_templates', ['created_at'], unique=False)

    # 2. email_campaigns
    if 'email_campaigns' not in existing_tables:
        op.create_table(
            'email_campaigns',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('hospital_id', sa.Integer(), nullable=True),
            sa.Column('campaign_name', sa.String(length=255), nullable=False),
            sa.Column('template_id', sa.Integer(), nullable=True),
            sa.Column('message_content', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=50), server_default='DRAFT', nullable=False),
            sa.Column('scheduled_at', sa.DateTime(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('total_recipients', sa.Integer(), server_default='0', nullable=False),
            sa.Column('sent_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('failed_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('skipped_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['template_id'], ['email_templates.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_email_campaigns_hospital_id'), 'email_campaigns', ['hospital_id'], unique=False)
        op.create_index(op.f('ix_email_campaigns_template_id'), 'email_campaigns', ['template_id'], unique=False)
        op.create_index(op.f('ix_email_campaigns_status'), 'email_campaigns', ['status'], unique=False)
        op.create_index(op.f('ix_email_campaigns_scheduled_at'), 'email_campaigns', ['scheduled_at'], unique=False)
        op.create_index(op.f('ix_email_campaigns_created_at'), 'email_campaigns', ['created_at'], unique=False)

    # 3. email_batches
    if 'email_batches' not in existing_tables:
        op.create_table(
            'email_batches',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('batch_id', sa.String(length=100), nullable=False),
            sa.Column('hospital_id', sa.Integer(), nullable=True),
            sa.Column('batch_type', sa.String(length=50), nullable=False),
            sa.Column('status', sa.String(length=50), server_default='PENDING', nullable=False),
            sa.Column('total_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('sent_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('failed_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('skipped_count', sa.Integer(), server_default='0', nullable=False),
            sa.Column('results_summary', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_email_batches_batch_id'), 'email_batches', ['batch_id'], unique=True)
        op.create_index(op.f('ix_email_batches_hospital_id'), 'email_batches', ['hospital_id'], unique=False)
        op.create_index(op.f('ix_email_batches_batch_type'), 'email_batches', ['batch_type'], unique=False)
        op.create_index(op.f('ix_email_batches_status'), 'email_batches', ['status'], unique=False)
        op.create_index(op.f('ix_email_batches_created_at'), 'email_batches', ['created_at'], unique=False)

    # 4. email_messages
    if 'email_messages' not in existing_tables:
        op.create_table(
            'email_messages',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('hospital_id', sa.Integer(), nullable=True),
            sa.Column('batch_id', sa.String(length=100), nullable=True),
            sa.Column('campaign_id', sa.Integer(), nullable=True),
            sa.Column('patient_id', sa.Integer(), nullable=True),
            sa.Column('appointment_id', sa.Integer(), nullable=True),
            sa.Column('discharge_id', sa.Integer(), nullable=True),
            sa.Column('recipient_email', sa.String(length=255), nullable=False),
            sa.Column('subject', sa.String(length=255), nullable=False),
            sa.Column('body_html', sa.Text(), nullable=False),
            sa.Column('body_text', sa.Text(), nullable=True),
            sa.Column('media_url', sa.String(length=500), nullable=True),
            sa.Column('message_type', sa.String(length=50), nullable=False),
            sa.Column('source_type', sa.String(length=50), nullable=False),
            sa.Column('target_follow_up_date', sa.Date(), nullable=True),
            sa.Column('idempotency_key', sa.String(length=190), nullable=True),
            sa.Column('status', sa.String(length=50), server_default='PENDING', nullable=False),
            sa.Column('failure_reason', sa.Text(), nullable=True),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['batch_id'], ['email_batches.batch_id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['campaign_id'], ['email_campaigns.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['discharge_id'], ['discharges.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_email_messages_hospital_id'), 'email_messages', ['hospital_id'], unique=False)
        op.create_index(op.f('ix_email_messages_batch_id'), 'email_messages', ['batch_id'], unique=False)
        op.create_index(op.f('ix_email_messages_campaign_id'), 'email_messages', ['campaign_id'], unique=False)
        op.create_index(op.f('ix_email_messages_patient_id'), 'email_messages', ['patient_id'], unique=False)
        op.create_index(op.f('ix_email_messages_appointment_id'), 'email_messages', ['appointment_id'], unique=False)
        op.create_index(op.f('ix_email_messages_discharge_id'), 'email_messages', ['discharge_id'], unique=False)
        op.create_index(op.f('ix_email_messages_recipient_email'), 'email_messages', ['recipient_email'], unique=False)
        op.create_index(op.f('ix_email_messages_target_follow_up_date'), 'email_messages', ['target_follow_up_date'], unique=False)
        op.create_index(op.f('ix_email_messages_idempotency_key'), 'email_messages', ['idempotency_key'], unique=True)
        op.create_index(op.f('ix_email_messages_status'), 'email_messages', ['status'], unique=False)
        op.create_index(op.f('ix_email_messages_created_at'), 'email_messages', ['created_at'], unique=False)

    # 5. email_deliveries
    if 'email_deliveries' not in existing_tables:
        op.create_table(
            'email_deliveries',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('message_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['message_id'], ['email_messages.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_email_deliveries_message_id'), 'email_deliveries', ['message_id'], unique=False)
        op.create_index(op.f('ix_email_deliveries_status'), 'email_deliveries', ['status'], unique=False)
        op.create_index(op.f('ix_email_deliveries_created_at'), 'email_deliveries', ['created_at'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = set(inspector.get_table_names())

    if 'email_deliveries' in existing_tables:
        op.drop_table('email_deliveries')
    if 'email_messages' in existing_tables:
        op.drop_table('email_messages')
    if 'email_batches' in existing_tables:
        op.drop_table('email_batches')
    if 'email_campaigns' in existing_tables:
        op.drop_table('email_campaigns')
    if 'email_templates' in existing_tables:
        op.drop_table('email_templates')

