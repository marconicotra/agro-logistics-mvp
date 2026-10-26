from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol


class AIExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadDataExtraction:
    raw_text: str
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    origin: str | None = None
    destination: str | None = None
    date_window_start: datetime | None = None
    date_window_end: datetime | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    weight_per_head_kg: Decimal | None = None
    contact: str | None = None
    confidence: str = "medium"
    has_ambiguous_location: bool = False
    field_confidence: dict[str, str] = field(default_factory=dict)


class AIExtractionClient(Protocol):
    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        pass
