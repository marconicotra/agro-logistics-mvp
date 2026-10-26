"""Stage legacy locality values for review and add province aliases.

Revision ID: 0018_jauregui_geo_localities
Revises: 0017_managed_catalogs
Create Date: 2026-10-25
"""

import json
from pathlib import Path
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0018_jauregui_geo_localities"
down_revision = "0017_managed_catalogs"
branch_labels = None
depends_on = None


def _fold(value: str) -> str:
    plain = "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def upgrade() -> None:
    bind = op.get_bind()
    catalog = sa.table(
        "geographic_catalog",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("name", sa.Text),
        sa.column("normalized_name", sa.String),
        sa.column("parent_id", sa.String),
        sa.column("georef_id", sa.String),
        sa.column("aliases", sa.JSON),
        sa.column("source", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    province_rows = bind.execute(
        sa.select(catalog.c.id, catalog.c.name, catalog.c.aliases).where(
            catalog.c.kind == "PROVINCE"
        )
    ).all()
    provinces = {_fold(row.name): row for row in province_rows}

    province_aliases = {
        "ciudad autonoma de buenos aires": ["CABA"],
        "tierra del fuego antartida e islas del atlantico sur": ["Tierra del Fuego"],
    }
    for normalized_name, aliases_to_add in province_aliases.items():
        province = provinces.get(normalized_name)
        if province is None:
            raise RuntimeError(f"The Georef province seed is missing: {normalized_name}")
        aliases = list(province.aliases or [])
        alias_keys = {_fold(alias) for alias in aliases}
        for alias in aliases_to_add:
            if _fold(alias) not in alias_keys:
                aliases.append(alias)
                alias_keys.add(_fold(alias))
        bind.execute(
            catalog.update().where(catalog.c.id == province.id).values(
                aliases=aliases,
                updated_at=sa.func.now(),
            )
        )

    seed_path = Path(__file__).resolve().parents[2] / "data/catalogs/jauregui_lorda/localidades_para_revision.json"
    records = json.loads(seed_path.read_text(encoding="utf-8"))
    existing_keys = {
        (row.parent_id, row.normalized_name)
        for row in bind.execute(
            sa.select(catalog.c.parent_id, catalog.c.normalized_name).where(
                catalog.c.kind == "LOCALITY",
                catalog.c.source == "JAUREGUI_LORDA",
            )
        ).all()
    }
    to_insert = []
    for record in records:
        province_key = _fold(record["province_name"])
        province = provinces.get(province_key)
        if province is None:
            raise RuntimeError(f"Unknown province in legacy geography seed: {record['province_name']}")
        name = " ".join(record["locality_name"].split())
        normalized_name = _fold(name)
        key = (province.id, normalized_name)
        if key in existing_keys:
            continue
        record_id = f"jl:{uuid5(NAMESPACE_URL, f'agro:{province.id}:{normalized_name}').hex}"
        to_insert.append({
            "id": record_id,
            "kind": "LOCALITY",
            "name": name,
            "normalized_name": normalized_name,
            "parent_id": province.id,
            "georef_id": None,
            "aliases": [],
            "source": "JAUREGUI_LORDA",
            "active": False,
        })
        existing_keys.add(key)
    if to_insert:
        bind.execute(catalog.insert(), to_insert)


def downgrade() -> None:
    bind = op.get_bind()
    catalog = sa.table(
        "geographic_catalog",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("aliases", sa.JSON),
        sa.column("source", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    added_aliases = {"caba", "tierra del fuego"}
    for row in bind.execute(
        sa.select(catalog.c.id, catalog.c.aliases).where(catalog.c.kind == "PROVINCE")
    ).all():
        aliases = list(row.aliases or [])
        retained = [alias for alias in aliases if _fold(alias) not in added_aliases]
        if retained != aliases:
            bind.execute(
                catalog.update().where(catalog.c.id == row.id).values(
                    aliases=retained,
                    updated_at=sa.func.now(),
                )
            )
    bind.execute(catalog.delete().where(catalog.c.source == "JAUREGUI_LORDA"))
