from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.domain.models import Assignment, Carrier, ShipmentRequest, Trip, TripOffer
from app.infrastructure.db.base import Base
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.models import (
    AssignmentRecord,
    EventLogRecord,
    NotificationOutboxRecord,
    ShipmentRequestRecord,
    TripRecord,
)
from app.infrastructure.db.repositories import (
    SqlAssignmentRepository,
    SqlCarrierRepository,
    SqlShipmentRequestRepository,
    SqlTripRepository,
    SqlTripOfferRepository,
)
from app.infrastructure.db.session import get_engine, get_session_factory
from app.main import app


OPERATOR_HEADERS = {
    "x-internal-api-key": "qa-internal-test-key",
    "x-operator-user-id": "user_operator",
    "x-operator-role": "operator",
}


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "api-sql.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("INTERNAL_API_KEY", "qa-internal-test-key")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = create_engine(database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def test_db_health_uses_sql_backend(sql_runtime: sessionmaker[Session]) -> None:
    client = TestClient(app)

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "storage_backend": "sql",
        "database": "reachable",
        "schema": "outdated",
        "schema_revision": "unversioned",
        "expected_revision": "0019_route_operations",
    }


def test_db_health_reports_current_alembic_revision(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        session.execute(text("create table alembic_version (version_num varchar(32) not null)"))
        session.execute(
            text("insert into alembic_version (version_num) values ('0019_route_operations')")
        )
        session.commit()

    response = TestClient(app).get("/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "storage_backend": "sql",
        "database": "reachable",
        "schema": "current",
        "schema_revision": "0019_route_operations",
        "expected_revision": "0019_route_operations",
    }


def test_admin_api_validates_and_publishes_with_sql_repositories(legacy_broadcast, 
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(
            Carrier(id="car_1", name="Carrier 1", contact_phone="+5491111111111")
        )
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(status="PENDING_OPERATOR_REVIEW")
        )
        session.commit()

    client = TestClient(app, headers=OPERATOR_HEADERS)
    validate_response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers=OPERATOR_HEADERS,
        json={"notes": "validado en SQL", "idempotency_key": "sql_validate_api"},
    )
    publish_response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={"carrier_ids": ["car_1"], "idempotency_key": "sql_publish_api"},
    )

    assert validate_response.status_code == 200
    assert publish_response.status_code == 200

    with sql_runtime() as session:
        stored = session.get(ShipmentRequestRecord, shipment.id)
        events = session.scalars(select(EventLogRecord)).all()
        outbox = session.scalars(select(NotificationOutboxRecord)).all()

    assert stored is not None
    assert stored.status == "PUBLISHED"
    assert [event.event_type for event in events] == [
        "LOAD_VALIDATED",
        "LOAD_PUBLISHED",
        "BROADCAST_SENT",
        "CARRIER_NOTIFIED",
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_QUEUED",
    ]
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"


