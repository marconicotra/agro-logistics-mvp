"""scope QA messages, events, loads and trips to a test run

Revision ID: 0006_test_run_scoping
Revises: 0005_audio_transcription
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_test_run_scoping"
down_revision = "0005_audio_transcription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    definitions = (
        ("conversation_sessions", "active_test_run_id", "ix_conversation_sessions_active_test_run_id"),
        ("messages", "test_run_id", "ix_messages_test_run_id"),
        ("shipment_requests", "test_run_id", "ix_shipment_requests_test_run_id"),
        ("trip_offers", "test_run_id", "ix_trip_offers_test_run_id"),
        ("assignments", "test_run_id", "ix_assignments_test_run_id"),
        ("trips", "test_run_id", "ix_trips_test_run_id"),
        ("event_logs", "test_run_id", "ix_event_logs_test_run_id"),
    )
    for table, column_name, index_name in definitions:
        existing_columns = {column["name"] for column in inspector.get_columns(table)}
        if column_name not in existing_columns:
            op.add_column(table, sa.Column(column_name, sa.String(length=64)))
        existing_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table, [column_name])


def downgrade() -> None:
    op.drop_index("ix_event_logs_test_run_id", table_name="event_logs")
    op.drop_index("ix_trips_test_run_id", table_name="trips")
    op.drop_index("ix_assignments_test_run_id", table_name="assignments")
    op.drop_index("ix_trip_offers_test_run_id", table_name="trip_offers")
    op.drop_index("ix_shipment_requests_test_run_id", table_name="shipment_requests")
    op.drop_index("ix_messages_test_run_id", table_name="messages")
    op.drop_index("ix_conversation_sessions_active_test_run_id", table_name="conversation_sessions")
    op.drop_column("event_logs", "test_run_id")
    op.drop_column("trips", "test_run_id")
    op.drop_column("assignments", "test_run_id")
    op.drop_column("trip_offers", "test_run_id")
    op.drop_column("shipment_requests", "test_run_id")
    op.drop_column("messages", "test_run_id")
    op.drop_column("conversation_sessions", "active_test_run_id")
