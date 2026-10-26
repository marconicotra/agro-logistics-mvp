from app.domain.location_catalog import resolve_argentine_locality


def test_georef_catalog_resolves_unique_locality_without_network() -> None:
    result = resolve_argentine_locality("Már del Plata")

    assert result.status == "RESOLVED"
    assert result.locality is not None
    assert result.locality.georef_id == "06357110"
    assert result.locality.name == "Mar del Plata"
    assert result.locality.province == "Buenos Aires"
    assert result.catalog_version.startswith("georef-localidades-sha256:")


def test_georef_catalog_does_not_guess_homonymous_locality() -> None:
    result = resolve_argentine_locality("San Pedro")

    assert result.status == "AMBIGUOUS"
    assert result.locality is None
    assert len({candidate.province for candidate in result.candidates}) > 1


def test_known_capital_aliases_resolve_to_canonical_localities() -> None:
    cordoba = resolve_argentine_locality("Córdoba capital")
    corrientes = resolve_argentine_locality("Ciudad de Corrientes")

    assert (cordoba.status, cordoba.locality.name if cordoba.locality else None) == ("RESOLVED", "Córdoba")
    assert (corrientes.status, corrientes.locality.name if corrientes.locality else None) == ("RESOLVED", "Corrientes")


def test_rural_reference_is_preserved_as_declared_text_when_not_a_locality() -> None:
    result = resolve_argentine_locality("Estancia El Pino, partido de San Pedro")

    assert result.status == "NOT_FOUND"
    assert result.locality is None
    assert result.candidates == ()
