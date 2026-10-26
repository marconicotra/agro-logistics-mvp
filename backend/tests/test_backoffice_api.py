from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_whatsapp_provider, reset_app_state
from app.core.config import get_settings
from app.domain.models import (
    Assignment,
    Carrier,
    CarrierOnboarding,
    ConversationSession,
    Document,
    Driver,
    Location,
    Message,
    Producer,
    ShipmentRequest,
    Trip,
    TripOffer,
    Vehicle,
)
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.base import Base
from app.infrastructure.db.repositories import (
    SqlAssignmentRepository,
    SqlCarrierRepository,
    SqlDocumentRepository,
    SqlDriverRepository,
    SqlMessageRepository,
    SqlShipmentRequestRepository,
    SqlTripRepository,
    SqlVehicleRepository,
)
from app.infrastructure.db.session import get_engine, get_session_factory
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider
from app.main import app


OPERATOR_HEADERS = {"x-operator-user-id": "user_operator", "x-operator-role": "operator"}


def client_with_clean_state() -> tuple[TestClient, object]:
    state = reset_app_state()
    return TestClient(app), state


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "backoffice-api.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("DATABASE_URL", database_url)
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


def test_backoffice_overview_returns_complete_structure() -> None:
    client, state = client_with_clean_state()
    conversation = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(id="cs_overview", channel="kapso", status="OPEN")
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="HUMAN_REVIEW_REQUESTED",
        actor_type="SYSTEM",
        entity_type="ConversationSession",
        entity_id=conversation.id,
        summary="Requiere soporte",
        related_entity_ids={"conversationSessionId": conversation.id},
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="CARRIER_RESPONSE_AMBIGUOUS",
        actor_type="Carrier",
        entity_type="ConversationSession",
        entity_id=conversation.id,
        summary="Respuesta ambigua",
        related_entity_ids={"conversationSessionId": conversation.id},
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="CARRIER_NOTIFICATION_FAILED",
        actor_type="SYSTEM",
        entity_type="ShipmentRequest",
        entity_id="sr_missing",
        summary="Fallo outbound",
    )
    state.shipment_requests.add(ShipmentRequest(status="PUBLISHED"))  # type: ignore[attr-defined]
    state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    state.shipment_requests.add(ShipmentRequest(status="ASSIGNED"))  # type: ignore[attr-defined]
    state.trips.add(  # type: ignore[attr-defined]
        Trip(id="trip_planned", shipment_request_id="sr_1", assignment_id="asg_1", carrier_id="car_1")
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_progress",
            shipment_request_id="sr_2",
            assignment_id="asg_2",
            carrier_id="car_2",
            status="IN_TRANSIT",
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_done",
            shipment_request_id="sr_3",
            assignment_id="asg_3",
            carrier_id="car_3",
            status="COMPLETED",
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_cancelled",
            shipment_request_id="sr_4",
            assignment_id="asg_4",
            carrier_id="car_4",
            status="CANCELLED",
        )
    )
    state.carriers.add(Carrier(name="Validado", is_validated=True))  # type: ignore[attr-defined]
    state.carriers.add(Carrier(name="Pendiente", is_validated=False))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(entity_type="carrier", entity_id="car_1", document_type="dni", status="PENDING")
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(entity_type="carrier", entity_id="car_1", document_type="ruta", status="APPROVED")
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(entity_type="carrier", entity_id="car_1", document_type="seguro", status="REJECTED")
    )

    response = client.get("/api/v1/backoffice/overview", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "open_conversations",
        "open_conversations_requiring_operator",
        "ambiguous_conversations",
        "failed_notifications",
        "total_shipments",
        "published_shipments",
        "shipments_in_matching",
        "assigned_shipments",
        "unassigned_published_shipments",
        "avg_unassigned_age_hours",
        "total_trips",
        "planned_trips",
        "in_progress_trips",
        "completed_trips",
        "cancelled_trips",
        "failed_trips",
        "total_carriers",
        "validated_carriers",
        "pending_validation_carriers",
        "carrier_onboarding_pending_review",
        "carrier_documents_pending_review",
        "total_documents",
        "pending_documents",
        "approved_documents",
        "rejected_documents",
    }
    assert payload["open_conversations"] == 1
    assert payload["open_conversations_requiring_operator"] == 1
    assert payload["ambiguous_conversations"] == 1
    # Dashboard counts notifications whose outbox status is FAILED; an old
    # failure event alone does not represent a currently failed outbox item.
    assert payload["failed_notifications"] == 0
    assert payload["published_shipments"] == 1
    assert payload["shipments_in_matching"] == 1
    assert payload["assigned_shipments"] == 1
    assert payload["planned_trips"] == 1
    assert payload["in_progress_trips"] == 1
    assert payload["completed_trips"] == 1
    assert payload["cancelled_trips"] == 1
    assert payload["failed_trips"] == 0
    assert payload["validated_carriers"] == 1
    assert payload["pending_validation_carriers"] == 1
    assert payload["carrier_onboarding_pending_review"] == 0
    assert payload["carrier_documents_pending_review"] == 1
    assert payload["pending_documents"] == 1
    assert payload["approved_documents"] == 1
    assert payload["rejected_documents"] == 1


def test_producer_backoffice_lists_related_activity_and_excludes_carrier_qa_role() -> None:
    client, state = client_with_clean_state()
    state.producers.add(Producer(id="producer_one", name="Productor QA", contact_phone="+5491112345678"))  # type: ignore[attr-defined]
    state.locations.add(Location(id="loc_origin", original_text="Pergamino", normalized_name="Pergamino"))  # type: ignore[attr-defined]
    state.locations.add(Location(id="loc_destination", original_text="Rosario", normalized_name="Rosario"))  # type: ignore[attr-defined]
    state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="shipment_producer_one",
            producer_id="producer_one",
            producer_phone_number="+5491112345678",
            origin_location_id="loc_origin",
            destination_location_id="loc_destination",
            status="PUBLISHED",
            livestock_type="novillos",
        )
    )
    state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(
            id="conversation_producer",
            channel="whatsapp",
            participant_phone="+5491112345678",
            normalized_phone_number="+5491112345678",
            role_override="Producer",
            active_test_run_id="qa_one",
        )
    )
    state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(
            id="conversation_carrier",
            channel="whatsapp",
            participant_phone="+5491112345678",
            normalized_phone_number="+5491112345678",
            role_override="Carrier",
            active_test_run_id="qa_one",
        )
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="SHIPMENT_PUBLISHED",
        actor_type="SYSTEM",
        entity_type="ShipmentRequest",
        entity_id="shipment_producer_one",
        summary="Carga publicada",
        related_entity_ids={"loadId": "shipment_producer_one"},
    )

    listed = client.get("/api/v1/backoffice/producers", headers=OPERATOR_HEADERS)
    detail = client.get("/api/v1/backoffice/producers/producer_one", headers=OPERATOR_HEADERS)
    unauthorized = client.get("/api/v1/backoffice/producers")

    assert listed.status_code == 200
    assert listed.json()[0]["shipments_count"] == 1
    producer_page = client.get("/api/v1/backoffice/producers/page?limit=25&offset=0", headers=OPERATOR_HEADERS)
    assert producer_page.status_code == 200
    assert producer_page.json()["total"] == 1
    assert [item["id"] for item in producer_page.json()["items"]] == ["producer_one"]
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["shipments"][0]["origin"] == "Pergamino"
    assert payload["shipments"][0]["destination"] == "Rosario"
    assert payload["conversation_ids"] == ["conversation_producer"]
    assert payload["events"][0]["summary"] == "Carga publicada"
    assert unauthorized.status_code == 401


def test_server_managed_operator_roles_require_admin_and_are_audited(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)
    operator_headers = {"x-operator-user-id": "operator-1", "x-operator-role": "operator"}
    admin_headers = {"x-operator-user-id": "admin-1", "x-operator-role": "admin"}

    forbidden = client.put(
        "/api/v1/backoffice/operators/user-2/role",
        headers=operator_headers,
        json={"role": "operator"},
    )
    assigned = client.put(
        "/api/v1/backoffice/operators/user-2/role",
        headers=admin_headers,
        json={"role": "operator"},
    )
    revoked = client.delete("/api/v1/backoffice/operators/user-2/role", headers=admin_headers)

    assert forbidden.status_code == 403
    assert assigned.status_code == 200
    assert assigned.json() == {
        "user_id": "user-2",
        "role": "operator",
        "assigned_by_user_id": "admin-1",
    }
    assert revoked.status_code == 204
    with sql_runtime() as session:
        role = session.get(models.OperatorRoleRecord, "user-2")
        events = session.query(models.EventLogRecord).all()
    assert role is not None and role.deleted_at is not None
    assert {event.event_type for event in events} >= {
        "BACKOFFICE_ROLE_ASSIGNED",
        "BACKOFFICE_ROLE_REVOKED",
    }


