from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from zoneinfo import ZoneInfo

from app.application.ai import AIExtractionError, LoadDataExtraction
from app.domain.cargo import (
    CargoCategoryDefinition,
    CargoTypeDefinition,
    QUANTITY_UNITS,
    default_cargo_catalog,
    normalize_cargo_category,
    normalize_cargo_type,
    normalize_quantity_unit,
)


class OpenAIExtractionClient:
    """Extract candidate shipment fields with the backend's configured OpenAI model."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = 20) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._cargo_categories, self._cargo_types = default_cargo_catalog()

    def configure_cargo_catalog(
        self,
        categories: list[CargoCategoryDefinition],
        types: list[CargoTypeDefinition],
    ) -> None:
        self._cargo_categories = categories
        self._cargo_types = types

    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIExtractionError("OpenAI package is not installed") from exc

        today = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date().isoformat()
        category_choices = ", ".join(f"{item.code} ({item.name})" for item in self._cargo_categories if item.active)
        cargo_type_choices = ", ".join(
            f"{item.name} [{item.category_code}]" for item in self._cargo_types if item.active
        )
        unit_choices = ", ".join(QUANTITY_UNITS)
        try:
            client = OpenAI(api_key=self._api_key, timeout=self._timeout_seconds)
            response = client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extraé datos de una solicitud de transporte de hacienda o granos en Argentina. "
                            f"Devolvé únicamente un objeto JSON con cargo_category ({category_choices}), "
                            f"cargo_type elegido de este catálogo activo ({cargo_type_choices}), "
                            f"quantity_unit ({unit_choices}), livestock_type. "
                            "No infieras quantity_unit: informala solo si aparece explícitamente en el mensaje; "
                            "si falta, devolvé null. "
                            "Incluí origin, destination, date_window_start, date_window_end, quantity_estimate, "
                            "weight_per_head_kg cuando se informe peso por animal (por ejemplo: 25 terneros de 300 kilos "
                            "significa 25 HEAD y 300 kg por cabeza; no mezcles el pesaje con la cantidad). "
                            "contact, confidence, has_ambiguous_location y field_confidence. "
                            "Usá null para datos ausentes. "
                            "Las fechas deben ser ISO 8601 o null. No inventes valores. "
                            "Conservá el tipo de hacienda/grano expresado. confidence debe ser high, medium, "
                            "low o unknown. Fecha de referencia: " + today + "."
                        ),
                    },
                    {"role": "user", "content": message_text},
                ],
            )
            content = response.choices[0].message.content
            data = json.loads(content or "{}")
            return LoadDataExtraction(
                raw_text=message_text,
                cargo_category=normalize_cargo_category(data.get("cargo_category"), self._cargo_categories),
                cargo_type=(
                    normalize_cargo_type(
                        data.get("cargo_type"), data.get("cargo_category"),
                        self._cargo_types, self._cargo_categories,
                    )
                    or _optional_string(data.get("cargo_type"))
                ),
                quantity_unit=normalize_quantity_unit(data.get("quantity_unit")),
                origin=_optional_string(data.get("origin")),
                destination=_optional_string(data.get("destination")),
                date_window_start=_optional_datetime(data.get("date_window_start")),
                date_window_end=_optional_datetime(data.get("date_window_end")),
                livestock_type=(
                    normalize_cargo_type(
                        data.get("livestock_type"), "LIVESTOCK", self._cargo_types, self._cargo_categories
                    )
                    or _optional_string(data.get("livestock_type"))
                ),
                quantity_estimate=_optional_decimal(data.get("quantity_estimate")),
                weight_per_head_kg=_optional_decimal(data.get("weight_per_head_kg")),
                contact=_optional_string(data.get("contact")),
                confidence=_confidence(data.get("confidence")),
                has_ambiguous_location=bool(data.get("has_ambiguous_location", False)),
                field_confidence=_field_confidence(data.get("field_confidence")),
            )
        except AIExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Never include provider response bodies, prompts, or credentials in errors/logs.
            raise AIExtractionError(f"OpenAI extraction failed: {exc.__class__.__name__}") from exc


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _confidence(value: object) -> str:
    normalized = str(value or "medium").strip().lower()
    return normalized if normalized in {"high", "medium", "low", "unknown"} else "medium"


def _field_confidence(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    valid = {"high", "medium", "low", "unknown", "estimated"}
    return {
        str(key): str(confidence).lower()
        for key, confidence in value.items()
        if isinstance(key, str) and str(confidence).lower() in valid
    }
