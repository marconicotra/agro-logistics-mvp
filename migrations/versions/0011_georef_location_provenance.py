"""Add Georef identity and provenance to declared locations.

Revision ID: 0011_georef_location_provenance
Revises: 0010_operator_roles
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_georef_location_provenance"
down_revision = "0010_operator_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("locations")}
    if "georef_id" not in existing:
        op.add_column("locations", sa.Column("georef_id", sa.String(length=32), nullable=True))
    if "catalog_version" not in existing:
        op.add_column("locations", sa.Column("catalog_version", sa.String(length=128), nullable=True))
    if "provenance" not in existing:
        op.add_column(
            "locations",
            sa.Column("provenance", sa.String(length=32), server_default="USER_DECLARED", nullable=False),
        )
        op.alter_column("locations", "provenance", server_default=None)


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("locations")}
    for column in ("provenance", "catalog_version", "georef_id"):
        if column in existing:
            op.drop_column("locations", column)