def test_backoffice_overview_works_with_sql_backend(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(Carrier(id="car_sql", name="SQL Carrier"))
        SqlShipmentRequestRepository(session).add(ShipmentRequest(id="sr_sql", status="PUBLISHED"))
        SqlDocumentRepository(session).add(
            Document(entity_type="carrier", entity_id="car_sql", document_type="dni")
        )
        session.commit()

    response = TestClient(app).get("/api/v1/backoffice/overview", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_carriers"] == 1
    assert payload["pending_validation_carriers"] == 1
    assert payload["carrier_onboarding_pending_review"] == 0
    assert payload["carrier_documents_pending_review"] == 1
    assert payload["total_shipments"] == 1
    assert payload["published_shipments"] == 1
    assert payload["total_documents"] == 1
    assert payload["pending_documents"] == 1


def test_backoffice_open_conversations_respects_limit() -> None:
    client, state = client_with_clean_state()
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 1, 2, tzinfo=UTC)
    first = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(id="cs_first", channel="kapso", status="OPEN", last_message_at=old)
    )
    second = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(id="cs_second", channel="kapso", status="OPEN", last_message_at=new)
    )
    state.messages.add(  # type: ignore[attr-defined]
        Message(
            conversation_session_id=first.id,
            provider="kapso",
            direction="inbound",
            sender_type="Producer",
            raw_content="mensaje viejo",
        )
    )
    state.messages.add(  # type: ignore[attr-defined]
        Message(
            conversation_session_id=second.id,
            provider="kapso",
            direction="inbound",
            sender_type="Producer",
            raw_content="mensaje nuevo",
        )
    )

    response = client.get(
        "/api/v1/backoffice/conversations/open?limit=1",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["cs_second"]

    page = client.get(
        "/api/v1/backoffice/conversations/open/page?limit=1&offset=1",
        headers=OPERATOR_HEADERS,
    )
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["limit"] == 1
    assert page.json()["offset"] == 1
    assert [item["id"] for item in page.json()["items"]] == ["cs_first"]
    assert page.json()["items"][0]["last_message_preview"] == "mensaje viejo"


def test_backoffice_conversation_messages_returns_ordered_operator_thread() -> None:
    client, state = client_with_clean_state()
    conversation = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(id="cs_thread", channel="kapso", status="OPEN")
    )
    later = datetime(2026, 10, 9, 15, 5, tzinfo=UTC)
    earlier = datetime(2026, 10, 9, 15, 4, tzinfo=UTC)
    state.messages.add(  # type: ignore[attr-defined]
        Message(
            id="msg_agent",
            conversation_session_id=conversation.id,
            provider="kapso",
            direction="outbound",
            sender_type="AGENT",
            message_type="text",
            raw_content="Te aviso cuando haya novedades.",
            sent_at=later,
            test_run_id="qa_synthetic_run",
            related_entity_ids={"qaRole": "TRANSPORTISTA", "providerMessageId": "private-provider-id"},
        )
    )
    state.messages.add(  # type: ignore[attr-defined]
        Message(
            id="msg_human",
            conversation_session_id=conversation.id,
            provider="kapso",
            direction="inbound",
            sender_type="Carrier",
            message_type="text",
            raw_content="Me interesa.",
            received_at=earlier,
            test_run_id="qa_synthetic_run",
            related_entity_ids={"qaRole": "TRANSPORTISTA"},
        )
    )
    state.messages.add(  # type: ignore[attr-defined]
        Message(
            id="msg_media",
            conversation_session_id=conversation.id,
            provider="kapso",
            direction="inbound",
            sender_type="Carrier",
            message_type="document",
            raw_content="private attachment metadata",
        )
    )
    failed_event = state.event_log.record(  # type: ignore[attr-defined]
        event_type="CONVERSATION_REPLY_FAILED",
        actor_type="SYSTEM",
        entity_type="ConversationSession",
        entity_id=conversation.id,
        summary="Respuesta no enviada",
        occurred_at=datetime(2026, 10, 9, 15, 6, tzinfo=UTC),
        test_run_id="qa_synthetic_run",
    )

    response = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["msg_human", "msg_agent", failed_event.event_id, "msg_media"]
    assert payload[0]["content"] == "Me interesa."
    assert payload[0]["qa_role"] == "TRANSPORTISTA"
    assert payload[0]["test_run_id"] == "qa_synthetic_run"
    assert payload[1]["content"] == "Te aviso cuando haya novedades."
    assert payload[1]["delivery_status"] == "accepted_by_provider"
    assert payload[2]["content"] == "No se pudo enviar la respuesta automática."
    assert payload[2]["delivery_status"] == "failed"
    assert payload[3]["content"] is None
    assert all("private-provider-id" not in str(item) for item in payload)
    assert all("raw_content" not in item for item in payload)


def test_backoffice_conversation_messages_requires_operator_and_known_conversation() -> None:
    client, _state = client_with_clean_state()

    unauthorized = client.get("/api/v1/backoffice/conversations/missing/messages")
    missing = client.get(
        "/api/v1/backoffice/conversations/missing/messages",
        headers=OPERATOR_HEADERS,
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404


def test_backoffice_conversation_history_uses_stable_bidirectional_cursors() -> None:
    client, state = client_with_clean_state()
    conversation = state.conversation_sessions.add(
        ConversationSession(id="cs_paged", channel="kapso", status="OPEN")
    )
    start = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    for index in range(55):
        state.messages.add(
            Message(
                id=f"message_{index:03d}",
                conversation_session_id=conversation.id,
                provider="kapso",
                direction="inbound",
                sender_type="Producer",
                message_type="text",
                raw_content=f"mensaje {index}",
                received_at=start + timedelta(seconds=index // 2),
            )
        )

    newest = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages/page?limit=50",
        headers=OPERATOR_HEADERS,
    )
    assert newest.status_code == 200
    payload = newest.json()
    assert len(payload["items"]) == 50
    assert payload["items"][0]["id"] == "message_005"
    assert payload["items"][-1]["id"] == "message_054"
    assert payload["has_more"] is True
    assert payload["next_cursor"]
    assert payload["latest_cursor"]

    older = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages/page?limit=50&cursor={payload['next_cursor']}&direction=older",
        headers=OPERATOR_HEADERS,
    )
    assert older.status_code == 200
    assert [item["id"] for item in older.json()["items"]] == [f"message_{index:03d}" for index in range(5)]
    assert older.json()["has_more"] is False

    state.messages.add(
        Message(
            id="message_055",
            conversation_session_id=conversation.id,
            provider="kapso",
            direction="outbound",
            sender_type="Agent",
            message_type="text",
            raw_content="respuesta nueva",
            sent_at=start + timedelta(minutes=1),
        )
    )
    newer = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages/page?cursor={payload['latest_cursor']}&direction=newer",
        headers=OPERATOR_HEADERS,
    )
    assert newer.status_code == 200
    assert [item["id"] for item in newer.json()["items"]] == ["message_055"]
    assert newer.json()["items"][0]["content"] == "respuesta nueva"


def test_backoffice_conversation_history_pages_from_sql(sql_runtime: sessionmaker[Session]) -> None:
    conversation = ConversationSession(id="cs_sql_paged", channel="kapso", status="OPEN")
    start = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    with sql_runtime() as session:
        from app.infrastructure.db.repositories import SqlConversationSessionRepository

        SqlConversationSessionRepository(session).add(conversation)
        repository = SqlMessageRepository(session)
        for index in range(3):
            repository.add(
                Message(
                    id=f"sql_message_{index}", conversation_session_id=conversation.id, provider="kapso",
                    direction="inbound", sender_type="Producer", message_type="text",
                    raw_content=f"SQL {index}", received_at=start + timedelta(seconds=index),
                )
            )
        session.commit()

    client = TestClient(app)
    first = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages/page?limit=2",
        headers=OPERATOR_HEADERS,
    )
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == ["sql_message_1", "sql_message_2"]
    assert first.json()["has_more"] is True
    previous = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages/page?limit=2&cursor={first.json()['next_cursor']}",
        headers=OPERATOR_HEADERS,
    )
    assert previous.status_code == 200
    assert [item["id"] for item in previous.json()["items"]] == ["sql_message_0"]


