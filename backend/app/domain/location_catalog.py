"""Offline, version-pinned resolver for Argentine localities from Georef."""

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[3] / "data/catalogs/georef/localidades.csv"
_LOCALITY_ALIASES = {
    "cordoba capital": "cordoba",
    "ciudad de cordoba": "cordoba",
    "corrientes capital": "corrientes",
    "ciudad de corrientes": "corrientes",
}


@dataclass(frozen=True)
class GeorefLocality:
    georef_id: str
    name: str
    province: str
    department: str | None
    province_id: str


@dataclass(frozen=True)
class LocalityResolution:
    status: str
    locality: GeorefLocality | None
    candidates: tuple[GeorefLocality, ...]
    catalog_version: str


@dataclass(frozen=True)
class GeographicCatalogEntry:
    id: str
    kind: str
    name: str
    parent_id: str | None
    georef_id: str | None
    aliases: tuple[str, ...] = ()


def fold_location(value: str) -> str:
    without_marks = "".join(
        char
        for char in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()


@lru_cache(maxsize=1)
def _catalog() -> tuple[str, dict[str, tuple[GeorefLocality, ...]]]:
    raw = CATALOG_PATH.read_bytes()
    version = f"georef-localidades-sha256:{hashlib.sha256(raw).hexdigest()}"
    by_name: dict[str, list[GeorefLocality]] = {}
    with CATALOG_PATH.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            # The resource also includes nested entities such as neighborhoods.
            # Keep top-level localities and named components, avoiding duplicate
            # matches against the same city represented by its constituent areas.
            if row.get("categoria") == "Entidad":
                continue
            locality = GeorefLocality(
                georef_id=row["id"],
                name=row["nombre"],
                province=row["provincia_nombre"],
                department=row.get("departamento_nombre") or None,
                province_id=row["provincia_id"],
            )
            by_name.setdefault(fold_location(locality.name), []).append(locality)
    return version, {key: tuple(values) for key, values in by_name.items()}


def resolve_argentine_locality(value: str) -> LocalityResolution:
    """Resolve exact locality names; never choose among same-name localities."""
    version, catalog = _catalog()
    folded = fold_location(value)
    candidates = catalog.get(_LOCALITY_ALIASES.get(folded, folded), ())
    if not candidates:
        return LocalityResolution("NOT_FOUND", None, (), version)
    if len(candidates) > 1:
        return LocalityResolution("AMBIGUOUS", None, candidates, version)
    return LocalityResolution("RESOLVED", candidates[0], candidates, version)


def resolve_catalog_locality(
    value: str,
    entries: tuple[GeographicCatalogEntry, ...] | list[GeographicCatalogEntry],
) -> LocalityResolution:
    """Resolve against the active database catalog snapshot supplied by the caller."""
    by_id = {entry.id: entry for entry in entries}
    folded = fold_location(value)
    matches = [
        entry for entry in entries
        if entry.kind == "LOCALITY"
        and folded in {fold_location(entry.name), *(fold_location(alias) for alias in entry.aliases)}
    ]
    candidates: list[GeorefLocality] = []
    for entry in matches:
        department = by_id.get(entry.parent_id or "")
        province = by_id.get(department.parent_id or "") if department else None
        if department and department.kind == "PROVINCE":
            province, department = department, None
        candidates.append(
            GeorefLocality(
                georef_id=entry.georef_id or entry.id,
                name=entry.name,
                province=province.name if province else "",
                department=department.name if department else None,
                province_id=province.georef_id or province.id if province else "",
            )
        )
    if not candidates:
        return LocalityResolution("NOT_FOUND", None, (), "database-catalog")
    if len(candidates) > 1:
        return LocalityResolution("AMBIGUOUS", None, tuple(candidates), "database-catalog")
    return LocalityResolution("RESOLVED", candidates[0], tuple(candidates), "database-catalog")