def test_admin_api_creates_chat_draft_with_sql_repositories(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 40 cabezas de novillos de Azul a Liniers manana",
            "phone_number": "+5491135690073",
            "idempotency_key": "sql_chat_draft_1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DRAFT"

    with sql_runtime() as session:
        stored = session.get(ShipmentRequestRecord, payload["shipment_id"])
        events = session.scalars(select(EventLogRecord)).all()

    assert stored is not None
    assert stored.status == "DRAFT"
    assert stored.cargo_category == "LIVESTOCK"
    assert stored.cargo_type == "novillos"
    assert stored.quantity_unit == "HEAD"
    assert stored.livestock_type == "novillos"
    assert stored.quantity_estimate == 40
    assert stored.operational_notes == "Necesito camion para 40 cabezas de novillos de Azul a Liniers manana"
    assert stored.requires_human_review is False
    assert len(events) == 1
    assert events[0].event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"
    assert events[0].entity_id == stored.id
    assert events[0].payload == {
        "text": "Necesito camion para 40 cabezas de novillos de Azul a Liniers manana",
        "phone_number": "+5491135690073",
        "source": "kapso",
        "cargo_category": "LIVESTOCK",
        "cargo_type": "novillos",
        "quantity_unit": "HEAD",
    }
    assert events[0].idempotency_key == "sql_chat_draft_1"


def test_admin_api_create_chat_draft_is_idempotent_with_sql_repositories(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)
    request = {
        "text": "Necesito camion para 12 vacas",
        "phone_number": "+5491135690073",
        "idempotency_key": "sql_chat_draft_retry",
    }

    first = client.post("/api/v1/shipment-requests/from-chat", headers=OPERATOR_HEADERS, json=request)
    second = client.post("/api/v1/shipment-requests/from-chat", headers=OPERATOR_HEADERS, json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()

    with sql_runtime() as session:
        shipments = session.scalars(select(ShipmentRequestRecord)).all()
        events = session.scalars(select(EventLogRecord)).all()

    assert len(shipments) == 1
    assert shipments[0].livestock_type == "vacas"
    assert shipments[0].quantity_estimate == 12
    assert len(events) == 1
    assert events[0].event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"


def test_admin_api_creates_grain_chat_draft_with_sql_repositories(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 30 toneladas de soja de Tandil a Rosario manana",
            "phone_number": "+5491135690073",
            "idempotency_key": "sql_chat_draft_grain",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cargo_category"] == "GRAIN"
    assert payload["cargo_type"] == "soja"
    assert payload["quantity_unit"] == "TON"

    with sql_runtime() as session:
        stored = session.get(ShipmentRequestRecord, payload["shipment_id"])

    assert stored is not None
    assert stored.status == "DRAFT"
    assert stored.cargo_category == "GRAIN"
    assert stored.cargo_type == "soja"
    assert stored.quantity_unit == "TON"
    assert stored.livestock_type is None
    assert stored.quantity_estimate == 30


def test_admin_api_lists_recent_chat_drafts_with_sql_repositories(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)
    client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 22 cabezas de novillos",
            "phone_number": "+5492222222222",
            "idempotency_key": "sql_chat_draft_other_phone",
        },
    )
    target = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 110 cabezas de vacas de Tandil a Cañuelas mañana",
            "phone_number": "541135690073",
            "idempotency_key": "sql_chat_draft_target_phone",
        },
    )

    response = client.get(
        "/api/v1/admin/shipments/from-chat/recent",
        headers=OPERATOR_HEADERS,
        params={"phone_number": "+5491135690073"},
    )

    assert target.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["shipment_id"] == target.json()["shipment_id"]
    assert payload[0]["status"] == "DRAFT"
    assert payload[0]["livestock_type"] == "vacas"
    assert payload[0]["quantity_estimate"] == "110.00"
    assert payload[0]["source_phone_number"] == "541135690073"


def test_admin_api_lists_draft_shipments_with_sql_repositories(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        older = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                id="sr_sql_old_draft",
                status="DRAFT",
                livestock_type="novillos",
                quantity_estimate=40,
                operational_notes="SQL draft viejo",
                created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            )
        )
        newer = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                id="sr_sql_new_draft",
                status="DRAFT",
                livestock_type="toros",
                quantity_estimate=500,
                operational_notes="SQL draft nuevo",
                created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )
        )
        SqlShipmentRequestRepository(session).add(ShipmentRequest(id="sr_sql_validated", status="VALIDATED"))
        session.commit()

    client = TestClient(app)
    response = client.get("/api/v1/admin/shipments/drafts", headers=OPERATOR_HEADERS)

    assert older.id == "sr_sql_old_draft"
    assert response.status_code == 200
    payload = response.json()
    assert [item["shipment_id"] for item in payload] == [newer.id, older.id]
    assert payload[0]["livestock_type"] == "toros"
    assert payload[0]["quantity_estimate"] == "500.00"