def test_backoffice_mock_outbound_message_is_not_reported_as_provider_accepted() -> None:
    client, state = client_with_clean_state()
    conversation = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(id="cs_mock_thread", channel="local-demo", status="OPEN")
    )
    state.messages.add(  # type: ignore[attr-defined]
        Message(
            id="msg_mock_agent",
            conversation_session_id=conversation.id,
            provider="mock_whatsapp",
            direction="outbound",
            sender_type="Agent",
            message_type="text",
            raw_content="Respuesta simulada.",
        )
    )

    response = client.get(
        f"/api/v1/backoffice/conversations/{conversation.id}/messages",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()[0]["delivery_status"] is None


def test_backoffice_unassigned_shipments_excludes_active_assignments() -> None:
    client, state = client_with_clean_state()
    origin = state.locations.add(Location(id="loc_origin", original_text="Azul"))  # type: ignore[attr-defined]
    destination = state.locations.add(Location(id="loc_destination", original_text="Liniers"))  # type: ignore[attr-defined]
    unassigned = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_unassigned",
            status="PUBLISHED",
            origin_location_id=origin.id,
            destination_location_id=destination.id,
            cargo_category="LIVESTOCK",
            cargo_type="novillos",
        )
    )
    assigned = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_assigned", status="MATCHING")
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=unassigned.id,
            carrier_id="car_1",
            response_type="INTERESTED",
            status="INTERESTED",
        )
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=unassigned.id,
            carrier_id="car_2",
            response_type="NOT_AVAILABLE",
            status="NOT_AVAILABLE",
        )
    )
    state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=assigned.id,
            carrier_id="car_3",
            selected_by_user_id="operator",
            status="CONFIRMED",
        )
    )

    response = client.get("/api/v1/backoffice/shipments/unassigned", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["sr_unassigned"]
    assert payload[0]["origin"] == "Azul"
    assert payload[0]["destination"] == "Liniers"
    assert payload[0]["offers_count"] == 2
    assert payload[0]["interested_carriers_count"] == 1
    page = client.get("/api/v1/backoffice/shipments/unassigned/page?limit=1", headers=OPERATOR_HEADERS)
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert [item["id"] for item in page.json()["items"]] == ["sr_unassigned"]


def test_backoffice_can_update_and_delete_shipment_with_event_log() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_editable", status="PUBLISHED", cargo_type="novillos")
    )
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(id="off_editable", shipment_request_id=shipment.id, carrier_id="car_editable")
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_editable",
            shipment_request_id=shipment.id,
            trip_offer_id=offer.id,
            carrier_id="car_editable",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(id="trip_editable_shipment", shipment_request_id=shipment.id, assignment_id=assignment.id, carrier_id="car_editable")
    )

    update_response = client.patch(
        f"/api/v1/backoffice/shipments/{shipment.id}",
        headers=OPERATOR_HEADERS,
        json={
            "status": "MATCHING",
            "origin": "Azul",
            "destination": "Liniers",
            "cargo_type": "vacas",
            "quantity_unit": "HEAD",
            "quantity_estimate": "42",
            "requires_human_review": True,
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()["shipment"]
    assert payload["status"] == "MATCHING"
    assert payload["origin"] == "Azul"
    assert payload["destination"] == "Liniers"
    assert payload["cargo_type"] == "vacas"
    assert payload["quantity_estimate"] == "42"
    assert payload["requires_human_review"] is True
    assert state.shipment_requests.get(shipment.id).status == "MATCHING"  # type: ignore[attr-defined, union-attr]
    assert state.event_log.events[-1].event_type == "LOAD_UPDATED"  # type: ignore[attr-defined]

    delete_response = client.delete(f"/api/v1/backoffice/shipments/{shipment.id}", headers=OPERATOR_HEADERS)

    assert delete_response.status_code == 204
    assert state.shipment_requests.get(shipment.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.trip_offers.get(offer.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.assignments.get(assignment.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.trips.get(trip.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.event_log.events[-1].event_type == "LOAD_ADMIN_DELETED"  # type: ignore[attr-defined]


def test_backoffice_normalizes_shared_cargo_fields_and_rejects_unknown_values() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_cargo_normalization", status="DRAFT")
    )

    normalized = client.patch(
        f"/api/v1/backoffice/shipments/{shipment.id}",
        headers=OPERATOR_HEADERS,
        json={"cargo_category": " grain ", "quantity_unit": "Toneladas"},
    )

    assert normalized.status_code == 200
    assert normalized.json()["shipment"]["cargo_category"] == "GRAIN"
    assert normalized.json()["shipment"]["quantity_unit"] == "TON"

    invalid = client.patch(
        f"/api/v1/backoffice/shipments/{shipment.id}",
        headers=OPERATOR_HEADERS,
        json={"status": "PUBLISHED", "quantity_unit": "bolsas"},
    )

    assert invalid.status_code == 422
    stored = state.shipment_requests.get(shipment.id)  # type: ignore[attr-defined]
    assert stored is not None
    assert stored.status == "DRAFT"
    assert stored.quantity_unit == "TON"


def test_backoffice_shipment_detail_returns_offers_assignment_trip_and_timeline() -> None:
    client, state = client_with_clean_state()
    origin = state.locations.add(  # type: ignore[attr-defined]
        Location(id="loc_shipment_origin", original_text="Cordoba Capital", normalized_name="Cordoba Capital")
    )
    destination = state.locations.add(  # type: ignore[attr-defined]
        Location(id="loc_shipment_destination", original_text="La Plata", normalized_name="La Plata")
    )
    carrier = state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_detail_shipment",
            name="Transporte Sur",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
            is_validated=True,
        )
    )
    vehicle = state.vehicles.add(  # type: ignore[attr-defined]
        Vehicle(id="veh_detail_shipment", carrier_id=carrier.id, plate="AA123BB")
    )
    source_message = state.messages.add(  # type: ignore[attr-defined]
        Message(
            id="msg_shipment_source",
            conversation_session_id="cs_source",
            provider="kapso",
            direction="inbound",
            sender_type="Producer",
            raw_content="Necesito mover 50 vacas de Cordoba a La Plata.",
        )
    )
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_detail",
            status="ASSIGNED",
            producer_phone_number="+5492222222222",
            origin_location_id=origin.id,
            destination_location_id=destination.id,
            cargo_category="LIVESTOCK",
            cargo_type="vacas",
            quantity_unit="HEAD",
            quantity_estimate=50,
            operational_notes="Carga con prioridad alta",
            source_message_id=source_message.id,
            requires_human_review=True,
            missing_critical_fields=["date_window"],
            field_confidence={"origin": "high", "destination": "high"},
        )
    )
    offer_message = state.messages.add(  # type: ignore[attr-defined]
        Message(
            id="msg_offer_source",
            conversation_session_id="cs_offer",
            provider="kapso",
            direction="inbound",
            sender_type="Carrier",
            raw_content="Me interesa, tengo jaula disponible.",
        )
    )
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            id="off_detail",
            shipment_request_id=shipment.id,
            carrier_id=carrier.id,
            vehicle_id=vehicle.id,
            source_message_id=offer_message.id,
            response_type="INTERESTED",
            status="INTERESTED",
        )
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_detail",
            shipment_request_id=shipment.id,
            trip_offer_id=offer.id,
            carrier_id=carrier.id,
            vehicle_id=vehicle.id,
            selected_by_user_id="user_operator",
            confirmed_by_user_id="user_operator",
            status="CONFIRMED",
            confirmation_notes="Asignado desde backoffice",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_detail",
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=carrier.id,
            vehicle_id=vehicle.id,
            status="PLANNED",
        )
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="LOAD_PUBLISHED",
        actor_type="SYSTEM",
        entity_type="ShipmentRequest",
        entity_id=shipment.id,
        summary="Carga publicada",
        related_entity_ids={"loadId": shipment.id},
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="CARRIER_INTERESTED",
        actor_type="CARRIER",
        entity_type="TripOffer",
        entity_id=offer.id,
        summary="Transportista interesado",
        related_entity_ids={"loadId": shipment.id, "tripOfferId": offer.id, "carrierId": carrier.id},
    )
    state.event_log.record(  # type: ignore[attr-defined]
        event_type="ASSIGNMENT_CONFIRMED",
        actor_type="OPERATOR",
        entity_type="Assignment",
        entity_id=assignment.id,
        summary="Assignment confirmado",
        previous_state="PENDING_CONFIRMATION",
        new_state="CONFIRMED",
        related_entity_ids={
            "loadId": shipment.id,
            "tripOfferId": offer.id,
            "assignmentId": assignment.id,
            "tripId": trip.id,
        },
    )

    response = client.get(f"/api/v1/backoffice/shipments/{shipment.id}", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["shipment"]["id"] == shipment.id
    assert payload["shipment"]["origin"] == "Cordoba Capital"
    assert payload["shipment"]["destination"] == "La Plata"
    assert payload["shipment"]["source_message_preview"] == "Necesito mover 50 vacas de Cordoba a La Plata."
    assert payload["shipment"]["requires_human_review"] is True
    assert payload["offers"][0]["id"] == offer.id
    assert payload["offers"][0]["carrier_name"] == "Transporte Sur"
    assert payload["offers"][0]["vehicle_plate"] == "AA123BB"
    assert payload["offers"][0]["source_message_preview"] == "Me interesa, tengo jaula disponible."
    assert payload["active_assignment"]["id"] == assignment.id
    assert payload["active_assignment"]["status"] == "CONFIRMED"
    assert payload["active_trip"]["id"] == trip.id
    assert payload["active_trip"]["status"] == "PLANNED"
    assert [item["event_type"] for item in payload["events"]] == [
        "ASSIGNMENT_CONFIRMED",
        "CARRIER_INTERESTED",
        "LOAD_PUBLISHED",
    ]


def test_backoffice_can_update_and_delete_trip_with_event_log() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_edit_trip", name="Carrier Trip"))  # type: ignore[attr-defined]
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_edit_trip", status="ASSIGNED", producer_phone_number="+5492222222222")
    )
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(id="off_edit_trip", shipment_request_id=shipment.id, carrier_id="car_edit_trip")
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_edit",
            shipment_request_id=shipment.id,
            trip_offer_id=offer.id,
            carrier_id="car_edit_trip",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(id="trip_editable", shipment_request_id=shipment.id, assignment_id=assignment.id, carrier_id="car_edit_trip")
    )

    update_response = client.patch(
        f"/api/v1/backoffice/trips/{trip.id}",
        headers=OPERATOR_HEADERS,
        json={"status": "PLANNED", "incident_notes": "Operador corrigió estado", "requires_human_review": True},
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["id"] == trip.id
    assert payload["status"] == "PLANNED"
    assert state.trips.get(trip.id).status == "PLANNED"  # type: ignore[attr-defined, union-attr]
    assert state.trips.get(trip.id).incident_notes == "Operador corrigió estado"  # type: ignore[attr-defined, union-attr]
    assert state.event_log.events[-1].event_type == "TRIP_UPDATED"  # type: ignore[attr-defined]

    bypass_response = client.patch(
        f"/api/v1/backoffice/trips/{trip.id}",
        headers=OPERATOR_HEADERS,
        json={"status": "IN_TRANSIT"},
    )
    assert bypass_response.status_code == 422
    assert state.trips.get(trip.id).status == "PLANNED"  # type: ignore[attr-defined, union-attr]

    delete_response = client.delete(f"/api/v1/backoffice/trips/{trip.id}", headers=OPERATOR_HEADERS)

    assert delete_response.status_code == 204
    assert state.trips.get(trip.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.shipment_requests.get(shipment.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.trip_offers.get(offer.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert state.assignments.get(assignment.id).deleted_at is not None  # type: ignore[attr-defined, union-attr]
    assert [event.event_type for event in state.event_log.events[-2:]] == [  # type: ignore[attr-defined]
        "TRIP_ADMIN_DELETED",
        "LOAD_ADMIN_DELETED",
    ]

    dashboard_response = client.get(
        "/api/v1/producer/dashboard?phone_number=+5492222222222",
        headers=OPERATOR_HEADERS,
    )

    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["total_shipments"] == 0


def test_backoffice_manual_interest_creates_offer_and_notifies_both_parties() -> None:
    client, state = client_with_clean_state()
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    try:
        carrier = state.carriers.add(  # type: ignore[attr-defined]
            Carrier(id="car_manual_interest", name="Carrier Manual", contact_phone="+5491111111111", is_validated=True)
        )
        shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
            ShipmentRequest(id="sr_manual_interest", status="PUBLISHED", producer_phone_number="+5492222222222")
        )

        response = client.post(
            f"/api/v1/backoffice/shipments/{shipment.id}/manual-interest",
            headers=OPERATOR_HEADERS,
            json={"carrier_id": carrier.id},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["shipment_status"] == "MATCHING"
        assert payload["carrier_id"] == carrier.id
        assert payload["carrier_notification_status"] == "sent"
        assert payload["producer_notification_status"] == "sent"
        assert "CARRIER_INTERESTED" in payload["event_types"]
        assert "LOAD_MATCHING_STARTED" in payload["event_types"]
        assert len(state.trip_offers.list()) == 1  # type: ignore[attr-defined]
        assert state.shipment_requests.get(shipment.id).status == "MATCHING"  # type: ignore[attr-defined, union-attr]
        assert len(provider.sent_messages) == 2
    finally:
        app.dependency_overrides.clear()


def test_backoffice_manual_assign_creates_assignment_trip_and_notifies_both_parties() -> None:
    client, state = client_with_clean_state()
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    try:
        carrier = state.carriers.add(  # type: ignore[attr-defined]
            Carrier(id="car_manual_assign", name="Carrier Assigned", contact_phone="+5491111111111", is_validated=True)
        )
        shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
            ShipmentRequest(id="sr_manual_assign", status="PUBLISHED", producer_phone_number="+5492222222222")
        )

        response = client.post(
            f"/api/v1/backoffice/shipments/{shipment.id}/manual-assign",
            headers=OPERATOR_HEADERS,
            json={"carrier_id": carrier.id, "notes": "Prueba E2E backoffice"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["shipment_status"] == "ASSIGNED"
        assert payload["assignment_status"] == "CONFIRMED"
        assert payload["trip_status"] == "PLANNED"
        assert payload["carrier_id"] == carrier.id
        assert payload["carrier_notification_status"] == "sent"
        assert payload["producer_notification_status"] == "sent"
        assert "ASSIGNMENT_CONFIRMED" in payload["event_types"]
        assert len(state.assignments.list()) == 1  # type: ignore[attr-defined]
        assert len(state.trips.list()) == 1  # type: ignore[attr-defined]
        assert state.shipment_requests.get(shipment.id).status == "ASSIGNED"  # type: ignore[attr-defined, union-attr]
        assert len(provider.sent_messages) == 4
    finally:
        app.dependency_overrides.clear()


def test_backoffice_trips_filters_by_status() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_trip", name="Carrier Trip"))  # type: ignore[attr-defined]
    state.shipment_requests.add(ShipmentRequest(id="sr_trip", status="ASSIGNED"))  # type: ignore[attr-defined]
    state.trips.add(  # type: ignore[attr-defined]
        Trip(id="trip_planned", shipment_request_id="sr_trip", assignment_id="asg_1", carrier_id="car_trip")
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_transit",
            shipment_request_id="sr_trip",
            assignment_id="asg_2",
            carrier_id="car_trip",
            status="IN_TRANSIT",
        )
    )

    response = client.get("/api/v1/backoffice/trips?status=IN_TRANSIT", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "trip_transit",
            "test_run_id": None,
            "status": "IN_TRANSIT",
            "shipment_request_id": "sr_trip",
            "carrier_id": "car_trip",
            "driver_id": None,
            "vehicle_id": None,
            "carrier_name": "Carrier Trip",
            "origin": None,
            "destination": None,
            "planned_start_at": None,
            "updated_at": response.json()[0]["updated_at"],
        }
    ]
    page = client.get("/api/v1/backoffice/trips/page?status=IN_TRANSIT&limit=1", headers=OPERATOR_HEADERS)
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert [item["id"] for item in page.json()["items"]] == ["trip_transit"]


def test_backoffice_trip_actions_update_status_and_notify_both_parties() -> None:
    client, state = client_with_clean_state()
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    try:
        carrier = state.carriers.add(  # type: ignore[attr-defined]
            Carrier(id="car_trip_actions", name="Carrier Trip", contact_phone="+5491111111111", is_validated=True)
        )
        driver = state.drivers.add(  # type: ignore[attr-defined]
            Driver(
                id="drv_trip_actions",
                carrier_id=carrier.id,
                name="Chofer aprobado",
                license_category="F",
                validation_status="APPROVED",
            )
        )
        vehicle = state.vehicles.add(  # type: ignore[attr-defined]
            Vehicle(
                id="veh_trip_actions",
                carrier_id=carrier.id,
                plate="AA123BB",
                status="ACTIVE",
                validation_status="APPROVED",
            )
        )
        shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
            ShipmentRequest(id="sr_trip_actions", status="ASSIGNED", producer_phone_number="+5492222222222")
        )
        assignment = state.assignments.add(  # type: ignore[attr-defined]
            Assignment(
                id="asg_trip_actions",
                shipment_request_id=shipment.id,
                carrier_id=carrier.id,
                selected_by_user_id="user_operator",
                status="CONFIRMED",
            )
        )
        trip = state.trips.add(  # type: ignore[attr-defined]
            Trip(
                id="trip_actions",
                shipment_request_id=shipment.id,
                assignment_id=assignment.id,
                carrier_id=carrier.id,
                status="PLANNED",
                driver_id=driver.id,
                vehicle_id=vehicle.id,
            )
        )

        start_response = client.post(
            f"/api/v1/backoffice/trips/{trip.id}/start",
            headers=OPERATOR_HEADERS,
            json={"notes": "Chofer confirmado"},
        )
        assert start_response.status_code == 200
        assert start_response.json()["trip_status"] == "LOADING_PENDING"

        transit_response = client.post(
            f"/api/v1/backoffice/trips/{trip.id}/mark-in-transit",
            headers=OPERATOR_HEADERS,
            json={"notes": "Salio de origen"},
        )
        assert transit_response.status_code == 200
        assert transit_response.json()["trip_status"] == "IN_TRANSIT"

        complete_response = client.post(
            f"/api/v1/backoffice/trips/{trip.id}/complete",
            headers=OPERATOR_HEADERS,
            json={"notes": "Entregado sin novedades"},
        )
        assert complete_response.status_code == 200
        payload = complete_response.json()
        assert payload["trip_status"] == "COMPLETED"
        assert payload["shipment_status"] == "CLOSED"
        assert payload["carrier_notification_status"] == "sent"
        assert payload["producer_notification_status"] == "sent"
        assert "TRIP_COMPLETED" in payload["event_types"]
        assert state.trips.get(trip.id).status == "COMPLETED"  # type: ignore[attr-defined, union-attr]
        assert state.shipment_requests.get(shipment.id).status == "CLOSED"  # type: ignore[attr-defined, union-attr]
        assert len(provider.sent_messages) == 6
    finally:
        app.dependency_overrides.clear()


def test_trip_start_requires_approved_carrier_driver_and_vehicle() -> None:
    client, state = client_with_clean_state()
    carrier = state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_gate", name="Carrier Gate", is_validated=True, validation_status="APPROVED")
    )
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_gate", status="ASSIGNED")
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_gate",
            shipment_request_id=shipment.id,
            carrier_id=carrier.id,
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_gate",
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=carrier.id,
        )
    )

    no_crew = client.post(f"/api/v1/backoffice/trips/{trip.id}/start", headers=OPERATOR_HEADERS, json={})
    assert no_crew.status_code == 409
    assert no_crew.json()["detail"] == "Assign a reviewed driver and vehicle before trip start"

    driver = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/drivers",
        headers=OPERATOR_HEADERS,
        json={"name": "Chofer de prueba", "license_category": "F"},
    )
    vehicle = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/vehicles",
        headers=OPERATOR_HEADERS,
        json={"plate_number": "AA123BB", "vehicle_type": "camion", "status": "ACTIVE"},
    )
    assert driver.status_code == 201
    assert vehicle.status_code == 201
    driver_id = driver.json()["id"]
    vehicle_id = vehicle.json()["id"]

    unreviewed_crew = client.post(
        f"/api/v1/backoffice/trips/{trip.id}/crew",
        headers=OPERATOR_HEADERS,
        json={"driver_id": driver_id, "vehicle_id": vehicle_id},
    )
    assert unreviewed_crew.status_code == 200
    blocked = client.post(f"/api/v1/backoffice/trips/{trip.id}/start", headers=OPERATOR_HEADERS, json={})
    assert blocked.status_code == 409
    assert "not approved" in blocked.json()["detail"]

    approved_driver = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/drivers/{driver_id}/approve",
        headers=OPERATOR_HEADERS,
        json={"notes": "Licencia revisada por soporte"},
    )
    approved_vehicle = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/vehicles/{vehicle_id}/approve",
        headers=OPERATOR_HEADERS,
        json={"notes": "Unidad revisada por soporte"},
    )
    assert approved_driver.status_code == 200
    assert approved_vehicle.status_code == 200

    expired_document = state.documents.add(  # type: ignore[attr-defined]
        Document(
            entity_type="driver", entity_id=driver_id, document_type="licencia",
            status="APPROVED", expires_at=date.today() - timedelta(days=1),
        )
    )
    expired_doc_start = client.post(f"/api/v1/backoffice/trips/{trip.id}/start", headers=OPERATOR_HEADERS, json={})
    assert expired_doc_start.status_code == 409
    assert "expired" in expired_doc_start.json()["detail"]
    expired_document.expires_at = date.today() + timedelta(days=30)
    state.documents.save(expired_document)  # type: ignore[attr-defined]

    ready = client.post(f"/api/v1/backoffice/trips/{trip.id}/start", headers=OPERATOR_HEADERS, json={})
    assert ready.status_code == 200
    assert ready.json()["trip_status"] == "LOADING_PENDING"
    assert state.trips.get(trip.id).driver_id == driver_id  # type: ignore[attr-defined, union-attr]
    assert state.trips.get(trip.id).vehicle_id == vehicle_id  # type: ignore[attr-defined, union-attr]


