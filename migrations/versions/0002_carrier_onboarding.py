"""carrier onboarding schema

Revision ID: 0002_carrier_onboarding
Revises: 0001_initial
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_carrier_onboarding"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in {
        "carriers": [
            sa.Column("email", sa.Text(), nullable=True),
            sa.Column("company_name", sa.Text(), nullable=True),
            sa.Column("cuit", sa.String(length=32), nullable=True),
            sa.Column("truck_count", sa.Integer(), nullable=True),
            sa.Column("truck_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("truck_body_type", sa.Text(), nullable=True),
            sa.Column("validation_status", sa.String(length=64), nullable=False, server_default="DRAFT"),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("reviewed_by_user_id", sa.String(length=64), nullable=True),
        ],
        "documents": [
            sa.Column("provider", sa.String(length=64), nullable=True),
            sa.Column("provider_media_id", sa.String(length=128), nullable=True),
            sa.Column("mime_type", sa.String(length=128), nullable=True),
            sa.Column("file_name", sa.Text(), nullable=True),
            sa.Column("storage_uri", sa.Text(), nullable=True),
            sa.Column("uploaded_by_phone", sa.String(length=64), nullable=True),
            sa.Column("reviewed_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
        ],
    }.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)

    if not inspector.has_table("carrier_onboarding"):
        op.create_table(
            "carrier_onboarding",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("carrier_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("required_fields", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("missing_fields", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["carrier_id"], ["carriers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("carrier_onboarding")}
    for name, column in (("ix_carrier_onboarding_carrier_id", "carrier_id"), ("ix_carrier_onboarding_status", "status")):
        if name not in indexes:
            op.create_index(name, "carrier_onboarding", [column])


def downgrade() -> None:
    op.drop_index("ix_carrier_onboarding_status", table_name="carrier_onboarding")
    op.drop_index("ix_carrier_onboarding_carrier_id", table_name="carrier_onboarding")
    op.drop_table("carrier_onboarding")

    with op.batch_alter_table("documents") as batch:
        batch.drop_column("rejection_reason")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_user_id")
        batch.drop_column("uploaded_by_phone")
        batch.drop_column("storage_uri")
        batch.drop_column("file_name")
        batch.drop_column("mime_type")
        batch.drop_column("provider_media_id")
        batch.drop_column("provider")

    with op.batch_alter_table("carriers") as batch:
        batch.drop_column("reviewed_by_user_id")
        batch.drop_column("rejection_reason")
        batch.drop_column("rejected_at")
        batch.drop_column("validated_at")
        batch.drop_column("validation_status")
        batch.drop_column("truck_body_type")
        batch.drop_column("truck_types")
        batch.drop_column("truck_count")
        batch.drop_column("cuit")
        batch.drop_column("company_name")
        batch.drop_column("email")
