"""media assets schema

Revision ID: 0003_media_assets
Revises: 0002_carrier_onboarding
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_media_assets"
down_revision = "0002_carrier_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("media_assets"):
        op.create_table(
            "media_assets",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("message_id", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("provider_media_id", sa.String(length=128), nullable=True),
            sa.Column("media_type", sa.String(length=64), nullable=False),
            sa.Column("mime_type", sa.String(length=128), nullable=True),
            sa.Column("file_name", sa.Text(), nullable=True),
            sa.Column("external_url", sa.Text(), nullable=True),
            sa.Column("storage_uri", sa.Text(), nullable=True),
            sa.Column("sha256", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("media_assets")}
    for name, column in (("ix_media_assets_message_id", "message_id"), ("ix_media_assets_provider_media_id", "provider_media_id")):
        if name not in indexes:
            op.create_index(name, "media_assets", [column])
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    if "media_asset_id" not in message_columns:
        op.add_column("messages", sa.Column("media_asset_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("media_asset_id")

    op.drop_index("ix_media_assets_provider_media_id", table_name="media_assets")
    op.drop_index("ix_media_assets_message_id", table_name="media_assets")
    op.drop_table("media_assets")
