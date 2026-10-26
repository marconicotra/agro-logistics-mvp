import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.cargo import (
    CargoCategoryDefinition,
    CargoTypeDefinition,
    extract_explicit_quantity_unit,
    find_cargo_type_in_text,
    normalize_cargo_category,
    normalize_cargo_type,
    normalize_quantity_unit,
)


@dataclass(frozen=True)
class ParsedChatShipment:
    livestock_type: str | None
    quantity_estimate: Decimal | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    origin: str | None = None
    destination: str | None = None
    date_window_start: datetime | None = None
    date_window_end: datetime | None = None
    weight_per_head_kg: Decimal | None = None


_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}
_ARGENTINA_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")


def parse_chat_shipment_text(
    text: str,
    *,
    reference_datetime: datetime | None = None,
    cargo_categories: tuple[CargoCategoryDefinition, ...] | list[CargoCategoryDefinition] | None = None,
    cargo_types: tuple[CargoTypeDefinition, ...] | list[CargoTypeDefinition] | None = None,
) -> ParsedChatShipment:
    normalized = normalize_for_simple_parse(text)
    cargo_match = find_cargo_type_in_text(normalized, cargo_types)
    livestock_type = cargo_match.name if cargo_match and cargo_match.category_code == "LIVESTOCK" else None
    grain_type = cargo_match.name if cargo_match and cargo_match.category_code == "GRAIN" else None
    origin, destination = _extract_route(text)
    date_window_start, date_window_end = _extract_date_window(
        normalized,
        reference_datetime=reference_datetime,
    )
    cargo_category = cargo_match.category_code if cargo_match else None
    cargo_type = cargo_match.name if cargo_match else None
    quantity_unit = extract_explicit_quantity_unit(normalized)
    quantity_estimate = _extract_quantity(normalized, livestock_type=livestock_type)
    weight_per_head_kg = _extract_weight_per_head(normalized, livestock_type)
    if livestock_type:
        cargo_category = normalize_cargo_category("LIVESTOCK", cargo_categories)
        cargo_type = normalize_cargo_type(livestock_type, "LIVESTOCK", cargo_types, cargo_categories)
        quantity_unit = normalize_quantity_unit(quantity_unit)
        if _extract_livestock_count(normalized, livestock_type) is not None:
            quantity_unit = "HEAD"
    elif grain_type:
        cargo_category = normalize_cargo_category("GRAIN", cargo_categories)
        cargo_type = normalize_cargo_type(grain_type, "GRAIN", cargo_types, cargo_categories)
        quantity_unit = extract_explicit_quantity_unit(normalized)
    return ParsedChatShipment(
        livestock_type=livestock_type,
        quantity_estimate=quantity_estimate,
        cargo_category=cargo_category,
        cargo_type=cargo_type,
        quantity_unit=quantity_unit,
        origin=origin,
        destination=destination,
        date_window_start=date_window_start,
        date_window_end=date_window_end,
        weight_per_head_kg=weight_per_head_kg,
    )


def normalize_for_simple_parse(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )


def _extract_livestock_type(normalized_text: str) -> str | None:
    tokens = re.findall(r"[a-z]+", normalized_text)
    for token in tokens:
        canonical = normalize_cargo_type(token, "LIVESTOCK")
        if canonical:
            return canonical
    return None


def _extract_grain_type(normalized_text: str) -> str | None:
    tokens = re.findall(r"[a-z]+", normalized_text)
    for token in tokens:
        canonical = normalize_cargo_type(token, "GRAIN")
        if canonical:
            return canonical
    return None


def _extract_livestock_count(normalized_text: str, livestock_type: str | None) -> Decimal | None:
    if not livestock_type:
        return None
    aliases = {
        "novillos": "novillo|novillos",
        "vacas": "vaca|vacas",
        "terneros": "ternero|terneros",
        "terneras": "ternera|terneras",
        "vaquillonas": "vaquillona|vaquillonas",
        "toros": "toro|toros",
        "hacienda": "hacienda",
    }.get(livestock_type)
    if not aliases:
        return None
    match = re.search(
        rf"\b(\d+(?:[,.]\d+)?)\s+(?:(?:cabezas?)\s+(?:de\s+)?)?(?:{aliases})\b",
        normalized_text,
    )
    return Decimal(match.group(1).replace(",", ".")) if match else None


def _extract_quantity(normalized_text: str, *, livestock_type: str | None = None) -> Decimal | None:
    livestock_count = _extract_livestock_count(normalized_text, livestock_type)
    if livestock_count is not None:
        return livestock_count
    explicit_quantity = re.search(
        r"\b(\d+(?:[,.]\d+)?)\s*(?:kg|kgs|kilo(?:s|gramo(?:s)?)?|"
        r"toneladas?|tns?|camiones?)\b",
        normalized_text,
    )
    match = explicit_quantity or re.search(r"\b(\d+(?:[,.]\d+)?)\b", normalized_text)
    if match is None:
        return None
    return Decimal(match.group(1).replace(",", "."))


