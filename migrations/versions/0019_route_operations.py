"""Persistent declared routes, dispatch decisions and trip check-ins."""
from alembic import op
import sqlalchemy as sa

revision = "0019_route_operations"
down_revision = "0018_jauregui_geo_localities"
branch_labels = None
depends_on = None


def _create_table(name, *args, **kwargs):
    # 0001 historically created current metadata; support a fresh full chain as
    # well as databases upgraded from their actual historical schema.
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *args, **kwargs)


def _create_index(name, table, columns, **kwargs):
    if name not in {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns, **kwargs)


def upgrade():
    _create_table("routing_operations",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.String(96), nullable=False),
        sa.Column("test_run_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _create_index("ix_routing_due", "routing_operations", ["kind", "status", "due_at"])
    _create_index("ix_routing_scope", "routing_operations", ["kind", "test_run_id", "entity_id"])
    for name, typ in [("latitude", sa.Float()), ("longitude", sa.Float()), ("coordinate_source", sa.String(32)), ("coordinate_precision", sa.String(32))]:
        if name not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("locations")}:
            op.add_column("locations", sa.Column(name, typ, nullable=True))

    if "required_equipment_type" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("shipment_requests")}:
        op.add_column("shipment_requests", sa.Column("required_equipment_type", sa.String(100), nullable=True))


def downgrade():
    if "required_equipment_type" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("shipment_requests")}:
        op.drop_column("shipment_requests", "required_equipment_type")
    for name in ["coordinate_precision", "coordinate_source", "longitude", "latitude"]:
        op.drop_column("locations", name)
    op.drop_table("routing_operations")