def test_document_validity_dates_are_captured_and_invalid_ranges_rejected() -> None:
    client, state = client_with_clean_state()
    carrier = state.carriers.add(Carrier(id="car_doc_validity", name="Carrier Doc Validity"))  # type: ignore[attr-defined]
    driver = state.drivers.add(Driver(id="drv_doc_validity", carrier_id=carrier.id, name="Chofer"))  # type: ignore[attr-defined]
    valid_from = date.today() - timedelta(days=30)
    expires_at = date.today() + timedelta(days=90)
    created = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "licencia", "entity_type": "driver", "entity_id": driver.id,
            "valid_from": valid_from.isoformat(), "expires_at": expires_at.isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["valid_from"] == valid_from.isoformat()
    assert created.json()["expires_at"] == expires_at.isoformat()

    renewal = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "licencia", "entity_type": "driver", "entity_id": driver.id,
            "valid_from": expires_at.isoformat(), "supersedes_document_id": created.json()["id"],
        },
    )
    assert renewal.status_code == 201, renewal.text
    assert renewal.json()["supersedes_document_id"] == created.json()["id"]
    assert state.documents.get(created.json()["id"]) is not None  # type: ignore[attr-defined]

    other_driver = state.drivers.add(  # type: ignore[attr-defined]
        Driver(id="drv_other_doc_validity", carrier_id=carrier.id, name="Otro chofer")
    )
    cross_owner_renewal = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "licencia", "entity_type": "driver", "entity_id": other_driver.id,
            "supersedes_document_id": created.json()["id"],
        },
    )
    assert cross_owner_renewal.status_code == 422

    invalid = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "licencia", "entity_type": "driver", "entity_id": driver.id,
            "valid_from": expires_at.isoformat(), "expires_at": valid_from.isoformat(),
        },
    )
    assert invalid.status_code == 422


