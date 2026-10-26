"""Store carrier route availability declarations.

Revision ID: 0012_route_availabilities
Revises: 0011_georef_location_provenance
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_route_availabilities"
down_revision = "0011_georef_location_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("route_availabilities"):
        op.create_table(
            "route_availabilities",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("carrier_id", sa.String(length=64), sa.ForeignKey("carriers.id"), nullable=False),
            sa.Column("test_run_id", sa.String(length=64), nullable=True),
            sa.Column("origin", sa.Text(), nullable=False),
            sa.Column("destination", sa.Text(), nullable=False),
            sa.Column("stops", sa.JSON(), nullable=False),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("capacity", sa.Numeric(14, 3), nullable=True),
            sa.Column("capacity_unit", sa.String(length=32), nullable=True),
            sa.Column("cargo_types", sa.JSON(), nullable=False),
            sa.Column("equipment_types", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("committed_shipment_id", sa.String(length=64), nullable=True),
            sa.Column("declared_by_user_id", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("route_availabilities")}
    for name, column in (
        ("ix_route_availabilities_carrier_id", "carrier_id"),
        ("ix_route_availabilities_test_run_id", "test_run_id"),
        ("ix_route_availabilities_status", "status"),
    ):
        if name not in indexes:
            op.create_index(name, "route_availabilities", [column])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("route_availabilities"):
        indexes = {item["name"] for item in inspector.get_indexes("route_availabilities")}
        for name in (
            "ix_route_availabilities_status",
            "ix_route_availabilities_test_run_id",
            "ix_route_availabilities_carrier_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="route_availabilities")
        op.drop_table("route_availabilities")
