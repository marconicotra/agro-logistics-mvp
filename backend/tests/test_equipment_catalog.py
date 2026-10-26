from app.domain.equipment import normalize_equipment, normalize_equipment_or_declared


def test_equipment_aliases_are_accent_insensitive_and_canonical() -> None:
    assert normalize_equipment("CAMIÓN JAULA") == "camion jaula"
    assert normalize_equipment("cerealero") == "granelero"
    assert normalize_equipment("plataforma") == "playo"


def test_unknown_equipment_is_retained_as_declared_for_human_review() -> None:
    assert normalize_equipment("acoplado especial") is None
    assert normalize_equipment_or_declared("  acoplado   especial ") == "acoplado especial"
