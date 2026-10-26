from decimal import Decimal

import pytest

from app.domain.cargo import convert_mass_quantity, normalize_cargo_type


def test_product_aliases_normalize_by_canonical_category() -> None:
    assert normalize_cargo_type("MAÍZ", "GRAIN") == "maíz"
    assert normalize_cargo_type("novillo", "LIVESTOCK") == "novillos"
    assert normalize_cargo_type("soja", "LIVESTOCK") is None
    assert normalize_cargo_type("alfalfa", "GRAIN") is None


def test_only_exact_kg_ton_mass_conversion_is_allowed() -> None:
    assert convert_mass_quantity("1500", "kg", "ton") == Decimal("1.5")
    assert convert_mass_quantity("2", "ton", "kg") == Decimal("2000")
    assert convert_mass_quantity("2", "ton", "ton") == Decimal("2")
    with pytest.raises(ValueError):
        convert_mass_quantity("2", "HEAD", "TON")
