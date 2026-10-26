"""whatsapp allowlist contacts

Revision ID: 0004_whatsapp_allowed_contacts
Revises: 0003_media_assets
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_whatsapp_allowed_contacts"
down_revision = "0003_media_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("whatsapp_allowed_contacts"):
        op.create_table(
            "whatsapp_allowed_contacts",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("phone_number", sa.String(length=64), nullable=False),
            sa.Column("normalized_phone_number", sa.String(length=64), nullable=False),
            sa.Column("label", sa.Text(), nullable=True),
            sa.Column("environment", sa.String(length=32), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("whatsapp_allowed_contacts")}
    definitions = (
        ("ix_whatsapp_allowed_contacts_normalized_phone_number", ["normalized_phone_number"]),
        ("ix_whatsapp_allowed_contacts_phone_env_provider", ["normalized_phone_number", "environment", "provider"]),
        ("ix_whatsapp_allowed_contacts_status", ["status"]),
    )
    for name, columns in definitions:
        if name not in indexes:
            op.create_index(name, "whatsapp_allowed_contacts", columns)


def downgrade() -> None:
    op.drop_index("ix_whatsapp_allowed_contacts_status", table_name="whatsapp_allowed_contacts")
    op.drop_index(
        "ix_whatsapp_allowed_contacts_phone_env_provider",
        table_name="whatsapp_allowed_contacts",
    )
    op.drop_index(
        "ix_whatsapp_allowed_contacts_normalized_phone_number",
        table_name="whatsapp_allowed_contacts",
    )
    op.drop_table("whatsapp_allowed_contacts")