def test_admin_api_confirms_assignment_and_cancels_trip_with_sql_transaction(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(status="MATCHING", missing_critical_fields=[], requires_human_review=False)
        )
        assignment = SqlAssignmentRepository(session).add(
            Assignment(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                selected_by_user_id="user_operator",
            )
        )
        session.commit()

    client = TestClient(app)
    confirm_response = client.post(
        f"/api/v1/assignments/{assignment.id}/confirm",
        headers=OPERATOR_HEADERS,
        json={"confirmation_notes": "confirmado SQL", "idempotency_key": "sql_confirm_api"},
    )
    trip_id = confirm_response.json()["trip_id"]
    cancel_response = client.post(
        f"/api/v1/trips/{trip_id}/cancel",
        headers=OPERATOR_HEADERS,
        json={"reason": "cancelacion SQL", "idempotency_key": "sql_cancel_api"},
    )

    assert confirm_response.status_code == 200
    assert cancel_response.status_code == 200

    with sql_runtime() as session:
        stored_assignment = session.get(AssignmentRecord, assignment.id)
        stored_shipment = session.get(ShipmentRequestRecord, shipment.id)
        stored_trip = session.get(TripRecord, trip_id)
        events = session.scalars(select(EventLogRecord)).all()

    assert stored_assignment is not None
    assert stored_assignment.status == "CONFIRMED"
    assert stored_shipment is not None
    assert stored_shipment.status == "ASSIGNED"
    assert stored_trip is not None
    assert stored_trip.status == "CANCELLED"
    assert {event.event_type for event in events} == {
        "ASSIGNMENT_CREATED",
        "ASSIGNMENT_CONFIRMED",
        "TRIP_CREATED",
        "TRIP_CANCELLED",
    }


def test_admin_api_selects_offer_with_sql_transaction(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(status="MATCHING", missing_critical_fields=[], requires_human_review=False)
        )
        offer = SqlTripOfferRepository(session).add(
            TripOffer(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                response_type="INTERESTED",
            )
        )
        session.commit()

    client = TestClient(app)
    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id, "idempotency_key": "sql_select_offer_api"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assignment_status"] == "PROPOSED"
    assert payload["trip_status"] == "PLANNED"

    with sql_runtime() as session:
        assignments = session.scalars(select(AssignmentRecord)).all()
        trips = session.scalars(select(TripRecord)).all()
        events = session.scalars(select(EventLogRecord)).all()

    assert len(assignments) == 1
    assert assignments[0].trip_offer_id == offer.id
    assert len(trips) == 1
    assert trips[0].assignment_id == assignments[0].id
    assert [event.event_type for event in events] == [
        "ASSIGNMENT_CREATED",
        "ASSIGNMENT_SELECTED",
        "TRIP_CREATED",
    ]


