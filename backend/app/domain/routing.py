"""Route operations are independent from channel and Trip delivery states."""
from dataclasses import dataclass, field
from datetime import UTC, datetime
import math
from typing import Any
from uuid import uuid4

KINDS = {"preference", "dispatch", "tracking", "checkpoint", "report", "job", "usage", "closed_run"}


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Latitud o longitud inválida")
    return float(latitude), float(longitude)


@dataclass
class RoutingEntry:
    kind: str
    entity_id: str
    data: dict[str, Any] = field(default_factory=dict)
    test_run_id: str | None = None
    status: str = "ACTIVE"
    due_at: datetime | None = None
    id: str = field(default_factory=lambda: f"rt_{uuid4().hex}")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError("Tipo de operación de recorrido inválido")
        if self.due_at is not None:
            self.due_at = aware(self.due_at)
