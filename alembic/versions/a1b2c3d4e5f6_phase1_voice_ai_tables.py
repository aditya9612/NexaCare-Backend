"""Phase 1 Voice AI: hospital voice config, FAQ, preferred language, call analytics fields

Revision ID: a1b2c3d4e5f6
Revises: 21449ef446a4
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "21449ef446a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("preferred_language", sa.String(length=10), nullable=True),
    )
    op.create_index(
        "ix_patients_preferred_language",
        "patients",
        ["preferred_language"],
    )

    op.create_table(
        "hospital_voice_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("telephony_provider", sa.String(length=20), nullable=False, server_default="twilio"),
        sa.Column("voice_gender", sa.String(length=20), nullable=False, server_default="female"),
        sa.Column("voice_profile", sa.String(length=100), nullable=True),
        sa.Column("default_language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("reception_number", sa.String(length=20), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("from_number", sa.String(length=20), nullable=True),
        sa.Column("inbound_did", sa.String(length=20), nullable=True),
        sa.Column("exotel_sid", sa.String(length=100), nullable=True),
        sa.Column("exotel_api_key", sa.String(length=100), nullable=True),
        sa.Column("exotel_api_token", sa.String(length=100), nullable=True),
        sa.Column("exotel_subdomain", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("hospital_id", name="uq_hospital_voice_configs_hospital_id"),
    )
    op.create_index("ix_hospital_voice_configs_hospital_id", "hospital_voice_configs", ["hospital_id"])
    op.create_index("ix_hospital_voice_configs_inbound_did", "hospital_voice_configs", ["inbound_did"])
    op.create_index(
        "ix_hospital_voice_configs_telephony_provider",
        "hospital_voice_configs",
        ["telephony_provider"],
    )

    op.create_table(
        "hospital_faqs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("tags", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_hospital_faqs_hospital_id", "hospital_faqs", ["hospital_id"])
    op.create_index("ix_hospital_faqs_language", "hospital_faqs", ["language"])

    op.create_table(
        "hospital_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_hospital_policies_hospital_id", "hospital_policies", ["hospital_id"])

    op.create_table(
        "hospital_voice_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_hospital_voice_documents_hospital_id",
        "hospital_voice_documents",
        ["hospital_id"],
    )

    op.create_table(
        "voice_callback_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id"), nullable=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("call_id", sa.Integer(), sa.ForeignKey("voice_calls.id"), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_voice_callback_tickets_phone", "voice_callback_tickets", ["phone"])
    op.create_index("ix_voice_callback_tickets_status", "voice_callback_tickets", ["status"])

    op.add_column("voice_calls", sa.Column("hospital_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_voice_calls_hospital_id",
        "voice_calls",
        "hospitals",
        ["hospital_id"],
        ["id"],
    )
    op.create_index("ix_voice_calls_hospital_id", "voice_calls", ["hospital_id"])
    op.add_column("voice_calls", sa.Column("provider", sa.String(length=20), nullable=True))
    op.create_index("ix_voice_calls_provider", "voice_calls", ["provider"])
    op.add_column("voice_calls", sa.Column("intent", sa.String(length=50), nullable=True))
    op.add_column(
        "voice_calls",
        sa.Column("faq_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "voice_calls",
        sa.Column("ai_fallback", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("voice_calls", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "voice_calls",
        sa.Column(
            "transferred_to_reception",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "voice_calls",
        sa.Column("transfer_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "voice_calls",
        sa.Column("booking_success", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    op.add_column(
        "call_analytics",
        sa.Column("transfer_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "call_analytics",
        sa.Column("faq_success_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "call_analytics",
        sa.Column("ai_fallback_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "call_analytics",
        sa.Column("booking_success_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "call_analytics",
        sa.Column("retry_total", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("call_analytics", "retry_total")
    op.drop_column("call_analytics", "booking_success_count")
    op.drop_column("call_analytics", "ai_fallback_count")
    op.drop_column("call_analytics", "faq_success_count")
    op.drop_column("call_analytics", "transfer_count")

    op.drop_column("voice_calls", "booking_success")
    op.drop_column("voice_calls", "transfer_status")
    op.drop_column("voice_calls", "transferred_to_reception")
    op.drop_column("voice_calls", "confidence")
    op.drop_column("voice_calls", "ai_fallback")
    op.drop_column("voice_calls", "faq_hit")
    op.drop_column("voice_calls", "intent")
    op.drop_index("ix_voice_calls_provider", table_name="voice_calls")
    op.drop_column("voice_calls", "provider")
    op.drop_index("ix_voice_calls_hospital_id", table_name="voice_calls")
    op.drop_constraint("fk_voice_calls_hospital_id", "voice_calls", type_="foreignkey")
    op.drop_column("voice_calls", "hospital_id")

    op.drop_table("voice_callback_tickets")
    op.drop_table("hospital_voice_documents")
    op.drop_table("hospital_policies")
    op.drop_table("hospital_faqs")
    op.drop_table("hospital_voice_configs")

    op.drop_index("ix_patients_preferred_language", table_name="patients")
    op.drop_column("patients", "preferred_language")