def test_producer_accept_offer_with_sql_transaction(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                status="MATCHING",
                producer_phone_number="+5491111111111",
                missing_critical_fields=[],
                requires_human_review=False,
            )
        )
        offer = SqlTripOfferRepository(session).add(
            TripOffer(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                response_type="INTERESTED",
            )
        )
        session.commit()

    client = TestClient(app, headers=OPERATOR_HEADERS)
    first = client.post(
        f"/api/v1/shipments/{shipment.id}/offers/{offer.id}/accept",
        json={"phone_number": "+5491111111111", "idempotency_key": "sql_producer_accept_offer_" + "x" * 120},
    )
    second = client.post(
        f"/api/v1/shipments/{shipment.id}/offers/{offer.id}/accept",
        json={"phone_number": "+5491111111111", "idempotency_key": "sql_producer_accept_offer_" + "x" * 120},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["assignment_status"] == "CONFIRMED"
    assert first.json()["shipment_status"] == "ASSIGNED"
    assert second.json()["assignment_id"] == first.json()["assignment_id"]
    assert second.json()["trip_id"] == first.json()["trip_id"]

    with sql_runtime() as session:
        stored_shipment = session.get(ShipmentRequestRecord, shipment.id)
        assignments = session.scalars(select(AssignmentRecord)).all()
        trips = session.scalars(select(TripRecord)).all()
        events = session.scalars(select(EventLogRecord).order_by(EventLogRecord.occurred_at)).all()
        outbox = session.scalars(select(NotificationOutboxRecord)).all()

    assert stored_shipment is not None
    assert stored_shipment.status == "ASSIGNED"
    assert stored_shipment.producer_phone_number == "+5491111111111"
    assert len(assignments) == 1
    assert assignments[0].status == "CONFIRMED"
    assert assignments[0].selected_by_user_id == "producer:+5491111111111"
    assert len(trips) == 1
    assert trips[0].assignment_id == assignments[0].id
    assert [event.event_type for event in events] == [
        "PRODUCER_OFFER_ACCEPTED",
        "ASSIGNMENT_CREATED",
        "TRIP_CREATED",
        "MARKETPLACE_MATCH_CONFIRMED",
        "ASSIGNMENT_CONFIRMED",
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_FAILED",
        "PRODUCER_NOTIFICATION_REQUESTED",
        "PRODUCER_NOTIFICATION_QUEUED",
    ]
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"


def test_admin_api_select_offer_returns_existing_assignment_with_sql_transaction(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(status="MATCHING", missing_critical_fields=[], requires_human_review=False)
        )
        selected_offer = SqlTripOfferRepository(session).add(
            TripOffer(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                response_type="INTERESTED",
            )
        )
        other_offer = SqlTripOfferRepository(session).add(
            TripOffer(
                shipment_request_id=shipment.id,
                carrier_id="car_2",
                response_type="INTERESTED",
            )
        )
        assignment = SqlAssignmentRepository(session).add(
            Assignment(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                trip_offer_id=selected_offer.id,
                selected_by_user_id="user_operator",
                status="PROPOSED",
            )
        )
        trip = SqlTripRepository(session).add(
            Trip(
                shipment_request_id=shipment.id,
                assignment_id=assignment.id,
                carrier_id=assignment.carrier_id,
                status="PLANNED",
            )
        )
        session.commit()

    client = TestClient(app)
    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": other_offer.id, "idempotency_key": "sql_select_existing_assignment"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assignment_id"] == assignment.id
    assert payload["trip_id"] == trip.id
    assert payload["trip_offer_id"] == selected_offer.id
    assert payload["event_types"] == []

    with sql_runtime() as session:
        assignments = session.scalars(select(AssignmentRecord)).all()
        trips = session.scalars(select(TripRecord)).all()
        events = session.scalars(select(EventLogRecord)).all()

    assert len(assignments) == 1
    assert len(trips) == 1
    assert events == []


def test_admin_api_lookup_operation_with_sql_transaction(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                id="sr_sql_lookup",
                status="MATCHING",
                livestock_type="vacas",
                quantity_estimate=130,
                operational_notes="SQL lookup",
                missing_critical_fields=[],
                requires_human_review=False,
            )
        )
        assignment = SqlAssignmentRepository(session).add(
            Assignment(
                id="asg_sql_lookup",
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                trip_offer_id="off_sql_lookup",
                selected_by_user_id="user_operator",
                status="PROPOSED",
            )
        )
        trip = SqlTripRepository(session).add(
            Trip(
                id="trip_sql_lookup",
                shipment_request_id=shipment.id,
                assignment_id=assignment.id,
                carrier_id=assignment.carrier_id,
                status="PLANNED",
            )
        )
        session.commit()

    client = TestClient(app)
    by_trip = client.get(f"/api/v1/admin/operations/lookup/{trip.id}", headers=OPERATOR_HEADERS)
    by_shipment = client.get(f"/api/v1/admin/operations/lookup/{shipment.id}", headers=OPERATOR_HEADERS)

    assert by_trip.status_code == 200
    assert by_shipment.status_code == 200
    assert by_trip.json() == by_shipment.json()
    assert by_trip.json()["shipment_id"] == shipment.id
    assert by_trip.json()["assignment_id"] == assignment.id
    assert by_trip.json()["trip_id"] == trip.id
    assert by_trip.json()["operational_notes"] == "SQL lookup"


