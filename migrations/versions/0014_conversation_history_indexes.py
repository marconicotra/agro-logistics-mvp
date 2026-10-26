"""Add indexes for chronological conversation history pagination.

Revision ID: 0014_conv_history_idx
Revises: 0013_document_validity
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_conv_history_idx"
down_revision = "0013_document_validity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("messages")}
    if "ix_messages_conversation_occurred_at" not in indexes:
        op.create_index(
            "ix_messages_conversation_occurred_at",
            "messages",
            ["conversation_session_id", sa.text("COALESCE(received_at, sent_at, created_at)"), "id"],
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("event_logs")}
    if "ix_event_logs_conversation_reply_failed" not in indexes:
        op.create_index(
            "ix_event_logs_conversation_reply_failed",
            "event_logs",
            ["entity_type", "entity_id", "event_type", "occurred_at", "event_id"],
        )


def downgrade() -> None:
    for table, name in (
        ("event_logs", "ix_event_logs_conversation_reply_failed"),
        ("messages", "ix_messages_conversation_occurred_at"),
    ):
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if name in indexes:
            op.drop_index(name, table_name=table)
