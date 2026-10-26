"""Persist WhatsApp carrier-onboarding capture context.

Revision ID: 0008_capture_context
Revises: 0007_driver_vehicle_review_gate
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_capture_context"
down_revision = "0007_driver_vehicle_review_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("carrier_onboarding")}
    if "capture_context" not in existing:
        op.add_column(
            "carrier_onboarding",
            sa.Column("capture_context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    op.drop_column("carrier_onboarding", "capture_context")
