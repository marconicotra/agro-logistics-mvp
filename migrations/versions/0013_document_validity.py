"""Add declared document validity and renewal linkage.

Revision ID: 0013_document_validity
Revises: 0012_route_availabilities
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_document_validity"
down_revision = "0012_route_availabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    for name, column in (
        ("valid_from", sa.Column("valid_from", sa.Date(), nullable=True)),
        ("expires_at", sa.Column("expires_at", sa.Date(), nullable=True)),
        ("supersedes_document_id", sa.Column("supersedes_document_id", sa.String(length=64), nullable=True)),
    ):
        if name not in existing:
            op.add_column("documents", column)


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    for name in ("supersedes_document_id", "expires_at", "valid_from"):
        if name in existing:
            op.drop_column("documents", name)
