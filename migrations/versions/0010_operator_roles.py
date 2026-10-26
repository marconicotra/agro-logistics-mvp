"""Add server-managed backoffice roles for Supabase Auth identities.

Revision ID: 0010_operator_roles
Revises: 0009_notification_outbox
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_operator_roles"
down_revision = "0009_notification_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("operator_roles"):
        op.create_table(
            "operator_roles",
            sa.Column("user_id", sa.String(length=128), primary_key=True),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("assigned_by_user_id", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("role IN ('operator', 'admin')", name="ck_operator_roles_role"),
        )
    else:
        constraints = {item.get("name") for item in inspector.get_check_constraints("operator_roles")}
        if "ck_operator_roles_role" not in constraints:
            op.create_check_constraint(
                "ck_operator_roles_role",
                "operator_roles",
                "role IN ('operator', 'admin')",
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("operator_roles"):
        constraints = {item.get("name") for item in inspector.get_check_constraints("operator_roles")}
        if "ck_operator_roles_role" in constraints:
            op.drop_constraint("ck_operator_roles_role", "operator_roles", type_="check")
        op.drop_table("operator_roles")