def test_sql_trip_start_guard_loads_crew_state_from_sql(sql_runtime: sessionmaker[Session]) -> None:
    with sql_runtime() as session:
        carrier = SqlCarrierRepository(session).add(
            Carrier(
                id="car_sql_gate",
                name="SQL Gate",
                is_validated=True,
                validation_status="APPROVED",
            )
        )
        shipment = SqlShipmentRequestRepository(session).add(ShipmentRequest(id="sr_sql_gate", status="ASSIGNED"))
        assignment = SqlAssignmentRepository(session).add(
            Assignment(
                id="asg_sql_gate",
                shipment_request_id=shipment.id,
                carrier_id=carrier.id,
                selected_by_user_id="user_operator",
                status="CONFIRMED",
            )
        )
        trip = SqlTripRepository(session).add(
            Trip(
                id="trip_sql_gate",
                shipment_request_id=shipment.id,
                assignment_id=assignment.id,
                carrier_id=carrier.id,
            )
        )
        session.commit()

    client = TestClient(app)
    blocked = client.post(
        f"/api/v1/backoffice/trips/{trip.id}/start",
        headers=OPERATOR_HEADERS,
        json={},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Assign a reviewed driver and vehicle before trip start"

    driver = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/drivers",
        headers=OPERATOR_HEADERS,
        json={"name": "Chofer SQL", "license_category": "F"},
    )
    vehicle = client.post(
        f"/api/v1/backoffice/carriers/{carrier.id}/vehicles",
        headers=OPERATOR_HEADERS,
        json={"plate_number": "AB123CD", "vehicle_type": "camion", "status": "ACTIVE"},
    )
    assert driver.status_code == 201
    assert vehicle.status_code == 201
    driver_id = driver.json()["id"]
    vehicle_id = vehicle.json()["id"]

    for path in (
        f"/api/v1/backoffice/carriers/{carrier.id}/drivers/{driver_id}/approve",
        f"/api/v1/backoffice/carriers/{carrier.id}/vehicles/{vehicle_id}/approve",
    ):
        approved = client.post(path, headers=OPERATOR_HEADERS, json={"notes": "Revisión manual de prueba"})
        assert approved.status_code == 200

    assigned = client.post(
        f"/api/v1/backoffice/trips/{trip.id}/crew",
        headers=OPERATOR_HEADERS,
        json={"driver_id": driver_id, "vehicle_id": vehicle_id},
    )
    assert assigned.status_code == 200
    started = client.post(
        f"/api/v1/backoffice/trips/{trip.id}/start",
        headers=OPERATOR_HEADERS,
        json={},
    )
    assert started.status_code == 200