def test_admin_api_lookup_operation_returns_canonical_assignment_with_sql_transaction(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                id="sr_sql_lookup_canonical",
                status="ASSIGNED",
                livestock_type="vacas",
                quantity_estimate=130,
                operational_notes="SQL canonical lookup",
                missing_critical_fields=[],
                requires_human_review=False,
            )
        )
        old_assignment = SqlAssignmentRepository(session).add(
            Assignment(
                id="asg_sql_lookup_old",
                shipment_request_id=shipment.id,
                carrier_id="car_old",
                selected_by_user_id="user_operator",
                status="PROPOSED",
                created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )
        )
        confirmed_assignment = SqlAssignmentRepository(session).add(
            Assignment(
                id="asg_sql_lookup_confirmed",
                shipment_request_id=shipment.id,
                carrier_id="car_confirmed",
                selected_by_user_id="user_operator",
                status="CONFIRMED",
                created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            )
        )
        old_trip = SqlTripRepository(session).add(
            Trip(
                id="trip_sql_lookup_old",
                shipment_request_id=shipment.id,
                assignment_id=old_assignment.id,
                carrier_id=old_assignment.carrier_id,
                status="PLANNED",
            )
        )
        confirmed_trip = SqlTripRepository(session).add(
            Trip(
                id="trip_sql_lookup_confirmed",
                shipment_request_id=shipment.id,
                assignment_id=confirmed_assignment.id,
                carrier_id=confirmed_assignment.carrier_id,
                status="PLANNED",
            )
        )
        session.commit()

    client = TestClient(app)
    by_old_trip = client.get(f"/api/v1/admin/operations/lookup/{old_trip.id}", headers=OPERATOR_HEADERS)
    by_shipment = client.get(f"/api/v1/admin/operations/lookup/{shipment.id}", headers=OPERATOR_HEADERS)

    assert by_old_trip.status_code == 200
    assert by_shipment.status_code == 200
    assert by_old_trip.json() == by_shipment.json()
    assert by_shipment.json()["assignment_id"] == confirmed_assignment.id
    assert by_shipment.json()["trip_id"] == confirmed_trip.id
    assert by_shipment.json()["carrier_id"] == "car_confirmed"


def test_admin_api_lists_shipments_with_offers_from_sql_backend(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        older = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                id="sr_sql_older",
                status="PUBLISHED",
                livestock_type="novillos",
                quantity_estimate=30,
                created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            )
        )
        newer = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(
                id="sr_sql_newer",
                status="MATCHING",
                livestock_type="vacas",
                quantity_estimate=45,
                created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )
        )
        SqlShipmentRequestRepository(session).add(
            ShipmentRequest(id="sr_sql_validated", status="VALIDATED")
        )
        SqlTripOfferRepository(session).add(
            TripOffer(
                id="off_sql_older_offer",
                shipment_request_id=older.id,
                carrier_id="car_1",
                response_type="INTERESTED",
                created_at=datetime(2026, 5, 1, 13, 0, tzinfo=UTC),
            )
        )
        SqlTripOfferRepository(session).add(
            TripOffer(
                id="off_sql_newer_old_offer",
                shipment_request_id=newer.id,
                carrier_id="car_2",
                response_type="INTERESTED",
                created_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
            )
        )
        SqlTripOfferRepository(session).add(
            TripOffer(
                id="off_sql_newer_new_offer",
                shipment_request_id=newer.id,
                carrier_id="car_3",
                response_type="DECLINED",
                created_at=datetime(2026, 5, 2, 14, 0, tzinfo=UTC),
            )
        )
        session.commit()

    client = TestClient(app, headers=OPERATOR_HEADERS)
    response = client.get("/api/v1/admin/shipments/with-offers")

    assert response.status_code == 200
    payload = response.json()
    assert [item["shipment_id"] for item in payload] == [newer.id, older.id]
    assert [offer["trip_offer_id"] for offer in payload[0]["offers"]] == [
        "off_sql_newer_new_offer",
        "off_sql_newer_old_offer",
    ]
    assert payload[1]["offers"][0]["trip_offer_id"] == "off_sql_older_offer"


def test_memory_storage_backend_still_works_after_sql_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    client = TestClient(app)

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "storage_backend": "memory",
        "database": "not_configured",
    }
