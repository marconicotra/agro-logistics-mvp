"""Add durable transactional notification outbox.

Revision ID: 0009_notification_outbox
Revises: 0008_capture_context
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_notification_outbox"
down_revision = "0008_capture_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("notification_outbox"):
        op.create_table(
            "notification_outbox",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("idempotency_key", sa.String(length=256), nullable=False, unique=True),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("provider_scope", sa.String(length=128), nullable=True),
            sa.Column("message_payload", sa.JSON(), nullable=False),
            sa.Column("entity_type", sa.String(length=64), nullable=True),
            sa.Column("entity_id", sa.String(length=64), nullable=True),
            sa.Column("test_run_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_message_id", sa.String(length=128), nullable=True),
            sa.Column("last_error_code", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("notification_outbox")}
    if "ix_notification_outbox_dispatch" not in indexes:
        op.create_index(
            "ix_notification_outbox_dispatch",
            "notification_outbox",
            ["status", "available_at", "created_at"],
        )
    if "ix_notification_outbox_test_run_id" not in indexes:
        op.create_index("ix_notification_outbox_test_run_id", "notification_outbox", ["test_run_id"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("notification_outbox"):
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("notification_outbox")}
        if "ix_notification_outbox_test_run_id" in indexes:
            op.drop_index("ix_notification_outbox_test_run_id", table_name="notification_outbox")
        if "ix_notification_outbox_dispatch" in indexes:
            op.drop_index("ix_notification_outbox_dispatch", table_name="notification_outbox")
        op.drop_table("notification_outbox")
