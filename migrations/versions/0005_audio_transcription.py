"""audio transcription fields for media assets

Revision ID: 0005_audio_transcription
Revises: 0004_whatsapp_allowed_contacts
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_audio_transcription"
down_revision = "0004_whatsapp_allowed_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("media_assets")}
    columns = (
        sa.Column("transcription_status", sa.String(length=64), nullable=False, server_default="NOT_REQUIRED"),
        sa.Column("transcription_text", sa.Text(), nullable=True),
        sa.Column("transcription_provider", sa.String(length=64), nullable=True),
        sa.Column("transcription_model", sa.String(length=128), nullable=True),
        sa.Column("transcription_error", sa.Text(), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("media_assets", column)


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("transcribed_at")
        batch.drop_column("transcription_error")
        batch.drop_column("transcription_model")
        batch.drop_column("transcription_provider")
        batch.drop_column("transcription_text")
        batch.drop_column("transcription_status")
