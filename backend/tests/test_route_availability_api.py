from datetime import UTC, datetime, timedelta
from collections.abc import Iterator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import reset_app_state
from app.domain.models import Carrier
from app.main import app
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import EventLogRecord
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlRouteAvailabilityRepository
from app.core.config import get_settings
from app.infrastructure.db.session import get_engine, get_session_factory
from app.domain.route_availability import RouteAvailability


HEADERS = {"x-operator-user-id": "qa-operator", "x-operator-role": "operator"}


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'route-availability.db'}"
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


def test_backoffice_can_create_list_match_and_close_route_availability():
    state = reset_app_state()
    carrier = Carrier(name="Transportista QA")
    state.carriers.add(carrier)
    client = TestClient(app)
    now = datetime.now(UTC)
    payload = {
        "carrier_id": carrier.id,
        "test_run_id": "scenario-route-qa",
        "origin": "Corrientes",
        "destination": "Buenos Aires",
        "stops": ["Paraná", "Rosario"],
        "window_start": now.isoformat(),
        "window_end": (now + timedelta(days=2)).isoformat(),
        "capacity": "30",
        "capacity_unit": "TON",
        "cargo_types": ["maíz"],
        "equipment_types": ["granelero"],
    }

    created = client.post("/api/v1/backoffice/route-availabilities", json=payload, headers=HEADERS)
    assert created.status_code == 201, created.text
    availability_id = created.json()["id"]
    assert created.json()["status"] == "DRAFT"

    activated = client.patch(
        f"/api/v1/backoffice/route-availabilities/{availability_id}/status",
        json={"status": "ACTIVE"}, headers=HEADERS,
    )
    assert activated.status_code == 200

    availability_page = client.get("/api/v1/backoffice/route-availabilities/page?limit=25&offset=0", headers=HEADERS)
    assert availability_page.status_code == 200
    assert availability_page.json()["total"] == 1
    assert [item["id"] for item in availability_page.json()["items"]] == [availability_id]

    matches = client.post("/api/v1/backoffice/route-availabilities/match", json={
        "origin": "Paraná", "destination": "Rosario", "shipment_at": now.isoformat(),
        "cargo_type": "maíz", "quantity": "25000", "quantity_unit": "KG", "equipment_type": "granelero",
    }, headers=HEADERS)
    assert matches.status_code == 200, matches.text
    assert matches.json()[0]["availability"]["id"] == availability_id
    assert matches.json()[0]["segment_origin"] == "Paraná"

    closed = client.patch(
        f"/api/v1/backoffice/route-availabilities/{availability_id}/status",
        json={"status": "CLOSED"}, headers=HEADERS,
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    events = state.event_log.events
    assert [event.event_type for event in events] == [
        "ROUTE_AVAILABILITY_CREATED", "ROUTE_AVAILABILITY_ACTIVE", "ROUTE_AVAILABILITY_CLOSED"
    ]
    assert events[1].previous_state == "DRAFT"
    assert events[1].new_state == "ACTIVE"
    assert events[0].test_run_id == "scenario-route-qa"


def test_route_availability_endpoints_require_operator_authentication():
    reset_app_state()
    response = TestClient(app).get("/api/v1/backoffice/route-availabilities")
    assert response.status_code == 401


def test_local_backoffice_cors_supports_alternate_loopback_dev_ports():
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5176"})
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5176"
    rejected = client.get("/health", headers={"Origin": "https://example.invalid"})
    assert "access-control-allow-origin" not in rejected.headers


def test_listing_expires_window_and_records_audit_event():
    state = reset_app_state()
    carrier = state.carriers.add(Carrier(name="Carrier expiration QA"))
    now = datetime.now(UTC)
    availability = RouteAvailability(
        carrier_id=carrier.id, origin="Corrientes", destination="Buenos Aires",
        window_start=now - timedelta(days=3), window_end=now - timedelta(days=1), status="ACTIVE",
    )
    state.route_availabilities.add(availability)
    response = TestClient(app).get("/api/v1/backoffice/route-availabilities", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()[0]["status"] == "EXPIRED"
    assert state.event_log.events[-1].event_type == "ROUTE_AVAILABILITY_EXPIRED"
    assert state.event_log.events[-1].previous_state == "ACTIVE"


def test_sql_repository_persists_route_availability_and_lifecycle_state():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        repository = SqlRouteAvailabilityRepository(session)
        item = RouteAvailability(
            carrier_id="carrier-sql",
            origin="Corrientes",
            destination="Buenos Aires",
            stops=["Paraná"],
            window_start=now,
            window_end=now + timedelta(days=1),
            capacity=30,
            capacity_unit="TON",
            cargo_types=["maíz"],
            equipment_types=["granelero"],
        )
        repository.add(item)
        session.commit()
        loaded = repository.get(item.id)
        assert loaded is not None
        assert loaded.route == ("Corrientes", "Paraná", "Buenos Aires")
        loaded.status = "ACTIVE"
        repository.save(loaded)
        session.commit()
        assert repository.get(item.id).status == "ACTIVE"
    engine.dispose()


def test_sql_backoffice_persists_availability_and_audit_events_atomically(sql_runtime):
    with sql_runtime() as session:
        carrier = SqlCarrierRepository(session).add(Carrier(name="SQL QA Carrier"))
        session.commit()
    client = TestClient(app)
    created = client.post("/api/v1/backoffice/route-availabilities", headers=HEADERS, json={
        "carrier_id": carrier.id, "test_run_id": "scenario-sql-route", "origin": "Corrientes",
        "destination": "Buenos Aires", "stops": ["Paraná"], "capacity": "30",
        "capacity_unit": "toneladas", "cargo_types": ["maiz"], "equipment_types": ["cerealero"],
    })
    assert created.status_code == 201, created.text
    availability_id = created.json()["id"]
    active = client.patch(
        f"/api/v1/backoffice/route-availabilities/{availability_id}/status",
        headers=HEADERS, json={"status": "ACTIVE"},
    )
    assert active.status_code == 200, active.text
    with sql_runtime() as session:
        stored = SqlRouteAvailabilityRepository(session).get(availability_id)
        events = session.scalars(select(EventLogRecord).order_by(EventLogRecord.occurred_at)).all()
    assert stored is not None and stored.status == "ACTIVE"
    assert [event.event_type for event in events] == ["ROUTE_AVAILABILITY_CREATED", "ROUTE_AVAILABILITY_ACTIVE"]
    assert all(event.test_run_id == "scenario-sql-route" for event in events)
