from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cargo import CargoCategoryDefinition, CargoTypeDefinition, default_cargo_catalog
from app.domain.location_catalog import GeographicCatalogEntry
from app.infrastructure.db.models import CargoCategoryRecord, CargoTypeRecord, GeographicCatalogRecord


def load_active_cargo_catalog(
    session: Session,
) -> tuple[list[CargoCategoryDefinition], list[CargoTypeDefinition]]:
    has_seed = session.scalar(select(CargoCategoryRecord.code).limit(1)) is not None
    if not has_seed:
        # Preserve the versioned starter catalog for fresh SQL schemas until the
        # managed-catalog migration has seeded rows. An intentionally disabled
        # catalog still has rows and therefore does not fall back.
        return default_cargo_catalog()
    categories = [
        CargoCategoryDefinition(row.code, row.name, tuple(row.aliases or ()), row.active)
        for row in session.scalars(
            select(CargoCategoryRecord).where(CargoCategoryRecord.active.is_(True)).order_by(CargoCategoryRecord.sort_order)
        ).all()
    ]
    active_codes = {item.code for item in categories}
    types = [
        CargoTypeDefinition(row.code, row.category_code, row.name, tuple(row.aliases or ()), row.active)
        for row in session.scalars(
            select(CargoTypeRecord)
            .where(CargoTypeRecord.active.is_(True))
            .order_by(CargoTypeRecord.sort_order, CargoTypeRecord.name)
        ).all()
        if row.category_code in active_codes
    ]
    return categories, types


def load_active_geography_catalog(session: Session) -> list[GeographicCatalogEntry] | None:
    has_seed = session.scalar(select(GeographicCatalogRecord.id).limit(1)) is not None
    if not has_seed:
        # None keeps the existing offline Georef snapshot as a compatibility
        # fallback until the managed-catalog migration is applied and seeded.
        return None
    rows = session.scalars(
        select(GeographicCatalogRecord)
        .where(GeographicCatalogRecord.active.is_(True), GeographicCatalogRecord.deleted_at.is_(None))
        .order_by(GeographicCatalogRecord.kind, GeographicCatalogRecord.normalized_name)
    ).all()
    return [
        GeographicCatalogEntry(
            id=row.id,
            kind=row.kind,
            name=row.name,
            parent_id=row.parent_id,
            georef_id=row.georef_id,
            aliases=tuple(row.aliases or ()),
        )
        for row in rows
    ]