def test_backoffice_pending_carriers_returns_not_validated_only() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_pending", name="Pendiente", contact_phone="+5491111111111")
    )
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_valid", name="Validado", is_validated=True)
    )
    state.vehicles.add(Vehicle(id="veh_1", carrier_id="car_pending"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(entity_type="carrier", entity_id="car_pending", document_type="dni", status="PENDING")
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(entity_type="carrier", entity_id="car_pending", document_type="ruta", status="APPROVED")
    )

    response = client.get("/api/v1/backoffice/carriers/pending-approval", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["car_pending"]
    assert payload[0]["vehicles_count"] == 1
    assert payload[0]["truck_count"] == 1
    assert payload[0]["documents_count"] == 2
    assert payload[0]["pending_documents_count"] == 1
    assert payload[0]["email"] is None
    assert payload[0]["company_name"] is None
    assert payload[0]["cuit"] is None


def test_carrier_onboarding_pending_creates_onboarding_and_missing_fields() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_onboarding", name="Carrier Onboarding"))  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/backoffice/carrier-onboarding/pending",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["carrier_id"] == "car_onboarding"
    assert payload[0]["onboarding_id"].startswith("cob_")
    assert payload[0]["validation_status"] == "DRAFT"
    assert payload[0]["onboarding_status"] == "WAITING_DATA"
    assert payload[0]["missing_fields"] == ["contact_phone", "cuit", "vehicle", "document"]
    assert len(state.carrier_onboardings.list()) == 1  # type: ignore[attr-defined]


def test_carrier_onboarding_detail_returns_carrier_vehicles_documents_and_events() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_detail",
            name="Carrier Detail",
            contact_phone="+5491111111111",
            email="carrier@example.com",
            company_name="Carrier SA",
            cuit="30-12345678-9",
        )
    )
    state.vehicles.add(Vehicle(id="veh_detail", carrier_id="car_detail", plate="AA123BB"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_detail",
            entity_type="carrier",
            entity_id="car_detail",
            document_type="dni",
            external_uri="manual://dni",
        )
    )

    response = client.get(
        "/api/v1/backoffice/carriers/car_detail/onboarding",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["carrier"]["id"] == "car_detail"
    assert payload["carrier"]["email"] == "carrier@example.com"
    assert payload["carrier"]["company_name"] == "Carrier SA"
    assert payload["carrier"]["cuit"] == "30-12345678-9"
    assert payload["onboarding"]["status"] == "PENDING_REVIEW"
    assert payload["onboarding"]["missing_fields"] == []
    assert payload["vehicles"][0]["id"] == "veh_detail"
    assert payload["vehicles"][0]["plate_number"] == "AA123BB"
    assert payload["documents"][0]["id"] == "doc_detail"
    assert payload["documents"][0]["has_file"] is False
    assert "external_uri" not in payload["documents"][0]
    assert "storage_uri" not in payload["documents"][0]
    assert payload["events"][0]["event_type"] == "CARRIER_ONBOARDING_CREATED"


def test_carrier_onboarding_backoffice_detail_shows_whatsapp_capture_progress() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_capture_progress", name="Carrier QA"))  # type: ignore[attr-defined]
    state.carrier_onboardings.add(  # type: ignore[attr-defined]
        CarrierOnboarding(
            carrier_id="car_capture_progress",
            capture_context={
                "step": "review_confirmation",
                "captured_vehicle_count": "1",
                "declared_vehicle_count": "2",
            },
        )
    )

    response = client.get(
        "/api/v1/backoffice/carriers/car_capture_progress/onboarding",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["capture_progress"] == {
        "step": "review_confirmation",
        "captured_vehicle_count": 1,
        "declared_vehicle_count": 2,
    }


def test_carrier_onboarding_approve_carrier_updates_validation_state() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_approve",
            name="Carrier Approve",
            contact_phone="+5491111111111",
            cuit="30-12345678-9",
        )
    )
    state.vehicles.add(Vehicle(id="veh_approve", carrier_id="car_approve"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_approve",
            entity_type="carrier",
            entity_id="car_approve",
            document_type="dni",
            external_uri="manual://dni",
        )
    )

    response = client.post(
        "/api/v1/backoffice/carriers/car_approve/approve",
        headers=OPERATOR_HEADERS,
        json={"notes": "Aprobado por soporte"},
    )

    assert response.status_code == 200
    carrier = state.carriers.get("car_approve")  # type: ignore[attr-defined]
    onboarding = state.carrier_onboardings.list()[0]  # type: ignore[attr-defined]
    assert carrier.is_validated is True
    assert carrier.validation_status == "APPROVED"
    assert carrier.reviewed_by_user_id == "user_operator"
    assert carrier.validated_at is not None
    assert onboarding.status == "APPROVED"
    assert response.json()["carrier"]["validation_status"] == "APPROVED"


def test_carrier_onboarding_approve_carrier_requires_missing_fields_resolved() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_missing", name="Carrier Missing"))  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/backoffice/carriers/car_missing/approve",
        headers=OPERATOR_HEADERS,
        json={},
    )

    assert response.status_code == 409
    assert "missing fields" in response.json()["detail"]
    carrier = state.carriers.get("car_missing")  # type: ignore[attr-defined]
    assert carrier.is_validated is False
    assert carrier.validation_status == "DRAFT"


def test_carrier_onboarding_reject_carrier_saves_reason() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_reject", name="Carrier Reject"))  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/backoffice/carriers/car_reject/reject",
        headers=OPERATOR_HEADERS,
        json={"reason": "Falta documentación obligatoria"},
    )

    assert response.status_code == 200
    carrier = state.carriers.get("car_reject")  # type: ignore[attr-defined]
    onboarding = state.carrier_onboardings.list()[0]  # type: ignore[attr-defined]
    assert carrier.is_validated is False
    assert carrier.validation_status == "REJECTED"
    assert carrier.rejection_reason == "Falta documentación obligatoria"
    assert carrier.rejected_at is not None
    assert onboarding.status == "REJECTED"
    assert onboarding.rejection_reason == "Falta documentación obligatoria"


def test_carrier_onboarding_approve_document() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_doc_approve", name="Doc Approve"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_to_approve",
            entity_type="carrier",
            entity_id="car_doc_approve",
            document_type="dni",
            external_uri="manual://dni",
        )
    )

    response = client.post(
        "/api/v1/backoffice/carriers/car_doc_approve/documents/doc_to_approve/approve",
        headers=OPERATOR_HEADERS,
        json={"notes": "Documento legible"},
    )

    assert response.status_code == 200
    document = state.documents.get("doc_to_approve")  # type: ignore[attr-defined]
    assert document.status == "APPROVED"
    assert document.notes == "Documento legible"
    assert document.reviewed_by_user_id == "user_operator"
    assert document.reviewed_at is not None
    assert document.rejection_reason is None
    assert response.json()["status"] == "APPROVED"
    assert any(
        event.event_type == "CARRIER_DOCUMENT_APPROVED" and event.entity_id == "doc_to_approve"
        for event in state.event_log.events  # type: ignore[attr-defined]
    )


def test_carrier_onboarding_reject_document_with_reason() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_doc_reject", name="Doc Reject"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_to_reject",
            entity_type="carrier",
            entity_id="car_doc_reject",
            document_type="seguro",
            external_uri="manual://seguro",
        )
    )

    response = client.post(
        "/api/v1/backoffice/carriers/car_doc_reject/documents/doc_to_reject/reject",
        headers=OPERATOR_HEADERS,
        json={"reason": "Documento vencido"},
    )

    assert response.status_code == 200
    document = state.documents.get("doc_to_reject")  # type: ignore[attr-defined]
    assert document.status == "REJECTED"
    assert document.rejection_reason == "Documento vencido"
    assert document.reviewed_by_user_id == "user_operator"
    assert document.reviewed_at is not None
    assert response.json()["status"] == "REJECTED"
    assert any(
        event.event_type == "CARRIER_DOCUMENT_REJECTED" and event.entity_id == "doc_to_reject"
        for event in state.event_log.events  # type: ignore[attr-defined]
    )


def test_carrier_onboarding_old_validated_carrier_is_treated_as_approved() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_old_valid", name="Old Valid", is_validated=True)
    )

    pending_response = client.get(
        "/api/v1/backoffice/carrier-onboarding/pending",
        headers=OPERATOR_HEADERS,
    )
    overview_response = client.get("/api/v1/backoffice/overview", headers=OPERATOR_HEADERS)

    assert pending_response.status_code == 200
    assert pending_response.json() == []
    assert overview_response.status_code == 200
    assert overview_response.json()["validated_carriers"] == 1
    assert overview_response.json()["pending_validation_carriers"] == 0


