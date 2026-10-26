"""Canonical cargo categories, quantity units, and unit labels for the MVP."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

CARGO_CATEGORIES = ("LIVESTOCK", "GRAIN")
QUANTITY_UNITS = ("HEAD", "TON", "KG", "TRUCKLOAD")

LIVESTOCK_TYPES = {
    "novillo": "novillos",
    "novillos": "novillos",
    "vaca": "vacas",
    "vacas": "vacas",
    "ternero": "terneros",
    "terneros": "terneros",
    "ternera": "terneras",
    "terneras": "terneras",
    "vaquillona": "vaquillonas",
    "vaquillonas": "vaquillonas",
    "toro": "toros",
    "toros": "toros",
    "hacienda": "hacienda",
}
GRAIN_TYPES = {
    "soja": "soja",
    "maiz": "maíz",
    "trigo": "trigo",
    "girasol": "girasol",
    "sorgo": "sorgo",
    "cebada": "cebada",
}

_QUANTITY_UNIT_ALIASES = {
    "head": "HEAD",
    "heads": "HEAD",
    "cabeza": "HEAD",
    "cabezas": "HEAD",
    "ton": "TON",
    "tons": "TON",
    "t": "TON",
    "tn": "TON",
    "tns": "TON",
    "tonelada": "TON",
    "toneladas": "TON",
    "kg": "KG",
    "kgs": "KG",
    "kilo": "KG",
    "kilos": "KG",
    "kilogramo": "KG",
    "kilogramos": "KG",
    "truckload": "TRUCKLOAD",
    "truckloads": "TRUCKLOAD",
    "camion": "TRUCKLOAD",
    "camiones": "TRUCKLOAD",
}

_QUANTITY_UNIT_LABELS = {
    "HEAD": "cabezas",
    "TON": "toneladas",
    "KG": "kg",
    "TRUCKLOAD": "camiones",
}


@dataclass(frozen=True)
class CargoCategoryDefinition:
    code: str
    name: str
    aliases: tuple[str, ...] = ()
    active: bool = True


@dataclass(frozen=True)
class CargoTypeDefinition:
    code: str
    category_code: str
    name: str
    aliases: tuple[str, ...] = ()
    active: bool = True


def default_cargo_catalog() -> tuple[list[CargoCategoryDefinition], list[CargoTypeDefinition]]:
    categories = [
        CargoCategoryDefinition("LIVESTOCK", "Hacienda", ("ganado",)),
        CargoCategoryDefinition("GRAIN", "Granos", ("cereales",)),
    ]
    types = [
        CargoTypeDefinition(canonical, "LIVESTOCK", canonical, tuple(alias for alias, value in LIVESTOCK_TYPES.items() if value == canonical and alias != canonical))
        for canonical in dict.fromkeys(LIVESTOCK_TYPES.values())
    ] + [
        CargoTypeDefinition(canonical, "GRAIN", canonical, tuple(alias for alias, value in GRAIN_TYPES.items() if value == canonical and alias != canonical))
        for canonical in dict.fromkeys(GRAIN_TYPES.values())
    ]
    return categories, types


def normalize_cargo_category(
    value: object,
    categories: Sequence[CargoCategoryDefinition] | None = None,
) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    catalog = categories if categories is not None else default_cargo_catalog()[0]
    for category in catalog:
        if category.active and normalized.casefold() in {category.code.casefold(), category.name.casefold(), *(alias.casefold() for alias in category.aliases)}:
            return category.code
    return None


def normalize_quantity_unit(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _fold(value)
    return _QUANTITY_UNIT_ALIASES.get(normalized)


def normalize_cargo_type(
    value: object,
    category: object | None = None,
    types: Sequence[CargoTypeDefinition] | None = None,
    categories: Sequence[CargoCategoryDefinition] | None = None,
) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _fold(value)
    catalog = types if types is not None else default_cargo_catalog()[1]
    canonical_category = normalize_cargo_category(category, categories) if category is not None else None
    for item in catalog:
        accepted = {_fold(item.code), _fold(item.name), *(_fold(alias) for alias in item.aliases)}
        if item.active and normalized in accepted and (canonical_category is None or item.category_code == canonical_category):
            return item.name
    if types is not None:
        return None
    if canonical_category == "LIVESTOCK":
        return LIVESTOCK_TYPES.get(normalized)
    if canonical_category == "GRAIN":
        return GRAIN_TYPES.get(normalized)
    matches = {**LIVESTOCK_TYPES, **GRAIN_TYPES}
    return matches.get(normalized)


def find_cargo_type_in_text(
    text: str,
    types: Sequence[CargoTypeDefinition] | None = None,
) -> CargoTypeDefinition | None:
    catalog = types if types is not None else default_cargo_catalog()[1]
    folded_text = _fold(text)
    candidates: list[tuple[int, CargoTypeDefinition]] = []
    for item in catalog:
        if not item.active:
            continue
        for alias in (item.name, item.code, *item.aliases):
            normalized = _fold(alias)
            if normalized and re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", folded_text):
                candidates.append((len(normalized), item))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def convert_mass_quantity(value: Decimal | int | str, from_unit: object, to_unit: object) -> Decimal:
    """Convert exact metric mass units only; refuse head/truck equivalences."""
    source = normalize_quantity_unit(from_unit)
    target = normalize_quantity_unit(to_unit)
    amount = Decimal(str(value))
    if amount < 0 or source not in {"KG", "TON"} or target not in {"KG", "TON"}:
        raise ValueError("Only nonnegative KG/TON quantities can be converted")
    if source == target:
        return amount
    return amount / Decimal(1000) if source == "KG" else amount * Decimal(1000)


def quantity_unit_label(value: object) -> str | None:
    normalized = normalize_quantity_unit(value)
    return _QUANTITY_UNIT_LABELS.get(normalized or "")


def extract_explicit_quantity_unit(text: str) -> str | None:
    normalized = _fold(text)
    if normalized in _QUANTITY_UNIT_ALIASES:
        return _QUANTITY_UNIT_ALIASES[normalized]

    if re.search(r"\b\d+(?:[,.]\d+)?\s*t\b", normalized):
        return "TON"
    for alias, canonical in _QUANTITY_UNIT_ALIASES.items():
        if alias in {"t", "camion", "camiones", "truckload", "truckloads"}:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical
    if re.search(r"\b\d+(?:[,.]\d+)?\s+camiones?\b", normalized):
        return "TRUCKLOAD"
    return None


def _fold(value: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"\s+", " ", without_accents).strip()
