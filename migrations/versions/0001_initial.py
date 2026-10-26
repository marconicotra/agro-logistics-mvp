"""initial schema

Revision ID: 0001_initial
Revises: None
Create Date: 2026-04-26
"""
from alembic import op

from app.infrastructure.db.base import Base
from app.infrastructure.db import models  # noqa: F401


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Later catalog/routing migrations own their DDL and server-side seed defaults.
    # Do not eagerly create these future tables from the live ORM metadata.
    later_tables = {"geographic_catalog", "cargo_categories", "cargo_types", "routing_operations"}
    Base.metadata.create_all(bind=op.get_bind(), tables=[t for t in Base.metadata.sorted_tables if t.name not in later_tables])


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

