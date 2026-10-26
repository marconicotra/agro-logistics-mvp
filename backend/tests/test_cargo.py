from app.domain.cargo import (
    CARGO_CATEGORIES,
    QUANTITY_UNITS,
    extract_explicit_quantity_unit,
    normalize_cargo_category,
    normalize_quantity_unit,
    quantity_unit_label,
)


def test_cargo_categories_are_normalized_from_shared_catalog() -> None:
    assert normalize_cargo_category(" grain ") == "GRAIN"
    assert normalize_cargo_category("livestock") == "LIVESTOCK"
    assert normalize_cargo_category("produce") is None
    assert CARGO_CATEGORIES == ("LIVESTOCK", "GRAIN")


def test_quantity_units_and_labels_are_normalized_from_shared_catalog() -> None:
    assert normalize_quantity_unit("Toneladas") == "TON"
    assert normalize_quantity_unit("kilogramos") == "KG"
    assert normalize_quantity_unit("cabezas") == "HEAD"
    assert normalize_quantity_unit("camiones") == "TRUCKLOAD"
    assert normalize_quantity_unit("bolsas") is None
    assert quantity_unit_label("toneladas") == "toneladas"
    assert QUANTITY_UNITS == ("HEAD", "TON", "KG", "TRUCKLOAD")


def test_quantity_unit_extraction_does_not_treat_a_vehicle_request_as_a_unit() -> None:
    assert extract_explicit_quantity_unit("necesito un camion para 30 soja") is None
    assert extract_explicit_quantity_unit("30 toneladas de soja") == "TON"
    assert extract_explicit_quantity_unit("toneladas") == "TON"
    assert extract_explicit_quantity_unit("2 camiones de soja") == "TRUCKLOAD"
