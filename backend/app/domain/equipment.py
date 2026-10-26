"""Shared MVP equipment vocabulary and aliases used in carrier capture."""

import re
import unicodedata


EQUIPMENT_ALIASES = {
    "camion": "camion",
    "camion jaula": "camion jaula",
    "jaula": "jaula",
    "jaula ganadera": "jaula",
    "semirremolque": "semirremolque",
    "semi": "semirremolque",
    "acoplado": "acoplado",
    "bateas": "batea",
    "batea": "batea",
    "granelero": "granelero",
    "cerealero": "granelero",
    "sider": "sider",
    "baranda volcable": "baranda volcable",
    "playo": "playo",
    "plataforma": "playo",
    "carreton": "carreton",
    "carreton maquinaria": "carreton",
    "cisterna": "cisterna",
    "tanque": "cisterna",
    "termico": "termico",
    "refrigerado": "termico",
    "portacontenedor": "portacontenedor",
}


def normalize_equipment(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    folded = "".join(
        character
        for character in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(character) != "Mn"
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", folded).strip()
    return EQUIPMENT_ALIASES.get(normalized)


def normalize_equipment_or_declared(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_equipment(value) or " ".join(value.split())
