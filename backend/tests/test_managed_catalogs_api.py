from collections.abc import Iterator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.chat_shipment_parser import parse_chat_shipment_text
from app.core.config import get_settings
from app.infrastructure.db.base import Base
from app.infrastructure.db.catalogs import load_active_cargo_catalog, load_active_geography_catalog
from app.infrastructure.db.session import get_engine, get_session_factory
from app.main import app

ADMIN_HEADERS = {"x-operator-user-id": "catalog-admin", "x-operator-role": "admin"}
OPERATOR_HEADERS = {"x-operator-user-id": "catalog-operator", "x-operator-role": "operator"}


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'catalogs.db'}"
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    engine = create_engine(database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_settings.cache_clear()


def test_geography_catalog_crud_hierarchy_and_province_filter(sql_runtime) -> None:
    factory = sql_runtime
    client = TestClient(app)
    province = client.post(
        "/api/v1/backoffice/catalogs/geography",
        headers=ADMIN_HEADERS,
        json={"kind": "PROVINCE", "name": "Provincia de Prueba"},
    )
    assert province.status_code == 201, province.text
    department = client.post(
        "/api/v1/backoffice/catalogs/geography",
        headers=ADMIN_HEADERS,
        json={"kind": "DEPARTMENT", "name": "Partido de Prueba", "parent_id": province.json()["id"]},
    )
    assert department.status_code == 201, department.text
    locality = client.post(
        "/api/v1/backoffice/catalogs/geography",
        headers=ADMIN_HEADERS,
        json={
            "kind": "LOCALITY", "name": "Localidad de Prueba", "parent_id": department.json()["id"],
            "aliases": ["Localidad Prueba", "localidad prueba"],
        },
    )
    assert locality.status_code == 201, locality.text
    assert locality.json()["aliases"] == ["Localidad Prueba"]

    page = client.get(
        "/api/v1/backoffice/catalogs/geography",
        headers=OPERATOR_HEADERS,
        params={"kind": "LOCALITY", "parent_id": province.json()["id"]},
    )
    assert page.status_code == 200, page.text
    assert [row["name"] for row in page.json()["items"]] == ["Localidad de Prueba"]

    cannot_disable_parent = client.patch(
        f"/api/v1/backoffice/catalogs/geography/{department.json()['id']}",
        headers=ADMIN_HEADERS,
        json={"active": False},
    )
    assert cannot_disable_parent.status_code == 409

    with factory() as session:
        geography = load_active_geography_catalog(session)
    # The database-managed hierarchy is the resolver's source of truth.
    from app.domain.location_catalog import resolve_catalog_locality
    result = resolve_catalog_locality("Localidad Prueba", geography)
    assert result.status == "RESOLVED"
    assert result.locality is not None
    assert result.locality.province == "Provincia de Prueba"
    assert result.locality.department == "Partido de Prueba"


def test_cargo_catalog_crud_is_consumed_by_chat_parser(sql_runtime) -> None:
    factory = sql_runtime
    client = TestClient(app)
    category = client.post(
        "/api/v1/backoffice/catalogs/cargo/categories",
        headers=ADMIN_HEADERS,
        json={"code": "FERTILIZERS", "name": "Fertilizantes", "aliases": ["insumos"]},
    )
    assert category.status_code == 201, category.text
    cargo_type = client.post(
        "/api/v1/backoffice/catalogs/cargo/types",
        headers=ADMIN_HEADERS,
        json={
            "code": "urea_granulada", "category_code": "FERTILIZERS", "name": "Urea granulada",
            "aliases": ["urea"],
        },
    )
    assert cargo_type.status_code == 201, cargo_type.text

    with factory() as session:
        categories, types = load_active_cargo_catalog(session)
    parsed = parse_chat_shipment_text(
        "Necesito transportar urea desde Azul hasta Olavarría",
        cargo_categories=categories,
        cargo_types=types,
    )
    assert parsed.cargo_category == "FERTILIZERS"
    assert parsed.cargo_type == "Urea granulada"

    disabled = client.patch(
        "/api/v1/backoffice/catalogs/cargo/types/urea_granulada",
        headers=ADMIN_HEADERS,
        json={"active": False},
    )
    assert disabled.status_code == 200, disabled.text
    with factory() as session:
        categories, types = load_active_cargo_catalog(session)
    parsed_after_disable = parse_chat_shipment_text(
        "Necesito transportar urea desde Azul hasta Olavarría",
        cargo_categories=categories,
        cargo_types=types,
    )
    assert parsed_after_disable.cargo_type is None


def test_catalog_mutation_requires_admin(sql_runtime) -> None:
    del sql_runtime
    response = TestClient(app).post(
        "/api/v1/backoffice/catalogs/cargo/categories",
        headers=OPERATOR_HEADERS,
        json={"code": "NEW_CATEGORY", "name": "Nueva categoría"},
    )
    assert response.status_code == 403
