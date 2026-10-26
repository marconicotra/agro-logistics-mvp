from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.route_availability import RouteAvailability, match_route_availability


NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def availability(**overrides):
    values = {
        "carrier_id": "carrier-1",
        "origin": "Corrientes",
        "destination": "Buenos Aires",
        "stops": ["Paraná", "Rosario"],
        "window_start": NOW,
        "window_end": NOW + timedelta(days=2),
        "capacity": Decimal("30"),
        "capacity_unit": "TON",
        "cargo_types": ["maíz"],
        "equipment_types": ["granelero"],
        "status": "ACTIVE",
    }
    values.update(overrides)
    return RouteAvailability(**values)


def test_matches_declared_intermediate_segment_in_route_order():
    match = match_route_availability(
        availability(),
        origin="Paraná",
        destination="Rosario",
        shipment_at=NOW + timedelta(days=1),
        cargo_type="maíz",
        quantity=Decimal("25000"),
        quantity_unit="KG",
        equipment_type="granelero",
        now=NOW,
    )

    assert match is not None
    assert (match.segment_origin, match.segment_destination) == ("Paraná", "Rosario")
    assert "capacidad declarada suficiente" in match.reasons


def test_rejects_segment_whose_stops_are_in_reverse_order():
    assert match_route_availability(
        availability(), origin="Rosario", destination="Paraná", shipment_at=NOW,
        cargo_type="maíz", quantity=Decimal("1"), quantity_unit="TON", now=NOW,
    ) is None


def test_rejects_insufficient_capacity_or_incompatible_cargo_and_equipment():
    assert match_route_availability(
        availability(), origin="Corrientes", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="soja", quantity=Decimal("1"), quantity_unit="TON", now=NOW,
    ) is None
    assert match_route_availability(
        availability(), origin="Corrientes", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="maíz", quantity=Decimal("31"), quantity_unit="TON", equipment_type="granelero", now=NOW,
    ) is None
    assert match_route_availability(
        availability(), origin="Corrientes", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="maíz", quantity=Decimal("1"), quantity_unit="TON", equipment_type="jaula", now=NOW,
    ) is None


def test_does_not_guess_missing_information_and_explains_what_needs_confirmation():
    match = match_route_availability(
        availability(cargo_types=[], equipment_types=[], capacity=None, capacity_unit=None),
        origin="Corrientes", destination="Buenos Aires", shipment_at=None,
        cargo_type=None, quantity=None, quantity_unit=None, now=NOW,
    )

    assert match is not None
    assert any("pendiente de confirmar" in reason for reason in match.reasons)


def test_expired_or_non_active_availability_is_not_matched():
    assert match_route_availability(
        availability(window_start=NOW - timedelta(days=2), window_end=NOW - timedelta(seconds=1)), origin="Corrientes", destination="Buenos Aires",
        shipment_at=NOW, cargo_type="maíz", quantity=Decimal("1"), quantity_unit="TON", now=NOW,
    ) is None
    assert match_route_availability(
        availability(window_start=NOW - timedelta(days=2), window_end=NOW - timedelta(seconds=1)),
        origin="Corrientes", destination="Buenos Aires", shipment_at=None,
        cargo_type="maíz", quantity=None, quantity_unit=None, now=NOW,
    ) is None
    assert match_route_availability(
        availability(status="CLOSED"), origin="Corrientes", destination="Buenos Aires",
        shipment_at=NOW, cargo_type="maíz", quantity=Decimal("1"), quantity_unit="TON", now=NOW,
    ) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin": "", "destination": "Buenos Aires"},
        {"capacity": Decimal("10"), "capacity_unit": None},
        {"capacity": Decimal("0"), "capacity_unit": "TON"},
        {"window_start": NOW + timedelta(days=2), "window_end": NOW},
        {"stops": ["Buenos Aires"]},
        {"status": "PUBLISHED"},
    ],
)
def test_rejects_invalid_availability_declarations(overrides):
    with pytest.raises(ValueError):
        availability(**overrides)


def test_does_not_convert_mass_to_heads_or_truckloads():
    assert match_route_availability(
        availability(capacity=Decimal("30000"), capacity_unit="KG"),
        origin="Corrientes", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="maíz", quantity=Decimal("1"), quantity_unit="TRUCKLOAD", now=NOW,
    ) is None


def test_matches_head_capacity_only_when_both_quantities_use_heads():
    declared = availability(capacity=Decimal("40"), capacity_unit="HEAD", cargo_types=["novillos"])
    match = match_route_availability(
        declared, origin="Corrientes", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="novillos", quantity=Decimal("35"), quantity_unit="cabezas", now=NOW,
    )
    assert match is not None
    assert match_route_availability(
        declared, origin="Corrientes", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="novillos", quantity=Decimal("35"), quantity_unit="TON", now=NOW,
    ) is None


def test_normalizes_locality_and_supported_unit_aliases_before_matching():
    item = availability(origin="Córdoba capital", destination="Buenos Aires", capacity_unit="tn")
    assert item.origin == "Córdoba"
    assert item.capacity_unit == "TON"
    match = match_route_availability(
        item, origin="Cordoba", destination="Buenos Aires", shipment_at=NOW,
        cargo_type="maiz", quantity=Decimal("2"), quantity_unit="toneladas", now=NOW,
    )
    assert match is not None


def test_rejects_unsupported_capacity_unit_instead_of_guessing():
    with pytest.raises(ValueError, match="capacity_unit"):
        availability(capacity=Decimal("3"), capacity_unit="pallets")
