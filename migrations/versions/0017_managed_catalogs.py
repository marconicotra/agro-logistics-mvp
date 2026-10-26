"""Create maintained geography and cargo catalogs.

Revision ID: 0017_managed_catalogs
Revises: 0016_livestock_head_weight
Create Date: 2026-10-25
"""

import csv
from pathlib import Path
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


revision = "0017_managed_catalogs"
down_revision = "0016_livestock_head_weight"
branch_labels = None
depends_on = None


def _fold(value: str) -> str:
    plain = "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def upgrade() -> None:
    op.create_table(
        "geographic_catalog",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(256), nullable=False),
        sa.Column("parent_id", sa.String(96), sa.ForeignKey("geographic_catalog.id"), nullable=True),
        sa.Column("georef_id", sa.String(32), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(32), nullable=False, server_default="MANUAL"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kind", "georef_id", name="uq_geographic_catalog_kind_georef"),
    )
    op.create_index("ix_geographic_catalog_kind", "geographic_catalog", ["kind"])
    op.create_index("ix_geographic_catalog_normalized_name", "geographic_catalog", ["normalized_name"])
    op.create_index("ix_geographic_catalog_active", "geographic_catalog", ["active"])
    op.create_index(
        "ix_geographic_catalog_kind_parent_active", "geographic_catalog", ["kind", "parent_id", "active"]
    )

    op.create_table(
        "cargo_categories",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cargo_categories_active", "cargo_categories", ["active"])
    op.create_table(
        "cargo_types",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("category_code", sa.String(64), sa.ForeignKey("cargo_categories.code"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cargo_types_active", "cargo_types", ["active"])
    op.create_index("ix_cargo_types_category_active", "cargo_types", ["category_code", "active"])

    bind = op.get_bind()
    categories = sa.table(
        "cargo_categories",
        sa.column("code", sa.String), sa.column("name", sa.Text), sa.column("aliases", sa.JSON),
        sa.column("active", sa.Boolean), sa.column("sort_order", sa.Integer),
    )
    types = sa.table(
        "cargo_types",
        sa.column("code", sa.String), sa.column("category_code", sa.String), sa.column("name", sa.Text),
        sa.column("aliases", sa.JSON), sa.column("active", sa.Boolean), sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(categories, [
        {"code": "LIVESTOCK", "name": "Hacienda", "aliases": ["ganado"], "active": True, "sort_order": 10},
        {"code": "GRAIN", "name": "Granos", "aliases": ["cereales"], "active": True, "sort_order": 20},
    ])
    cargo_types = [
        ("LIVESTOCK", "novillos", ["novillo"]),
        ("LIVESTOCK", "vacas", ["vaca"]),
        ("LIVESTOCK", "terneros", ["ternero"]),
        ("LIVESTOCK", "terneras", ["ternera"]),
        ("LIVESTOCK", "vaquillonas", ["vaquillona"]),
        ("LIVESTOCK", "toros", ["toro"]),
        ("LIVESTOCK", "hacienda", []),
        ("GRAIN", "soja", []),
        ("GRAIN", "maíz", ["maiz"]),
        ("GRAIN", "trigo", []),
        ("GRAIN", "girasol", []),
        ("GRAIN", "sorgo", []),
        ("GRAIN", "cebada", []),
    ]
    op.bulk_insert(types, [
        {"code": _fold(name).replace(" ", "_"), "category_code": category, "name": name,
         "aliases": aliases, "active": True, "sort_order": index * 10}
        for index, (category, name, aliases) in enumerate(cargo_types, start=1)
    ])

    catalog = sa.table(
        "geographic_catalog",
        sa.column("id", sa.String), sa.column("kind", sa.String), sa.column("name", sa.Text),
        sa.column("normalized_name", sa.String), sa.column("parent_id", sa.String),
        sa.column("georef_id", sa.String), sa.column("aliases", sa.JSON), sa.column("source", sa.String),
        sa.column("active", sa.Boolean),
    )
    csv_path = Path(__file__).resolve().parents[2] / "data/catalogs/georef/localidades.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    provinces: dict[str, dict[str, object]] = {}
    departments: dict[tuple[str, str], dict[str, object]] = {}
    localities: dict[str, dict[str, object]] = {}
    for row in rows:
        province_id = row["provincia_id"]
        province_key = f"province:{province_id}"
        provinces[province_id] = {
            "id": province_key, "kind": "PROVINCE", "name": row["provincia_nombre"],
            "normalized_name": _fold(row["provincia_nombre"]), "parent_id": None,
            "georef_id": province_id, "aliases": [], "source": "GEOREF", "active": True,
        }
        department_id = row.get("departamento_id")
        department_name = row.get("departamento_nombre")
        if department_id and department_name:
            department_key = (province_id, department_id)
            departments[department_key] = {
                "id": f"department:{province_id}:{department_id}", "kind": "DEPARTMENT", "name": department_name,
                "normalized_name": _fold(department_name), "parent_id": province_key,
                "georef_id": department_id, "aliases": [], "source": "GEOREF", "active": True,
            }
        if row.get("categoria") != "Entidad":
            locality_id = row.get("id")
            if locality_id:
                localities[locality_id] = {
                    "id": f"locality:{locality_id}", "kind": "LOCALITY", "name": row["nombre"],
                    "normalized_name": _fold(row["nombre"]),
                    "parent_id": f"department:{province_id}:{department_id}" if department_id and department_name else province_key,
                    "georef_id": locality_id, "aliases": [], "source": "GEOREF", "active": True,
                }

    for batch in (list(provinces.values()), list(departments.values()), list(localities.values())):
        if batch:
            op.bulk_insert(catalog, batch)


def downgrade() -> None:
    op.drop_table("cargo_types")
    op.drop_table("cargo_categories")
    op.drop_table("geographic_catalog")