def test_backoffice_carrier_documents_returns_matching_documents() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_docs", name="Docs"))  # type: ignore[attr-defined]
    expected = state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_expected",
            entity_type="carrier",
            entity_id="car_docs",
            document_type="dni",
            external_uri="s3://docs/dni.jpg",
            status="PENDING",
            notes="frente",
        )
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(id="doc_other", entity_type="carrier", entity_id="car_other", document_type="dni")
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(id="doc_shipment", entity_type="shipment", entity_id="car_docs", document_type="guia")
    )
    state.drivers.add(Driver(id="drv_docs_list", carrier_id="car_docs", name="Driver Listed"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(id="doc_driver_list", entity_type="driver", entity_id="drv_docs_list", document_type="licencia")
    )

    response = client.get(
        "/api/v1/backoffice/carriers/car_docs/documents",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    documents = {item["id"]: item for item in response.json()}
    assert set(documents) == {expected.id, "doc_driver_list"}
    assert documents[expected.id]["entity_type"] == "carrier"
    assert documents[expected.id]["entity_id"] == "car_docs"
    assert documents[expected.id]["document_type"] == "dni"
    assert documents[expected.id]["has_file"] is False
    assert documents[expected.id]["notes"] == "frente"
    assert documents["doc_driver_list"]["entity_type"] == "driver"
    assert "external_uri" not in documents[expected.id]
    assert "storage_uri" not in documents[expected.id]


def test_carrier_document_download_is_private_scoped_and_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_root = tmp_path / "private-media"
    storage_root.mkdir()
    file_path = storage_root / "license.pdf"
    file_path.write_bytes(b"fixture document")
    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(b"must not be served")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(storage_root))
    get_settings.cache_clear()
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_private", name="Private"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_private",
            entity_type="carrier",
            entity_id="car_private",
            document_type="driver_license",
            storage_uri=str(file_path),
            file_name="license.pdf",
            mime_type="application/pdf",
        )
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_escape",
            entity_type="carrier",
            entity_id="car_private",
            document_type="driver_license",
            storage_uri=str(outside_file),
        )
    )

    response = client.get(
        "/api/v1/backoffice/carriers/car_private/documents/doc_private/content",
        headers=OPERATOR_HEADERS,
    )
    wrong_carrier = client.get(
        "/api/v1/backoffice/carriers/car_other/documents/doc_private/content",
        headers=OPERATOR_HEADERS,
    )
    escaped_path = client.get(
        "/api/v1/backoffice/carriers/car_private/documents/doc_escape/content",
        headers=OPERATOR_HEADERS,
    )
    missing_auth = client.get("/api/v1/backoffice/carriers/car_private/documents/doc_private/content")

    assert response.status_code == 200
    assert response.content == b"fixture document"
    assert response.headers["cache-control"] == "private, no-store"
    assert "attachment" in response.headers["content-disposition"]
    assert wrong_carrier.status_code == 404
    assert escaped_path.status_code == 404
    assert missing_auth.status_code == 401
    assert [event.event_type for event in state.event_log.events] == ["CARRIER_DOCUMENT_ACCESSED"]  # type: ignore[attr-defined]
    assert state.event_log.events[0].payload == {"document_type": "driver_license"}  # type: ignore[attr-defined]


def test_driver_and_vehicle_documents_are_entity_scoped_and_do_not_auto_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_root = tmp_path / "private-media"
    storage_root.mkdir()
    license_file = storage_root / "driver-license.pdf"
    license_file.write_bytes(b"test license bytes")
    vehicle_file = storage_root / "vehicle-card.pdf"
    vehicle_file.write_bytes(b"test vehicle bytes")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(storage_root))
    get_settings.cache_clear()
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_docs_scope", name="Scoped Carrier"))  # type: ignore[attr-defined]
    state.carriers.add(Carrier(id="car_docs_other", name="Other Carrier"))  # type: ignore[attr-defined]
    state.drivers.add(Driver(id="drv_docs_scope", carrier_id="car_docs_scope", name="Driver One"))  # type: ignore[attr-defined]
    state.drivers.add(Driver(id="drv_docs_other", carrier_id="car_docs_other", name="Driver Two"))  # type: ignore[attr-defined]
    state.vehicles.add(Vehicle(id="veh_docs_scope", carrier_id="car_docs_scope", plate="AA123BB"))  # type: ignore[attr-defined]

    driver_document = client.post(
        "/api/v1/backoffice/carriers/car_docs_scope/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "driver_license",
            "entity_type": "driver",
            "entity_id": "drv_docs_scope",
            "storage_uri": str(license_file),
            "file_name": "driver-license.pdf",
            "mime_type": "application/pdf",
        },
    )
    vehicle_document = client.post(
        "/api/v1/backoffice/carriers/car_docs_scope/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "vehicle_registration",
            "entity_type": "vehicle",
            "entity_id": "veh_docs_scope",
            "storage_uri": str(vehicle_file),
        },
    )
    wrong_owner = client.post(
        "/api/v1/backoffice/carriers/car_docs_scope/documents",
        headers=OPERATOR_HEADERS,
        json={"document_type": "driver_license", "entity_type": "driver", "entity_id": "drv_docs_other"},
    )
    detail = client.get("/api/v1/backoffice/carriers/car_docs_scope/onboarding", headers=OPERATOR_HEADERS)
    driver_download = client.get(
        f"/api/v1/backoffice/carriers/car_docs_scope/documents/{driver_document.json()['id']}/content",
        headers=OPERATOR_HEADERS,
    )
    vehicle_download = client.get(
        f"/api/v1/backoffice/carriers/car_docs_scope/documents/{vehicle_document.json()['id']}/content",
        headers=OPERATOR_HEADERS,
    )
    cross_carrier_download = client.get(
        f"/api/v1/backoffice/carriers/car_docs_other/documents/{driver_document.json()['id']}/content",
        headers=OPERATOR_HEADERS,
    )
    approved_document = client.post(
        f"/api/v1/backoffice/carriers/car_docs_scope/documents/{driver_document.json()['id']}/approve",
        headers=OPERATOR_HEADERS,
        json={"notes": "Documento de prueba revisado"},
    )
    attempted_owner_change = client.patch(
        f"/api/v1/backoffice/carriers/car_docs_scope/documents/{driver_document.json()['id']}",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "driver_license",
            "entity_type": "vehicle",
            "entity_id": "veh_docs_scope",
        },
    )

    assert driver_document.status_code == vehicle_document.status_code == 201
    assert wrong_owner.status_code == 422
    payload = detail.json()
    assert payload["drivers"][0]["documents"][0]["entity_type"] == "driver"
    assert payload["vehicles"][0]["documents"][0]["entity_type"] == "vehicle"
    assert "storage_uri" not in payload["drivers"][0]["documents"][0]
    assert driver_download.status_code == vehicle_download.status_code == 200
    assert driver_download.content == b"test license bytes"
    assert vehicle_download.content == b"test vehicle bytes"
    assert cross_carrier_download.status_code == 404
    assert approved_document.status_code == 200
    assert attempted_owner_change.status_code == 409
    assert state.drivers.get("drv_docs_scope").validation_status == "PENDING_REVIEW"  # type: ignore[attr-defined, union-attr]
    assert state.vehicles.get("veh_docs_scope").validation_status == "PENDING_REVIEW"  # type: ignore[attr-defined, union-attr]


