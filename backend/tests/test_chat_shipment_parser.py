from datetime import datetime
from zoneinfo import ZoneInfo

from app.application.chat_shipment_parser import parse_chat_shipment_text


def test_grain_quantity_unit_is_not_inferred_when_absent() -> None:
    parsed = parse_chat_shipment_text("Necesito transportar 30 de soja desde Tandil hasta Rosario")
    with_vehicle_request = parse_chat_shipment_text("Necesito camión para transportar 30 de soja")

    assert parsed.cargo_category == "GRAIN"
    assert parsed.quantity_estimate == 30
    assert parsed.quantity_unit is None
    assert with_vehicle_request.quantity_unit is None


def test_grain_quantity_unit_is_parsed_only_when_explicit() -> None:
    tons = parse_chat_shipment_text("Necesito transportar 30 toneladas de soja")
    kilograms = parse_chat_shipment_text("Necesito transportar 30000 kg de soja")
    truckloads = parse_chat_shipment_text("Necesito transportar 2 camiones de soja")

    assert tons.quantity_estimate == 30
    assert tons.quantity_unit == "TON"
    assert kilograms.quantity_estimate == 30000
    assert kilograms.quantity_unit == "KG"
    assert truckloads.quantity_unit == "TRUCKLOAD"


def test_standalone_unit_reply_is_recognized() -> None:
    parsed = parse_chat_shipment_text("toneladas")

    assert parsed.quantity_unit == "TON"


def test_resolves_weekday_to_next_date_in_reference_timezone() -> None:
    buenos_aires = ZoneInfo("America/Argentina/Buenos_Aires")
    parsed = parse_chat_shipment_text(
        "Necesito transportar 30 novillos desde Pergamino hasta Rosario el viernes",
        reference_datetime=datetime(2026, 9, 29, 19, 50, tzinfo=buenos_aires),
    )

    assert parsed.date_window_start == datetime(2026, 10, 2, 8, 0, tzinfo=buenos_aires)
    assert parsed.origin == "Pergamino"
    assert parsed.destination == "Rosario"


def test_resolves_friday_to_expected_sandbox_summary_date() -> None:
    buenos_aires = ZoneInfo("America/Argentina/Buenos_Aires")
    parsed = parse_chat_shipment_text(
        "Necesito transportar 45 novillos desde Mar del Plata hasta Rosario el viernes",
        reference_datetime=datetime(2026, 9, 29, 17, 55, tzinfo=buenos_aires),
    )

    assert parsed.date_window_start == datetime(2026, 10, 2, 8, 0, tzinfo=buenos_aires)
    assert parsed.origin == "Mar del Plata"
    assert parsed.destination == "Rosario"


def test_resolves_explicit_argentine_numeric_date_and_removes_it_from_destination() -> None:
    buenos_aires = ZoneInfo("America/Argentina/Buenos_Aires")
    parsed = parse_chat_shipment_text(
        "45 novillos desde Mar del Plata hasta Rosario el 02/10/2026",
        reference_datetime=datetime(2026, 9, 29, 17, 55, tzinfo=buenos_aires),
    )

    assert parsed.date_window_start == datetime(2026, 10, 2, 8, 0, tzinfo=buenos_aires)
    assert parsed.destination == "Rosario"


def test_resolves_accented_weekday() -> None:
    buenos_aires = ZoneInfo("America/Argentina/Buenos_Aires")
    parsed = parse_chat_shipment_text(
        "Traslado de soja el miércoles",
        reference_datetime=datetime(2026, 9, 29, 19, 50, tzinfo=buenos_aires),
    )

    assert parsed.date_window_start == datetime(2026, 9, 30, 8, 0, tzinfo=buenos_aires)


def test_cargo_aliases_are_shared_and_canonicalized() -> None:
    livestock = parse_chat_shipment_text("Necesito 20 vacas")
    grain = parse_chat_shipment_text("Necesito 30 tn de maiz")

    explicit_heads = parse_chat_shipment_text("Necesito 20 cabezas de vacas")
    assert (livestock.cargo_category, livestock.cargo_type, livestock.quantity_unit) == (
        "LIVESTOCK",
        "vacas",
        "HEAD",
    )
    assert explicit_heads.quantity_unit == "HEAD"
    assert (grain.cargo_category, grain.cargo_type, grain.quantity_unit) == ("GRAIN", "maíz", "TON")


def test_livestock_count_and_per_head_weight_are_separate_and_route_is_clean() -> None:
    parsed = parse_chat_shipment_text(
        "Quiero transportar 25 terneros de 300 kilos desde Ayacucho a Cañuelas, para el 27/10/2026"
    )

    assert parsed.cargo_category == "LIVESTOCK"
    assert parsed.cargo_type == "terneros"
    assert parsed.quantity_estimate == 25
    assert parsed.quantity_unit == "HEAD"
    assert parsed.weight_per_head_kg == 300
    assert parsed.origin == "Ayacucho"
    assert parsed.destination == "Cañuelas"
    assert parsed.date_window_start == datetime(2026, 10, 27, 8, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))


def test_approximate_livestock_weight_phrase_is_captured_per_head() -> None:
    parsed = parse_chat_shipment_text(
        "Necesito transportar 30 novillos, peso aproximado 350 kg por cabeza, desde Pergamino hasta Rosario el 10/05/2026"
    )

    assert parsed.quantity_estimate == 30
    assert parsed.quantity_unit == "HEAD"
    assert parsed.weight_per_head_kg == 350


def test_route_destination_drops_para_el_dia_date_suffix() -> None:
    parsed = parse_chat_shipment_text(
        "Quiero transportar 25 terneros desde Ayacucho a Cañuelas, para el día 27/10/2026"
    )

    assert parsed.origin == "Ayacucho"
    assert parsed.destination == "Cañuelas"
