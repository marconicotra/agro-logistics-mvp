"""Declared carrier availability and conservative route matching."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.cargo import convert_mass_quantity, normalize_cargo_type, normalize_quantity_unit
from app.domain.equipment import normalize_equipment_or_declared
from app.domain.location_catalog import resolve_argentine_locality
from app.domain.models import TimestampMixin, new_id, require_value


AVAILABILITY_STATES = ("DRAFT", "ACTIVE", "COMMITTED", "CLOSED", "CANCELLED", "EXPIRED")


@dataclass
class RouteAvailability(TimestampMixin):
    carrier_id: str = ""
    origin: str = ""
    destination: str = ""
    window_start: datetime | None = None
    window_end: datetime | None = None
    capacity: Decimal | None = None
    capacity_unit: str | None = None
    cargo_types: list[str] = field(default_factory=list)
    equipment_types: list[str] = field(default_factory=list)
    stops: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("avail"))
    test_run_id: str | None = None
    status: str = "DRAFT"
    committed_shipment_id: str | None = None
    declared_by_user_id: str | None = None

    def __post_init__(self) -> None:
        require_value(self.carrier_id, "carrier_id")
        require_value(self.origin, "origin")
        require_value(self.destination, "destination")
        if self.origin.strip().casefold() == self.destination.strip().casefold():
            raise ValueError("origin and destination must differ")
        if self.status not in AVAILABILITY_STATES:
            raise ValueError("invalid availability status")
        self.origin = _canonical_location(self.origin)
        self.destination = _canonical_location(self.destination)
        self.stops = [_canonical_location(item) for item in self.stops]
        if self.capacity_unit is not None:
            canonical_unit = normalize_quantity_unit(self.capacity_unit)
            if canonical_unit is None:
                raise ValueError("capacity_unit must use a supported declared unit")
            self.capacity_unit = canonical_unit
        self.cargo_types = [normalize_cargo_type(item) or item.strip() for item in self.cargo_types]
        self.equipment_types = [normalize_equipment_or_declared(item) or "" for item in self.equipment_types]
        if (self.capacity is None) != (self.capacity_unit is None):
            raise ValueError("capacity and capacity_unit must be declared together")
        if self.capacity is not None and self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.window_start is not None:
            self.window_start = _aware(self.window_start)
        if self.window_end is not None:
            self.window_end = _aware(self.window_end)
        if self.window_start and self.window_end and self.window_start > self.window_end:
            raise ValueError("window_start must not be after window_end")
        if self.origin in self.stops or self.destination in self.stops:
            raise ValueError("stops must contain only intermediate locations")
        if any(not stop.strip() for stop in self.stops):
            raise ValueError("stops cannot be empty")
        if len({part.casefold() for part in [self.origin, *self.stops, self.destination]}) != len(self.stops) + 2:
            raise ValueError("route locations must be unique")

    @property
    def route(self) -> tuple[str, ...]:
        return (self.origin, *self.stops, self.destination)

    def expire_if_due(self, *, now: datetime | None = None) -> bool:
        now = _aware(now or datetime.now(UTC))
        if self.status == "ACTIVE" and self.window_end is not None and _aware(self.window_end) < now:
            self.status = "EXPIRED"
            return True
        return False


@dataclass(frozen=True)
class RouteMatch:
    availability_id: str
    segment_origin: str
    segment_destination: str
    reasons: tuple[str, ...]


def match_route_availability(
    availability: RouteAvailability,
    *,
    origin: str,
    destination: str,
    shipment_at: datetime | None,
    cargo_type: str | None,
    quantity: Decimal | None,
    quantity_unit: str | None,
    equipment_type: str | None = None,
    now: datetime | None = None,
) -> RouteMatch | None:
    """Return an explainable ordered-segment match; never infer missing capacity."""
    now = _aware(now or datetime.now(UTC))
    if availability.status != "ACTIVE":
        return None
    if availability.window_end and _aware(availability.window_end) < now:
        return None
    route = availability.route
    origin = _canonical_location(origin)
    destination = _canonical_location(destination)
    cargo_type = normalize_cargo_type(cargo_type) or cargo_type
    equipment_type = normalize_equipment_or_declared(equipment_type)
    try:
        start = next(i for i, item in enumerate(route[:-1]) if item.casefold() == origin.casefold())
        end = next(i for i, item in enumerate(route) if i > start and item.casefold() == destination.casefold())
    except StopIteration:
        return None
    reasons = ["origen y destino coinciden con un tramo declarado en el orden del recorrido"]
    if shipment_at:
        shipment_at = _aware(shipment_at)
        if availability.window_start and shipment_at < _aware(availability.window_start):
            return None
        if availability.window_end and shipment_at > _aware(availability.window_end):
            return None
        reasons.append("la fecha solicitada está dentro de la ventana declarada")
    elif availability.window_start or availability.window_end:
        reasons.append("falta confirmar la fecha de la carga")
    if cargo_type and availability.cargo_types:
        if cargo_type.casefold() not in {item.casefold() for item in availability.cargo_types}:
            return None
        reasons.append("tipo de carga admitido por el transportista")
    elif not cargo_type or not availability.cargo_types:
        reasons.append("tipo de carga pendiente de confirmar")
    if equipment_type and availability.equipment_types:
        if equipment_type.casefold() not in {item.casefold() for item in availability.equipment_types}:
            return None
        reasons.append("equipo compatible según lo declarado")
    elif equipment_type or not availability.equipment_types:
        reasons.append("equipo pendiente de confirmar")
    if quantity is not None:
        if not quantity_unit or not availability.capacity or not availability.capacity_unit:
            reasons.append("capacidad disponible pendiente de confirmar")
        else:
            try:
                source_unit = normalize_quantity_unit(quantity_unit)
                target_unit = normalize_quantity_unit(availability.capacity_unit)
                if source_unit == target_unit:
                    comparable = Decimal(str(quantity))
                else:
                    comparable = convert_mass_quantity(quantity, source_unit, target_unit)
            except (ValueError, ArithmeticError):
                return None
            if comparable is None or comparable > availability.capacity:
                return None
            reasons.append("capacidad declarada suficiente")
    else:
        reasons.append("cantidad pendiente de confirmar")
    return RouteMatch(availability.id, route[start], route[end], tuple(reasons))


def _canonical_location(value: str) -> str:
    declared = value.strip()
    resolution = resolve_argentine_locality(declared)
    if resolution.status == "RESOLVED" and resolution.locality:
        return resolution.locality.name
    return declared


def _aware(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
