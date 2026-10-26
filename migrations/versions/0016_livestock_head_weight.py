"""Store declared livestock weight per head.

Revision ID: 0016_livestock_head_weight
Revises: 0015_route_availability_capture
Create Date: 2026-10-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_livestock_head_weight"
down_revision = "0015_route_availability_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("shipment_requests")}
    if "weight_per_head_kg" not in columns:
        op.add_column(
            "shipment_requests",
            sa.Column("weight_per_head_kg", sa.Numeric(12, 2), nullable=True),
        )


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("shipment_requests")}
    if "weight_per_head_kg" in columns:
        op.drop_column("shipment_requests", "weight_per_head_kg")
