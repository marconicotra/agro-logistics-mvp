"""Persist WhatsApp route availability capture context.

Revision ID: 0015_route_availability_capture
Revises: 0014_conv_history_idx
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_route_availability_capture"
down_revision = "0014_conv_history_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("conversation_sessions")}
    if "route_availability_capture" not in columns:
        op.add_column(
            "conversation_sessions",
            sa.Column("route_availability_capture", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.alter_column("conversation_sessions", "route_availability_capture", server_default=None)


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("conversation_sessions")}
    if "route_availability_capture" in columns:
        op.drop_column("conversation_sessions", "route_availability_capture")