def _extract_weight_per_head(
    normalized_text: str,
    livestock_type: str | None,
) -> Decimal | None:
    if not livestock_type:
        return None
    aliases = {
        "novillos": "novillo|novillos",
        "vacas": "vaca|vacas",
        "terneros": "ternero|terneros",
        "terneras": "ternera|terneras",
        "vaquillonas": "vaquillona|vaquillonas",
        "toros": "toro|toros",
        "hacienda": "hacienda",
    }.get(livestock_type)
    if not aliases:
        return None
    match = re.search(
        rf"\b(?:{aliases})\b.{{0,45}}?"
        r"(?:\bde\s+|\bcon\s+(?:un\s+)?peso(?:\s+promedio)?\s+(?:de\s+)?|"
        r"\bpeso(?:\s+aproximado|\s+promedio)?\s*(?:de\s+)?|"
        r"\bpesaje(?:\s+promedio)?\s*(?:de\s+)?|\bpromedio\s+de\s+)"
        r"(\d+(?:[,.]\d+)?)\s*(?:kg|kgs|kilo(?:s|gramo(?:s)?)?)\b",
        normalized_text,
    )
    if match is None:
        return None
    return Decimal(match.group(1).replace(",", "."))


def _extract_route(text: str) -> tuple[str | None, str | None]:
    original = " ".join(text.split())
    for pattern in (
        re.compile(r"\bdesde\s+(?P<origin>.+?)\s*,?\s*hasta\s+(?P<destination>.+)", re.IGNORECASE),
        re.compile(r"\bdesde\s+(?P<origin>.+?)\s+a\s+(?P<destination>.+)", re.IGNORECASE),
        re.compile(r"\bde\s+(?P<origin>.+?)\s+a\s+(?P<destination>.+)", re.IGNORECASE),
    ):
        match = pattern.search(original)
        if match is None:
            continue
        origin = _clean_location_fragment(match.group("origin"))
        destination = _clean_location_fragment(match.group("destination"))
        if origin and destination:
            return origin, destination
    return None, None


def _clean_location_fragment(value: str) -> str | None:
    stripped = value.strip(" ,.;:")
    stripped = re.sub(
        r"\s*,?\s+para\s+(?:el\s+)?(?:(?:dia|día|fecha)\s+)?"
        r"(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
        r"\d{4}-\d{1,2}-\d{1,2}|hoy|manana|mañana|pasado manana|pasado mañana|"
        r"lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)\b.*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s*,?\s*(?:(?:el\s+)?(?:\d{1,2}\s+de\s+[a-záéíóúü]+(?:\s+de\s+\d{4})?|"
        r"lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)|"
        r"(?:el\s+)?\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
        r"\d{4}-\d{1,2}-\d{1,2}|hoy|manana|mañana|pasado manana|pasado mañana)\b.*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s*,?\s*(hablar con|llamar a|llama a|contacto)\b.*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = stripped.strip(" ,.;:")
    return stripped or None


def _extract_date_window(
    normalized_text: str,
    *,
    reference_datetime: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    reference = reference_datetime or datetime.now(_ARGENTINA_TIMEZONE)
    base = (
        reference.astimezone(_ARGENTINA_TIMEZONE)
        if reference.tzinfo is not None
        else reference.replace(tzinfo=_ARGENTINA_TIMEZONE)
    )

    if "pasado manana" in normalized_text:
        target = base + timedelta(days=2)
        return _at_morning(target), None
    if "manana" in normalized_text:
        target = base + timedelta(days=1)
        return _at_morning(target), None
    if re.search(r"\bhoy\b", normalized_text):
        return _at_morning(base), None

    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", normalized_text)
    if iso_match is not None:
        year, month, day = (int(part) for part in iso_match.groups())
        try:
            return datetime(year, month, day, 8, 0, tzinfo=_ARGENTINA_TIMEZONE), None
        except ValueError:
            return None, None

    numeric_date_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", normalized_text)
    if numeric_date_match is not None:
        day, month = (int(part) for part in numeric_date_match.groups()[:2])
        year_text = numeric_date_match.group(3)
        year = int(year_text) if year_text else base.year
        if year_text and len(year_text) == 2:
            year += 2000
        try:
            candidate = datetime(year, month, day, 8, 0, tzinfo=_ARGENTINA_TIMEZONE)
        except ValueError:
            return None, None
        if year_text is None and candidate.date() < base.date():
            try:
                candidate = candidate.replace(year=year + 1)
            except ValueError:
                return None, None
        return candidate, None

    match = re.search(
        r"\bel\s+(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de\s+(\d{4}))?\b",
        normalized_text,
    )
    if match is not None:
        day = int(match.group(1))
        month = _MONTHS[match.group(2)]
        year = int(match.group(3)) if match.group(3) else base.year
        candidate = datetime(year, month, day, 8, 0, tzinfo=_ARGENTINA_TIMEZONE)
        if match.group(3) is None and candidate.date() < base.date():
            candidate = datetime(year + 1, month, day, 8, 0, tzinfo=_ARGENTINA_TIMEZONE)
        return candidate, None

    weekday_match = re.search(
        r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
        normalized_text,
    )
    if weekday_match is None:
        return None, None

    days_ahead = (_WEEKDAYS[weekday_match.group(1)] - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return _at_morning(base + timedelta(days=days_ahead)), None


def _at_morning(value: datetime) -> datetime:
    return value.replace(hour=8, minute=0, second=0, microsecond=0)