def test_sql_backoffice_returns_driver_and_vehicle_documents(sql_runtime: sessionmaker[Session]) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(Carrier(id="car_sql_docs", name="SQL Docs"))
        SqlDriverRepository(session).add(Driver(id="drv_sql_docs", carrier_id="car_sql_docs", name="Driver SQL"))
        SqlVehicleRepository(session).add(Vehicle(id="veh_sql_docs", carrier_id="car_sql_docs", plate="AB456CD"))
        SqlDocumentRepository(session).add(
            Document(
                id="doc_sql_driver",
                entity_type="driver",
                entity_id="drv_sql_docs",
                document_type="driver_license",
                storage_uri="private/license.pdf",
            )
        )
        SqlDocumentRepository(session).add(
            Document(
                id="doc_sql_vehicle",
                entity_type="vehicle",
                entity_id="veh_sql_docs",
                document_type="vehicle_registration",
                storage_uri="private/registration.pdf",
            )
        )
        session.commit()

    response = TestClient(app).get(
        "/api/v1/backoffice/carriers/car_sql_docs/onboarding",
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["drivers"][0]["documents"][0]["id"] == "doc_sql_driver"
    assert payload["vehicles"][0]["documents"][0]["id"] == "doc_sql_vehicle"
    assert "storage_uri" not in payload["drivers"][0]["documents"][0]


def test_backoffice_lists_all_carriers_and_filters() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_pending_all",
            name="Transporte Norte",
            contact_phone="+5491111111111",
            company_name="Norte SRL",
            cuit="20111111112",
        )
    )
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_approved_all",
            name="Sur Logistica",
            contact_phone="+5492222222222",
            company_name="Sur SA",
            cuit="20222222223",
            is_validated=True,
            validation_status="APPROVED",
        )
    )
    state.carrier_onboardings.add(  # type: ignore[attr-defined]
        CarrierOnboarding(carrier_id="car_pending_all", status="PENDING_REVIEW")
    )
    state.vehicles.add(  # type: ignore[attr-defined]
        Vehicle(id="veh_search", carrier_id="car_pending_all", plate="AB123CD", status="ACTIVE")
    )
    state.documents.add(  # type: ignore[attr-defined]
        Document(entity_type="carrier", entity_id="car_pending_all", document_type="dni", status="PENDING")
    )

    response = client.get("/api/v1/backoffice/carriers?search=ab123cd", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["car_pending_all"]
    assert payload[0]["vehicles_count"] == 1
    assert payload[0]["pending_documents_count"] == 1
    assert payload[0]["missing_fields"] == ["document"]

    approved_response = client.get(
        "/api/v1/backoffice/carriers?validation_status=APPROVED",
        headers=OPERATOR_HEADERS,
    )
    assert approved_response.status_code == 200
    assert [item["id"] for item in approved_response.json()] == ["car_approved_all"]

    review_response = client.get(
        "/api/v1/backoffice/carriers?onboarding_pending_only=true",
        headers=OPERATOR_HEADERS,
    )
    assert review_response.status_code == 200
    assert [item["id"] for item in review_response.json()] == ["car_pending_all"]
    carrier_page = client.get("/api/v1/backoffice/carriers/page?limit=1&offset=1", headers=OPERATOR_HEADERS)
    assert carrier_page.status_code == 200
    assert carrier_page.json()["total"] == 2
    assert carrier_page.json()["limit"] == 1


def test_backoffice_create_and_update_carrier_records_events() -> None:
    client, state = client_with_clean_state()

    create_response = client.post(
        "/api/v1/backoffice/carriers",
        headers=OPERATOR_HEADERS,
        json={
            "name": "Carrier Manual",
            "phone": "+5491130303030",
            "email": "manual@example.com",
            "company_name": "Manual SRL",
            "cuit": "20303030301",
            "truck_count": 2,
            "truck_types": ["camion", "semi"],
            "truck_body_type": "jaula",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    carrier_id = created["carrier"]["id"]
    carrier = state.carriers.get(carrier_id)  # type: ignore[attr-defined]
    assert carrier is not None
    assert carrier.company_name == "Manual SRL"
    assert created["onboarding"]["missing_fields"] == ["vehicle", "document"]
    assert any(
        event.event_type == "CARRIER_CREATED" and event.entity_id == carrier_id
        for event in state.event_log.events  # type: ignore[attr-defined]
    )

    update_response = client.patch(
        f"/api/v1/backoffice/carriers/{carrier_id}",
        headers=OPERATOR_HEADERS,
        json={
            "name": "Carrier Manual Editado",
            "phone": "+5491140404040",
            "email": "editado@example.com",
            "company_name": "Manual Editado SRL",
            "cuit": "20303030309",
            "truck_count": 3,
            "truck_types": ["camion"],
            "truck_body_type": "baranda",
        },
    )

    assert update_response.status_code == 200
    updated = state.carriers.get(carrier_id)  # type: ignore[attr-defined]
    assert updated.name == "Carrier Manual Editado"
    assert updated.truck_body_type == "baranda"
    update_event = next(
        event
        for event in state.event_log.events  # type: ignore[attr-defined]
        if event.event_type == "CARRIER_UPDATED" and event.entity_id == carrier_id
    )
    assert "name" in update_event.payload["changed_fields"]
    assert update_event.payload["new_values"]["name"] == "Carrier Manual Editado"


def test_backoffice_vehicle_crud_recalculates_onboarding() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_vehicle", name="Carrier Vehicle", contact_phone="+5491111111111", cuit="20111111119")
    )

    create_response = client.post(
        "/api/v1/backoffice/carriers/car_vehicle/vehicles",
        headers=OPERATOR_HEADERS,
        json={
            "plate_number": "AC456EF",
            "vehicle_type": "camion",
            "body_type": "jaula",
            "capacity": "18.50",
            "status": "ACTIVE",
        },
    )

    assert create_response.status_code == 201
    vehicle_id = create_response.json()["id"]
    assert create_response.json()["body_type"] == "jaula"
    onboarding = state.carrier_onboardings.list()[0]  # type: ignore[attr-defined]
    assert onboarding.missing_fields == ["document"]

    update_response = client.patch(
        f"/api/v1/backoffice/carriers/car_vehicle/vehicles/{vehicle_id}",
        headers=OPERATOR_HEADERS,
        json={"plate_number": "ZZ999ZZ", "status": "MAINTENANCE", "body_type": "baranda"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["plate_number"] == "ZZ999ZZ"
    assert update_response.json()["status"] == "MAINTENANCE"
    assert any(
        event.event_type == "CARRIER_VEHICLE_UPDATED" and event.entity_id == vehicle_id
        for event in state.event_log.events  # type: ignore[attr-defined]
    )

    delete_response = client.delete(
        f"/api/v1/backoffice/carriers/car_vehicle/vehicles/{vehicle_id}",
        headers=OPERATOR_HEADERS,
    )
    assert delete_response.status_code == 200
    onboarding = state.carrier_onboardings.list()[0]  # type: ignore[attr-defined]
    assert "vehicle" in onboarding.missing_fields
    assert any(
        event.event_type == "CARRIER_VEHICLE_DISABLED" and event.entity_id == vehicle_id
        for event in state.event_log.events  # type: ignore[attr-defined]
    )


def test_backoffice_create_vehicle_with_capacity_works_in_sql_backend(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(
            Carrier(id="car_sql_vehicle", name="Carrier SQL Vehicle", contact_phone="+5491111111111", cuit="20111111119")
        )
        session.commit()

    response = TestClient(app).post(
        "/api/v1/backoffice/carriers/car_sql_vehicle/vehicles",
        headers=OPERATOR_HEADERS,
        json={
            "plate_number": "AC456EF",
            "vehicle_type": "camion",
            "body_type": "jaula",
            "capacity": "18.50",
            "status": "ACTIVE",
        },
    )

    assert response.status_code == 201
    assert response.json()["body_type"] == "jaula"


def test_backoffice_manual_document_create_and_update() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_document_manual",
            name="Carrier Document",
            contact_phone="+5491111111111",
            cuit="20111111119",
        )
    )
    state.vehicles.add(Vehicle(id="veh_document_manual", carrier_id="car_document_manual", status="ACTIVE"))  # type: ignore[attr-defined]

    create_response = client.post(
        "/api/v1/backoffice/carriers/car_document_manual/documents",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "cedula",
            "external_uri": "https://example.com/cedula.pdf",
            "file_name": "cedula.pdf",
            "mime_type": "application/pdf",
            "notes": "Carga manual",
        },
    )

    assert create_response.status_code == 201
    document_id = create_response.json()["id"]
    assert create_response.json()["provider"] == "manual"
    assert state.carrier_onboardings.list()[0].missing_fields == []  # type: ignore[attr-defined]

    update_response = client.patch(
        f"/api/v1/backoffice/carriers/car_document_manual/documents/{document_id}",
        headers=OPERATOR_HEADERS,
        json={
            "document_type": "cedula_verde",
            "external_uri": "https://example.com/cedula-verde.pdf",
            "file_name": "cedula-verde.pdf",
            "mime_type": "application/pdf",
            "notes": "Actualizado por soporte",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["document_type"] == "cedula_verde"
    assert any(
        event.event_type == "CARRIER_DOCUMENT_CREATED_MANUAL" and event.entity_id == document_id
        for event in state.event_log.events  # type: ignore[attr-defined]
    )
    assert any(
        event.event_type == "CARRIER_DOCUMENT_UPDATED" and event.entity_id == document_id
        for event in state.event_log.events  # type: ignore[attr-defined]
    )


def test_backoffice_suspend_and_mark_carrier_in_review() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_suspend",
            name="Carrier Suspend",
            contact_phone="+5491111111111",
            cuit="20111111119",
            is_validated=True,
            validation_status="APPROVED",
        )
    )
    state.vehicles.add(Vehicle(id="veh_suspend", carrier_id="car_suspend", status="ACTIVE"))  # type: ignore[attr-defined]
    state.documents.add(  # type: ignore[attr-defined]
        Document(
            id="doc_suspend",
            entity_type="carrier",
            entity_id="car_suspend",
            document_type="dni",
            external_uri="https://example.com/dni.pdf",
        )
    )

    suspend_response = client.post(
        "/api/v1/backoffice/carriers/car_suspend/suspend",
        headers=OPERATOR_HEADERS,
        json={"reason": "Documentacion vencida"},
    )
    assert suspend_response.status_code == 200
    assert suspend_response.json()["carrier"]["validation_status"] == "SUSPENDED"

    review_response = client.post(
        "/api/v1/backoffice/carriers/car_suspend/mark-in-review",
        headers=OPERATOR_HEADERS,
        json={"notes": "Se regularizo documentacion"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["carrier"]["validation_status"] == "PENDING_REVIEW"
    assert any(
        event.event_type == "CARRIER_SUSPENDED" and event.entity_id == "car_suspend"
        for event in state.event_log.events  # type: ignore[attr-defined]
    )
    assert any(
        event.event_type == "CARRIER_MARKED_IN_REVIEW" and event.entity_id == "car_suspend"
        for event in state.event_log.events  # type: ignore[attr-defined]
    )


def test_backoffice_endpoints_require_operator() -> None:
    client, _state = client_with_clean_state()

    missing_auth = client.get("/api/v1/backoffice/overview")
    wrong_role = client.get(
        "/api/v1/backoffice/overview",
        headers={"x-operator-user-id": "user_viewer", "x-operator-role": "viewer"},
    )
    missing_mutation_auth = client.post("/api/v1/backoffice/carriers/car_1/approve", json={})
    wrong_mutation_role = client.post(
        "/api/v1/backoffice/carriers/car_1/reject",
        headers={"x-operator-user-id": "user_viewer", "x-operator-role": "viewer"},
        json={"reason": "sin permisos"},
    )

    assert missing_auth.status_code == 401
    assert wrong_role.status_code == 403
    assert missing_mutation_auth.status_code == 401
    assert wrong_mutation_role.status_code == 403
