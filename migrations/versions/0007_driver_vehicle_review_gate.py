"""Add driver identity and independent driver/vehicle review state.

Revision ID: 0007_driver_vehicle_review_gate
Revises: 0006_test_run_scoping
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_driver_vehicle_review_gate"
down_revision = "0006_test_run_scoping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("drivers"):
        op.create_table(
            "drivers",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("carrier_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("license_category", sa.String(length=32), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("validation_status", sa.String(length=64), nullable=False),
            sa.Column("reviewed_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["carrier_id"], ["carriers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_drivers_carrier_id" not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("drivers")}:
        op.create_index("ix_drivers_carrier_id", "drivers", ["carrier_id"])

    vehicle_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("vehicles")}
    for column in (
        sa.Column("validation_status", sa.String(length=64), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("reviewed_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in vehicle_columns:
            op.add_column("vehicles", column)

    trip_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("trips")}
    if "driver_id" not in trip_columns:
        op.add_column("trips", sa.Column("driver_id", sa.String(length=64), nullable=True))
    trip_foreign_keys = {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("trips")}
    if "fk_trips_driver_id_drivers" not in trip_foreign_keys:
        op.create_foreign_key(
            "fk_trips_driver_id_drivers", "trips", "drivers", ["driver_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("trips") as batch:
        batch.drop_constraint("fk_trips_driver_id_drivers", type_="foreignkey")
        batch.drop_column("driver_id")

    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_user_id")
        batch.drop_column("validation_status")

    op.drop_index("ix_drivers_carrier_id", table_name="drivers")
    op.drop_table("drivers")
