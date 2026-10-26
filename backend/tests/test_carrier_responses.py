from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.ai import AIExtractionError, LoadDataExtraction
from app.application.admin_ops import AdminOpsService
from app.application.conversation_orchestrator import ConversationOrchestrator, InboundConversationMessage
from app.application.notifications import NotificationService
from app.domain.events import EventLogService, current_test_run_id
from app.domain.models import (
    Assignment,
    Carrier,
    ConversationSession,
    Location,
    Message,
    ShipmentRequest,
    Trip,
    TripOffer,
)
from app.domain.route_availability import RouteAvailability
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.base import Base
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.models import (
    EventLogRecord,
    NotificationOutboxRecord,
    ShipmentRequestRecord,
    TripOfferRecord,
)
from app.infrastructure.db.repositories import (
    SqlCarrierRepository,
    SqlConversationSessionRepository,
    SqlShipmentRequestRepository,
)
from app.infrastructure.db.session import get_engine, get_session_factory
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider
from app.infrastructure.repositories.memory import InMemoryRepository
from app.core.config import get_settings
from app.main import app


class FakeAIClient:
    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        raise AssertionError("Carrier response must not call AI extraction")


class FakeProducerAIClient:
    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        return LoadDataExtraction(
            raw_text=message_text,
            origin="Azul",
            destination="Liniers",
            livestock_type="novillos",
            quantity_estimate=35,
            contact="Juan",
            confidence="high",
            field_confidence={
                "origin": "provided",
                "destination": "provided",
                "date_window": "missing",
                "livestock_type": "provided",
                "quantity_estimate": "provided",
                "contact": "provided",
            },
        )


class FakeDraftAIClient:
    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        raise AIExtractionError("AI extraction client is not configured")


def build_carrier_orchestrator():
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    conversations: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipments: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    event_log = EventLogService()
    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(),
        conversation_sessions=conversations,
        messages=messages,
        shipment_requests=shipments,
        locations=InMemoryRepository[Location](),
        event_log=event_log,
        carriers=carriers,
        trip_offers=offers,
    )
    return orchestrator, carriers, shipments, offers, event_log


def test_whatsapp_carrier_route_capture_creates_scenario_scoped_availability():
    carriers = InMemoryRepository[Carrier]()
    conversations = InMemoryRepository[ConversationSession]()
    messages = InMemoryRepository[Message]()
    availabilities = InMemoryRepository[RouteAvailability]()
    events = EventLogService()
    carrier = Carrier(
        id="car_route_qa", name="Transportista QA", normalized_phone_number="+5491111111111",
        provider_name="kapso", provider_contact_id="contact_carrier_1",
        provider_conversation_id="conv_carrier_1", is_validated=True, validation_status="APPROVED",
    )
    carriers.add(carrier)
    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(), conversation_sessions=conversations, messages=messages,
        shipment_requests=InMemoryRepository[ShipmentRequest](), locations=InMemoryRepository[Location](),
        event_log=events, carriers=carriers, route_availabilities=availabilities,
        enable_test_role_switching=True,
    )

    def send(text: str, key: str):
        item = inbound(text, key)
        return orchestrator.handle_inbound_message(item)

    send("/test iniciar", "route_qa_start")
    send("/soy transportista", "route_qa_carrier")
    started = send("🛣️ Recorrido", "route_qa_menu_action")
    assert "localidad salís" in started.response_text
    send("Pergamino", "route_qa_origin")
    send("Rosario", "route_qa_destination")
    send("14/05/2026", "route_qa_date")
    send("Venado Tuerto", "route_qa_stops")
    send("25 cabezas", "route_qa_capacity")
    send("novillos", "route_qa_cargo")
    summary = send("jaula", "route_qa_equipment")
    assert "14/05/2026" in summary.response_text
    assert "responder 1 o 2" in summary.response_text
    assert {action.id for action in summary.actions} == {"confirmar_recorrido", "editar_recorrido"}
    saved = send("✅ Confirmar", "route_qa_confirm")

    assert "Recorrido registrado" in saved.response_text
    assert len(availabilities.list()) == 1
    availability = availabilities.list()[0]
    assert availability.route == ("Pergamino", "Venado Tuerto", "Rosario")
    assert availability.capacity_unit == "HEAD" and availability.capacity == Decimal("25")
    assert availability.cargo_types == ["novillos"]
    assert availability.status == "ACTIVE"
    assert availability.test_run_id == saved.conversation_session.active_test_run_id
    assert not saved.conversation_session.route_availability_capture
    assert any(event.event_type == "ROUTE_AVAILABILITY_CREATED" for event in events.events)


def build_orchestrator(ai_client=None):
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    conversations: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipments: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    event_log = EventLogService()
    orchestrator = ConversationOrchestrator(
        ai_client=ai_client or FakeAIClient(),
        conversation_sessions=conversations,
        messages=messages,
        shipment_requests=shipments,
        locations=InMemoryRepository[Location](),
        event_log=event_log,
        carriers=carriers,
        trip_offers=offers,
    )
    return orchestrator, carriers, conversations, messages, shipments, offers, event_log


def build_role_switch_orchestrator(ai_client=None, *, active_test_run_id: str | None = "qa_test_fixture"):
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    conversations: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipments: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    event_log = EventLogService()
    conversations.add(
        ConversationSession(
            id="cs_test_role",
            channel="kapso",
            external_conversation_id="conv_carrier_1",
            provider_name="kapso",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
            participant_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
            active_test_run_id=active_test_run_id,
        )
    )
    orchestrator = ConversationOrchestrator(
        ai_client=ai_client or FakeDraftAIClient(),
        conversation_sessions=conversations,
        messages=messages,
        shipment_requests=shipments,
        locations=InMemoryRepository[Location](),
        event_log=event_log,
        carriers=carriers,
        trip_offers=offers,
        enable_test_role_switching=True,
    )
    return orchestrator, carriers, conversations, messages, shipments, offers, event_log


def test_test_scenario_start_and_close_preserve_tagged_history() -> None:
    orchestrator, _, conversations, messages, _, _, event_log = build_role_switch_orchestrator(
        active_test_run_id=None
    )

    started = orchestrator.handle_inbound_message(inbound("/test iniciar", "evt_test_start"))
    run_id = started.conversation_session.active_test_run_id
    role = orchestrator.handle_inbound_message(inbound("/soy productor", "evt_test_role"))
    role_override = role.conversation_session.role_override
    closed = orchestrator.handle_inbound_message(inbound("/test cerrar", "evt_test_close"))
    after_close = orchestrator.handle_inbound_message(inbound("hola", "evt_after_test_close"))

    assert run_id and run_id.startswith("qa_")
    assert role_override == "Producer"
    assert closed.conversation_session.active_test_run_id is None
    assert after_close.message.test_run_id is None
    assert [message.test_run_id for message in messages.list()[:3]] == [run_id, run_id, run_id]
    assert conversations.get("cs_test_role").active_test_run_id is None  # type: ignore[union-attr]
    assert [event.event_type for event in event_log.events if event.test_run_id == run_id].count(
        "TEST_RUN_CLOSED"
    ) == 1


def test_unknown_declared_cargo_product_requires_human_review() -> None:
    orchestrator, *_ = build_role_switch_orchestrator()
    extraction = LoadDataExtraction(
        raw_text="Necesito transportar una carga especial",
        cargo_category="GRAIN",
        cargo_type="lentejas",
    )

    normalized = orchestrator._canonicalize_extraction(extraction, None)

    assert normalized.cargo_type == "lentejas"
    assert normalized.confidence == "unknown"
    assert normalized.field_confidence["cargo_type"] == "unknown"


def test_counted_livestock_implies_heads_even_if_ai_proposes_unit() -> None:
    class AIWithUnverifiedDefaultUnit:
        def extract_load_data(self, message_text: str) -> LoadDataExtraction:
            return LoadDataExtraction(
                raw_text=message_text,
                cargo_category="LIVESTOCK",
                cargo_type="novillos",
                livestock_type="novillos",
                quantity_estimate=Decimal("12"),
                quantity_unit="HEAD",
                origin="Azul",
                destination="Rosario",
                date_window_start=datetime(2026, 10, 13, 8, tzinfo=UTC),
                contact="QA",
                confidence="high",
            )

    orchestrator, _, _, _, shipments, _, _ = build_role_switch_orchestrator(
        ai_client=AIWithUnverifiedDefaultUnit()
    )
    orchestrator.handle_inbound_message(inbound("/soy productor", "evt_unit_role"))
    result = orchestrator.handle_inbound_message(
        inbound(
            "Necesito transportar 12 novillos desde Azul hasta Rosario el martes",
            "evt_unit_required",
        )
    )

    assert result.shipment_request is None
    assert "Cantidad: 12 cabezas" in (result.response_text or "")
    assert "¿Confirmás esta información?" in (result.response_text or "")
    assert shipments.list() == []


def test_internal_qa_marketplace_happy_path_with_producer_and_carrier_roles() -> None:
    """Exercise a full marketplace journey without Kapso, network, or persistent DB."""
    test_phone = "+5491111111111"
    conversations: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipments: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    locations: InMemoryRepository[Location] = InMemoryRepository()
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    assignments: InMemoryRepository[Assignment] = InMemoryRepository()
    trips: InMemoryRepository[Trip] = InMemoryRepository()
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    notifications = NotificationService(
        provider=provider,
        event_log=event_log,
        carriers=carriers,
        locations=locations,
    )
    carrier = carriers.add(
        Carrier(
            id="car_qa_internal",
            name="Transportista QA interno",
            contact_phone=test_phone,
            normalized_phone_number=test_phone,
            provider_name="kapso",
            provider_contact_id="contact_qa_internal",
            provider_conversation_id="conv_qa_internal",
            is_validated=True,
            validation_status="APPROVED",
        )
    )
    session = conversations.add(
        ConversationSession(
            id="cs_qa_internal",
            channel="kapso",
            provider_name="kapso",
            provider_contact_id="contact_qa_internal",
            provider_conversation_id="conv_qa_internal",
            participant_phone=test_phone,
            normalized_phone_number=test_phone,
            active_test_run_id=None,
            role_override="Producer",
        )
    )
    orchestrator = ConversationOrchestrator(
        ai_client=FakeDraftAIClient(),
        conversation_sessions=conversations,
        messages=messages,
        shipment_requests=shipments,
        locations=locations,
        event_log=event_log,
        carriers=carriers,
        trip_offers=offers,
        notification_service=notifications,
        enable_test_role_switching=True,
    )
    ops = AdminOpsService(
        shipment_requests=shipments,
        trip_offers=offers,
        assignments=assignments,
        trips=trips,
        carriers=carriers,
        locations=locations,
        conversation_sessions=conversations,
        messages=messages,
        event_log=event_log,
        notification_service=notifications,
        enable_test_role_switching=True,
    )

    started = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "/test iniciar",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_start",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    run_id = started.conversation_session.active_test_run_id
    assert run_id is not None and run_id.startswith("qa_")
    producer_role = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "/soy productor",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_producer_role",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert producer_role.conversation_session.role_override == "Producer"

    created = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "Necesito transportar 45 cabezas de novillos desde Mar del Plata hasta Rosario el viernes",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_load",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
            occurred_at=datetime(2026, 9, 29, 20, 55, tzinfo=UTC),
        )
    )
    assert created.shipment_request is None
    confirmed = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "confirmo",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_confirm",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
            occurred_at=datetime(2026, 9, 29, 20, 58, tzinfo=UTC),
        )
    )
    shipment = confirmed.shipment_request
    assert shipment is not None
    assert shipment.status == "PUBLISHED"
    assert shipment.test_run_id == run_id
    assert shipment.origin_location_id and locations.get(shipment.origin_location_id).original_text == "Mar del Plata"  # type: ignore[union-attr]
    resolved_origin = locations.get(shipment.origin_location_id)  # type: ignore[arg-type]
    assert resolved_origin is not None
    assert resolved_origin.georef_id == "06357110"
    assert resolved_origin.province == "Buenos Aires"
    assert resolved_origin.provenance == "GEOREF"
    assert resolved_origin.is_validated is False
    assert shipment.destination_location_id and locations.get(shipment.destination_location_id).original_text == "Rosario"  # type: ignore[union-attr]
    assert shipment.date_window_start is not None
    assert shipment.date_window_start.date() == date(2026, 10, 2)
    assert [message.test_run_id for message in messages.list()] == [run_id] * len(messages.list())

    producer_loads = ops.list_producer_shipments(phone_number=test_phone)
    assert len(producer_loads) == 1
    assert producer_loads[0].shipment_id == shipment.id
    producer_dashboard = ops.get_producer_dashboard(phone_number=test_phone)
    assert producer_dashboard.total_shipments == 1
    assert producer_dashboard.active_trips == 0

    sent_alert = next(
        event
        for event in event_log.events
        if event.event_type == "CARRIER_NOTIFICATION_SENT" and event.entity_id == shipment.id
    )
    outbound = provider.sent_messages[0]
    assert outbound.conversation_id == carrier.provider_conversation_id
    assert shipment.id in outbound.body
    assert [action.value for action in outbound.actions] == ["INTERESTED", "DECLINED", "MORE_INFO"]
    assert sent_alert.test_run_id == run_id
    assert outbound.metadata["interactive_delivery"] == "text_fallback"
    assert "1. Me interesa" in outbound.body
    assert "2. No puedo" in outbound.body
    assert "3. Más info" in outbound.body

    carrier_role = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "/soy transportista",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_carrier_role",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert carrier_role.conversation_session.role_override == "Carrier"
    carrier_response = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "Me interesa",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_interest",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert carrier_response.message.sender_type == "Carrier"
    assert carrier_response.trip_offer is not None
    assert carrier_response.trip_offer.response_type == "INTERESTED"
    assert carrier_response.trip_offer.test_run_id == run_id
    assert shipment.status == "MATCHING"

    producer_role_again = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "/soy productor",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_producer_role_again",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert producer_role_again.conversation_session.role_override == "Producer"
    interested = ops.list_producer_interested_offers(phone_number=test_phone)
    assert len(interested) == 1
    assert interested[0].trip_offer_id == carrier_response.trip_offer.id
    producer_dashboard = ops.get_producer_dashboard(phone_number=test_phone)
    assert producer_dashboard.pending_interested_offers == 1

    accepted = ops.accept_offer_by_producer(
        shipment_request_id=shipment.id,
        trip_offer_id=carrier_response.trip_offer.id,
        producer_phone_number=test_phone,
        idempotency_key="qa_internal_accept",
    )
    assert accepted.assignment.status == "CONFIRMED"
    assert accepted.trip.status == "PLANNED"
    assert accepted.assignment.test_run_id == run_id
    assert accepted.trip.test_run_id == run_id
    assert accepted.carrier_notification is not None
    assert accepted.carrier_notification.status == "sent"
    assert accepted.producer_notification is not None
    assert accepted.producer_notification.status == "sent"
    carrier_trip_notice, producer_trip_notice = provider.sent_messages[1:]
    assert "viaje" in carrier_trip_notice.body.lower()
    assert accepted.trip.id not in carrier_trip_notice.body
    assert accepted.trip.id in producer_trip_notice.body
    assert any(
        event.event_type == "CARRIER_NOTIFICATION_SENT"
        and event.entity_id == accepted.trip.id
        and event.payload.get("notification_type") == "TRIP_PLANNED"
        for event in accepted.events
    )
    assert any(
        event.event_type == "PRODUCER_NOTIFICATION_SENT"
        and event.entity_id == accepted.trip.id
        and event.payload.get("notification_type") == "TRIP_PLANNED"
        for event in accepted.events
    )
    sent_after_match = len(provider.sent_messages)
    duplicate_acceptance = ops.accept_offer_by_producer(
        shipment_request_id=shipment.id,
        trip_offer_id=carrier_response.trip_offer.id,
        producer_phone_number=test_phone,
        idempotency_key="qa_internal_accept",
    )
    assert duplicate_acceptance.assignment.id == accepted.assignment.id
    assert duplicate_acceptance.trip.id == accepted.trip.id
    assert len(provider.sent_messages) == sent_after_match

    producer_journey = ops.get_producer_dashboard(phone_number=test_phone)
    assert producer_journey.active_trips == 1
    assert producer_journey.current_operations[0].trip_id == accepted.trip.id
    assert producer_journey.current_operations[0].trip_status == "PLANNED"
    carrier_journey = ops.get_carrier_dashboard(carrier_id=carrier.id)
    assert carrier_journey.active_trips == 1
    assert carrier_journey.current_operations[0].trip_id == accepted.trip.id

    # Starting the trip sends the next lifecycle update to both participants.
    sent_before_trip_start = len(provider.sent_messages)
    token = current_test_run_id.set(session.active_test_run_id)
    try:
        started_trip = ops.start_trip(
            trip_id=accepted.trip.id,
            operator_user_id="qa_operator",
            idempotency_key="qa_internal_start_trip",
        )
    finally:
        current_test_run_id.reset(token)
    assert started_trip.trip.status == "LOADING_PENDING"
    assert started_trip.carrier_notification is not None
    assert started_trip.carrier_notification.status == "sent"
    assert started_trip.producer_notification is not None
    assert started_trip.producer_notification.status == "sent"
    assert len(provider.sent_messages) == sent_before_trip_start + 2
    assert any(event.event_type == "PRODUCER_NOTIFICATION_SENT" for event in started_trip.events)

    carrier_role_again = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "/soy transportista",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_carrier_role_again",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert carrier_role_again.conversation_session.role_override == "Carrier"

    def notify_carrier_for_qa_load(load: ShipmentRequest) -> None:
        token = current_test_run_id.set(run_id)
        try:
            notifications.send_new_load_alert(
                shipment=load,
                carrier_id=carrier.id,
                operator_user_id=None,
            )
        finally:
            current_test_run_id.reset(token)

    declined_load = ShipmentRequest(
        id="sr_qa_declined",
        test_run_id=run_id,
        producer_phone_number=test_phone,
        status="PUBLISHED",
        cargo_type="soja",
        cargo_category="GRAIN",
        quantity_unit="TON",
    )
    shipments.add(declined_load)
    locations.add(Location(id="loc_qa_rosario", original_text="Rosario", normalized_name="Rosario"))
    notify_carrier_for_qa_load(declined_load)
    declined = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "No puedo",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_declined",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert declined.trip_offer is not None
    assert declined.trip_offer.response_type == "DECLINED"
    assert declined.trip_offer.shipment_request_id == declined_load.id
    assert declined_load.status == "PUBLISHED"

    info_load = ShipmentRequest(
        id="sr_qa_more_info",
        test_run_id=run_id,
        producer_phone_number=test_phone,
        status="PUBLISHED",
        cargo_type="novillos",
        livestock_type="novillos",
        cargo_category="LIVESTOCK",
        quantity_estimate=Decimal("12"),
        quantity_unit="HEAD",
    )
    shipments.add(info_load)
    notify_carrier_for_qa_load(info_load)
    requested_info = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "Más info",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_more_info",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert requested_info.trip_offer is None
    assert requested_info.handoff_required is False
    assert "más info" in (requested_info.response_text or "").lower()
    assert not any(event.event_type == "CARRIER_RESPONSE_AMBIGUOUS" for event in requested_info.events)
    assert not any(event.event_type == "HUMAN_REVIEW_REQUESTED" for event in requested_info.events)

    availability = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "Estoy libre mañana por zona Azul, con jaula disponible",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_availability",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert availability.response_text == "Disponibilidad registrada. Un operador la revisa para futuras cargas."
    assert carrier.availability_notes == "Estoy libre mañana por zona Azul, con jaula disponible"
    assert len(offers.list()) == 2
    assert len(assignments.list()) == 1
    assert len(trips.list()) == 1
    assert all(message.test_run_id == run_id for message in messages.list())
    assert all(event.test_run_id == run_id for event in event_log.events)

    closed = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "/test cerrar",
            phone_number=test_phone,
            idempotency_key="evt_qa_internal_close",
            conversation_id="conv_qa_internal",
            provider_contact_id="contact_qa_internal",
        )
    )
    assert closed.conversation_session.active_test_run_id is None
    assert len(shipments.list()) == 3  # Closing a scenario preserves its QA data.


def inbound(text: str, idempotency_key: str = "evt_carrier_response") -> InboundConversationMessage:
    return InboundConversationMessage(
        provider="kapso",
        idempotency_key=idempotency_key,
        correlation_id="corr_1",
        conversation_id="conv_carrier_1",
        provider_contact_id="contact_carrier_1",
        provider_message_id=f"wamid_{idempotency_key}",
        phone_number="+5491111111111",
        occurred_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        text=text,
    )


def inbound_from_phone(
    text: str,
    *,
    phone_number: str,
    idempotency_key: str,
    correlation_id: str = "corr_1",
    conversation_id: str = "conv_1",
    provider_contact_id: str = "contact_1",
    occurred_at: datetime | None = None,
) -> InboundConversationMessage:
    return InboundConversationMessage(
        provider="kapso",
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        conversation_id=conversation_id,
        provider_contact_id=provider_contact_id,
        provider_message_id=f"wamid_{idempotency_key}",
        phone_number=phone_number,
        occurred_at=occurred_at or datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        text=text,
    )


def seed_carrier_alert(
    carriers,
    shipments,
    event_log,
    *,
    test_run_id: str | None = None,
) -> tuple[Carrier, ShipmentRequest]:
    carrier = carriers.add(
        Carrier(
            id="car_1",
            name="Carrier 1",
            normalized_phone_number="+5491111111111",
            provider_name="kapso",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )
    shipment = shipments.add(ShipmentRequest(id="sr_1", test_run_id=test_run_id, status="PUBLISHED"))
    event_log.record(
        event_type="CARRIER_NOTIFICATION_SENT",
        actor_type="SYSTEM",
        entity_type="ShipmentRequest",
        entity_id=shipment.id,
        summary="Notificacion enviada",
        related_entity_ids={"carrierId": carrier.id},
        payload={
            "carrier_id": carrier.id,
            "shipment_request_id": shipment.id,
            "destination": "conv_carrier_1",
        },
        source="mock_whatsapp",
        idempotency_key="notification_sent_1",
        test_run_id=test_run_id,
    )
    return carrier, shipment


def test_carrier_yes_creates_interested_trip_offer() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("1"))

    assert result.shipment_request == shipment
    assert result.message.sender_type == "Carrier"
    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "INTERESTED"
    assert len(offers.list()) == 1
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "CARRIER_INTERESTED",
        "LOAD_MATCHING_STARTED",
    ]
    assert shipment.status == "MATCHING"


@pytest.mark.parametrize(
    ("button_reply", "expected_type"),
    [("interested", "INTERESTED"), ("declined", "DECLINED"), ("more_info", "INFO_REQUEST")],
)
def test_carrier_interactive_provider_ids_are_recognized(
    button_reply: str,
    expected_type: str,
) -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound(button_reply, f"evt_button_{button_reply}"))

    assert result.shipment_request == shipment
    if expected_type == "INFO_REQUEST":
        assert result.trip_offer is None
    else:
        assert result.trip_offer is not None
        assert result.trip_offer.response_type == expected_type


def test_carrier_numeric_reply_maps_to_recent_interactive_action_context() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    carrier, shipment = seed_carrier_alert(carriers, shipments, event_log)
    event_log.events[-1].payload["interactive_actions"] = [
        {"id": "interested", "label": "Me interesa", "value": "INTERESTED", "kind": "quick_reply"},
        {"id": "declined", "label": "No puedo", "value": "DECLINED", "kind": "quick_reply"},
        {"id": "more_info", "label": "Más info", "value": "MORE_INFO", "kind": "quick_reply"},
    ]

    result = orchestrator.handle_inbound_message(inbound("1", "evt_interactive_context"))

    assert result.shipment_request == shipment
    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "INTERESTED"
    assert result.message.normalized_content == "INTERESTED"
    assert result.message.related_entity_ids["interactiveActionId"] == "interested"
    assert "INTERACTIVE_ACTION_SELECTED" in [event.event_type for event in result.events]
    assert result.events[1].payload == {
        "id": "interested",
        "value": "INTERESTED",
        "label": "Me interesa",
        "raw": {
            "id": "interested",
            "label": "Me interesa",
            "value": "INTERESTED",
            "kind": "quick_reply",
        },
    }
    assert len(offers.list()) == 1
    assert carrier.id == "car_1"


def test_first_interested_offer_moves_published_shipment_to_matching() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("1", "evt_first_interested_matching"))

    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "INTERESTED"
    assert shipments.get(shipment.id).status == "MATCHING"  # type: ignore[union-attr]
    matching_events = [
        event for event in event_log.events if event.event_type == "LOAD_MATCHING_STARTED"
    ]
    assert len(matching_events) == 1
    assert matching_events[0].previous_state == "PUBLISHED"
    assert matching_events[0].new_state == "MATCHING"
    assert matching_events[0].payload == {
        "shipment_request_id": shipment.id,
        "trigger": "carrier_interested",
        "trip_offer_id": result.trip_offer.id,
    }


def test_second_interested_response_from_same_carrier_does_not_duplicate_offer_or_matching_transition() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    first = orchestrator.handle_inbound_message(inbound("1", "evt_first_interested"))
    second = orchestrator.handle_inbound_message(inbound("1 me interesa", "evt_second_interested"))

    assert first.trip_offer is not None
    assert second.trip_offer is None
    assert second.response_text == "Ya había registrado tu interés por esta carga. El productor puede verlo y confirmar el viaje."
    assert len(offers.list()) == 1
    assert shipments.get(shipment.id).status == "MATCHING"  # type: ignore[union-attr]
    assert [event.event_type for event in event_log.events].count("CARRIER_INTERESTED") == 1
    assert [event.event_type for event in event_log.events].count("LOAD_MATCHING_STARTED") == 1


def test_declined_offer_does_not_move_published_shipment_to_matching() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("2", "evt_declined_no_matching"))

    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "DECLINED"
    assert result.response_text == "Anoté que no podés tomar esta carga. Gracias por responder."
    assert offers.list()[0].response_type == "DECLINED"
    assert shipments.get(shipment.id).status == "PUBLISHED"  # type: ignore[union-attr]
    assert [event.event_type for event in event_log.events].count("LOAD_MATCHING_STARTED") == 0


def test_carrier_general_availability_creates_availability_event_not_offer() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    carrier = carriers.add(
        Carrier(
            id="car_available",
            name="Carrier Disponible",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    result = orchestrator.handle_inbound_message(
        inbound("Estoy libre mañana por zona Azul", "evt_carrier_availability")
    )

    assert result.message.sender_type == "Carrier"
    assert result.trip_offer is None
    assert result.shipment_request is None
    assert result.handoff_required is False
    assert offers.list() == []
    assert shipments.list() == []
    stored_carrier = carriers.get(carrier.id)
    assert stored_carrier is not None
    assert stored_carrier.availability_notes == "Estoy libre mañana por zona Azul"
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "CARRIER_AVAILABILITY_REPORTED",
    ]
    availability_event = event_log.events[-1]
    assert availability_event.event_type == "CARRIER_AVAILABILITY_REPORTED"
    assert availability_event.entity_type == "Carrier"
    assert availability_event.entity_id == carrier.id
    assert availability_event.payload["text"] == "Estoy libre mañana por zona Azul"


def test_carrier_informar_disponibilidad_starts_structured_route_capture() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    carrier = carriers.add(
        Carrier(
            id="car_menu_availability",
            name="Carrier Menu Availability",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    response = orchestrator.handle_inbound_message(inbound("Informar disponibilidad", "evt_menu_availability"))

    assert response.message.sender_type == "Carrier"
    assert "¿Desde qué localidad salís?" in response.response_text
    assert response.conversation_session.route_availability_capture["step"] == "origin"
    assert carriers.get(carrier.id).availability_notes is None  # type: ignore[union-attr]
    assert shipments.list() == []
    assert offers.list() == []
    assert event_log.events[-1].event_type == "ROUTE_AVAILABILITY_CAPTURE_STARTED"


def test_test_role_switching_allows_registered_carrier_phone_to_act_as_producer() -> None:
    orchestrator, carriers, _, messages, shipments, offers, event_log = build_role_switch_orchestrator()
    carriers.add(
        Carrier(
            id="car_same_phone",
            name="Carrier Same Phone",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    switched = orchestrator.handle_inbound_message(inbound("iniciar sesion productor", "evt_role_producer"))
    first = orchestrator.handle_inbound_message(
        inbound(
            "Necesito camion para 30 toneladas de soja de Tandil a Rosario manana",
            "evt_role_producer_load",
        )
    )
    confirmed = orchestrator.handle_inbound_message(inbound("confirmo", "evt_role_producer_confirm"))

    assert switched.conversation_session.role_override == "Producer"
    assert first.message.sender_type == "Producer"
    assert confirmed.message.sender_type == "Producer"
    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.producer_phone_number == "+5491111111111"
    assert confirmed.shipment_request.cargo_category == "GRAIN"
    assert confirmed.shipment_request.cargo_type == "soja"
    assert confirmed.shipment_request.quantity_unit == "TON"
    assert confirmed.shipment_request.quantity_estimate == 30
    assert offers.list() == []
    assert len(shipments.list()) == 1
    assert [message.sender_type for message in messages.list()] == ["Producer", "Producer", "Producer"]
    assert "SESSION_ROLE_OVERRIDE_SET" in [event.event_type for event in event_log.events]
    assert "SHIPMENT_DRAFT_CREATED_FROM_CHAT" in [event.event_type for event in event_log.events]
    assert "LOAD_SELF_PUBLISHED" in [event.event_type for event in event_log.events]


def test_test_role_switching_slash_producer_command_allows_registered_carrier_phone() -> None:
    orchestrator, carriers, _, messages, shipments, offers, event_log = build_role_switch_orchestrator()
    carriers.add(
        Carrier(
            id="car_same_phone",
            name="Carrier Same Phone",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    switched = orchestrator.handle_inbound_message(inbound("/soy productor", "evt_slash_producer"))
    first = orchestrator.handle_inbound_message(
        inbound(
            "Necesito camion para 30 toneladas de soja de Tandil a Rosario manana",
            "evt_slash_producer_load",
        )
    )
    confirmed = orchestrator.handle_inbound_message(inbound("confirmo", "evt_slash_producer_confirm"))

    assert switched.conversation_session.role_override == "Producer"
    assert switched.response_text == "Modo de prueba activo: Productor."
    assert first.message.sender_type == "Producer"
    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.producer_phone_number == "+5491111111111"
    assert offers.list() == []
    assert len(shipments.list()) == 1
    assert [message.sender_type for message in messages.list()] == ["Producer", "Producer", "Producer"]
    assert event_log.events[1].event_type == "SESSION_ROLE_OVERRIDE_SET"


def test_test_role_switching_accepts_role_command_with_extra_text() -> None:
    orchestrator, carriers, _, _, _, offers, event_log = build_role_switch_orchestrator()
    carriers.add(
        Carrier(
            id="car_same_phone",
            name="Carrier Same Phone",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    switched = orchestrator.handle_inbound_message(
        inbound("iniciar sesion productor\ntext", "evt_role_producer_extra_text")
    )

    assert switched.conversation_session.role_override == "Producer"
    assert switched.message.sender_type == "Producer"
    assert switched.handoff_required is False
    assert offers.list() == []
    assert event_log.events[-1].event_type == "SESSION_ROLE_OVERRIDE_SET"


def test_test_role_switching_carrier_mode_creates_trip_offer() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_role_switch_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log, test_run_id="qa_test_fixture")

    switched = orchestrator.handle_inbound_message(inbound("iniciar sesión como transportista", "evt_role_carrier"))
    response = orchestrator.handle_inbound_message(inbound("1", "evt_role_carrier_yes"))

    assert switched.conversation_session.role_override == "Carrier"
    assert switched.events[-1].event_type == "SESSION_ROLE_OVERRIDE_SET"
    assert response.message.sender_type == "Carrier"
    assert response.shipment_request == shipment
    assert response.trip_offer is not None
    assert response.trip_offer.response_type == "INTERESTED"
    assert len(offers.list()) == 1


def test_test_role_switching_slash_carrier_mode_creates_trip_offer() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_role_switch_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log, test_run_id="qa_test_fixture")

    switched = orchestrator.handle_inbound_message(inbound("/soy transportista", "evt_slash_carrier"))
    response = orchestrator.handle_inbound_message(inbound("1", "evt_slash_carrier_yes"))

    assert switched.conversation_session.role_override == "Carrier"
    assert switched.response_text == "Modo de prueba activo: Transportista."
    assert response.message.sender_type == "Carrier"
    assert response.shipment_request == shipment
    assert response.trip_offer is not None
    assert response.trip_offer.response_type == "INTERESTED"
    assert len(offers.list()) == 1


def test_test_role_switching_operator_mode_routes_commands_without_offer() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_role_switch_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log, test_run_id="qa_test_fixture")

    switched = orchestrator.handle_inbound_message(inbound("iniciar sesion operador", "evt_role_operator"))
    command = orchestrator.handle_inbound_message(inbound("ver cargas", "evt_role_operator_ver_cargas"))

    assert switched.conversation_session.role_override == "Operator"
    assert command.message.sender_type == "Operator"
    assert command.trip_offer is None
    assert command.handoff_required is False
    assert offers.list() == []
    assert [event.event_type for event in command.events] == [
        "MESSAGE_RECEIVED",
        "OPERATOR_COMMAND_ROUTED_TO_KAPSO",
    ]


def test_test_role_switching_slash_operator_mode_routes_commands_without_offer() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_role_switch_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log, test_run_id="qa_test_fixture")

    switched = orchestrator.handle_inbound_message(inbound("/soy operador", "evt_slash_operator"))
    command = orchestrator.handle_inbound_message(inbound("ver cargas", "evt_slash_operator_ver_cargas"))

    assert switched.conversation_session.role_override == "Operator"
    assert switched.response_text == "Modo de prueba activo: Operador."
    assert command.message.sender_type == "Operator"
    assert command.trip_offer is None
    assert offers.list() == []


def test_test_role_switching_clear_returns_to_automatic_carrier_priority() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_role_switch_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log, test_run_id="qa_test_fixture")

    orchestrator.handle_inbound_message(inbound("iniciar sesion productor", "evt_role_clear_set"))
    cleared = orchestrator.handle_inbound_message(inbound("cerrar sesion", "evt_role_clear"))
    response = orchestrator.handle_inbound_message(inbound("1", "evt_role_clear_yes"))

    assert cleared.conversation_session.role_override is None
    assert response.message.sender_type == "Carrier"
    assert response.shipment_request == shipment
    assert response.trip_offer is not None
    assert len(offers.list()) == 1
    assert "SESSION_ROLE_OVERRIDE_CLEARED" in [event.event_type for event in event_log.events]


def test_test_role_switching_slash_reset_returns_to_automatic_carrier_priority() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_role_switch_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log, test_run_id="qa_test_fixture")

    orchestrator.handle_inbound_message(inbound("/soy productor", "evt_slash_reset_set"))
    cleared = orchestrator.handle_inbound_message(inbound("/reset", "evt_slash_reset"))
    response = orchestrator.handle_inbound_message(inbound("1", "evt_slash_reset_yes"))

    assert cleared.conversation_session.role_override is None
    assert cleared.response_text == "Modo automático activado."
    assert response.message.sender_type == "Carrier"
    assert response.shipment_request == shipment
    assert response.trip_offer is not None
    assert len(offers.list()) == 1
    assert "SESSION_ROLE_OVERRIDE_CLEARED" in [event.event_type for event in event_log.events]


def test_test_role_switching_status_reports_override_and_carrier_match() -> None:
    orchestrator, carriers, _, _, _, offers, event_log = build_role_switch_orchestrator()
    carriers.add(
        Carrier(
            id="car_same_phone",
            name="Carrier Same Phone",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    orchestrator.handle_inbound_message(inbound("/soy operador", "evt_slash_status_set"))
    status = orchestrator.handle_inbound_message(inbound("/estado sesion", "evt_slash_status"))

    assert status.conversation_session.role_override == "Operator"
    assert status.response_text == "\n".join(
        [
            "Modo actual: Operador",
            "Teléfono: +549***111",
            "Carrier detectado: car_same_phone",
        ]
    )
    assert status.trip_offer is None
    assert status.handoff_required is False
    assert offers.list() == []
    assert status.events[-1].event_type == "SESSION_ROLE_STATUS_REQUESTED"
    assert event_log.events[-1].payload == {
        "role_override": "Operator",
        "phone_number": "+549***111",
        "carrier_id": "car_same_phone",
    }


def test_role_switch_commands_are_ignored_when_disabled() -> None:
    orchestrator, carriers, _, _, shipments, offers, event_log = build_orchestrator(ai_client=FakeAIClient())
    seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("iniciar sesion productor", "evt_role_disabled"))

    assert result.message.sender_type == "Carrier"
    assert result.trip_offer is None
    assert result.handoff_required is True
    assert "SESSION_ROLE_OVERRIDE_SET" not in [event.event_type for event in event_log.events]
    assert offers.list() == []


def test_interested_offer_for_already_matching_shipment_does_not_repeat_transition() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    carrier = carriers.add(
        Carrier(
            id="car_1",
            name="Carrier 1",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )
    shipment = shipments.add(ShipmentRequest(id="sr_already_matching", status="MATCHING"))
    event_log.record(
        event_type="CARRIER_NOTIFICATION_SENT",
        actor_type="SYSTEM",
        entity_type="ShipmentRequest",
        entity_id=shipment.id,
        summary="Notificacion enviada",
        related_entity_ids={"carrierId": carrier.id},
        payload={
            "carrier_id": carrier.id,
            "shipment_request_id": shipment.id,
            "destination": "conv_carrier_1",
        },
        source="mock_whatsapp",
        idempotency_key="notification_already_matching",
    )

    result = orchestrator.handle_inbound_message(inbound("1", "evt_already_matching"))

    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "INTERESTED"
    assert len(offers.list()) == 1
    assert shipments.get(shipment.id).status == "MATCHING"  # type: ignore[union-attr]
    assert [event.event_type for event in event_log.events].count("LOAD_MATCHING_STARTED") == 0


def test_carrier_si_creates_interested_trip_offer() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("si", "evt_carrier_si"))

    assert result.shipment_request == shipment
    assert result.message.sender_type == "Carrier"
    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "INTERESTED"
    assert len(offers.list()) == 1
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "CARRIER_INTERESTED",
        "LOAD_MATCHING_STARTED",
    ]


def test_registered_carrier_phone_sets_sender_type_carrier_and_creates_trip_offer() -> None:
    orchestrator, carriers, _, messages, shipments, offers, _ = build_orchestrator()
    carriers.add(
        Carrier(
            id="car_phone_1",
            name="Carrier Phone",
            contact_phone="11 15 1111 1111",
            normalized_phone_number="+5491111111111",
        )
    )
    shipment = shipments.add(ShipmentRequest(id="sr_phone_1", status="PUBLISHED"))

    result = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "si",
            phone_number="+54 9 11 1111-1111",
            idempotency_key="evt_phone_carrier_yes",
            correlation_id="shipment:sr_phone_1:carrier:car_phone_1:NEW_LOAD_ALERT",
        )
    )

    assert result.message.sender_type == "Carrier"
    assert messages.list()[0].sender_type == "Carrier"
    assert result.shipment_request == shipment
    assert result.trip_offer is not None
    assert result.trip_offer.carrier_id == "car_phone_1"
    assert result.trip_offer.response_type == "INTERESTED"
    assert len(offers.list()) == 1


@pytest.mark.parametrize(
    ("inbound_phone", "idempotency_key"),
    [
        ("+5491135690073", "evt_phone_plus_549"),
        ("5491135690073", "evt_phone_549"),
        ("1135690073", "evt_phone_local_11"),
        ("541135690073", "evt_phone_without_mobile_9"),
    ],
)
def test_registered_carrier_phone_variants_match_carrier(inbound_phone: str, idempotency_key: str) -> None:
    orchestrator, carriers, _, messages, shipments, offers, _ = build_orchestrator()
    carriers.add(
        Carrier(
            id="car_real_phone",
            name="Carrier Real Phone",
            normalized_phone_number="+5491135690073",
        )
    )
    shipment = shipments.add(ShipmentRequest(id=f"sr_{idempotency_key}", status="PUBLISHED"))

    result = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "1",
            phone_number=inbound_phone,
            idempotency_key=idempotency_key,
            correlation_id=f"shipment:{shipment.id}:carrier:car_real_phone:NEW_LOAD_ALERT",
        )
    )

    assert result.message.sender_type == "Carrier"
    assert messages.list()[0].sender_type == "Carrier"
    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "INTERESTED"
    assert offers.list()[0].carrier_id == "car_real_phone"


def test_carrier_phone_lookup_logs_masked_values(caplog: pytest.LogCaptureFixture) -> None:
    orchestrator, carriers, _, _, shipments, _, _ = build_orchestrator()
    carriers.add(
        Carrier(
            id="car_real_phone",
            name="Carrier Real Phone",
            normalized_phone_number="+5491135690073",
        )
    )
    shipment = shipments.add(ShipmentRequest(id="sr_masked_lookup", status="PUBLISHED"))

    with caplog.at_level(logging.INFO, logger="app.application.conversation_orchestrator"):
        orchestrator.handle_inbound_message(
            inbound_from_phone(
                "1",
                phone_number="541135690073",
                idempotency_key="evt_masked_lookup",
                correlation_id=f"shipment:{shipment.id}:carrier:car_real_phone:NEW_LOAD_ALERT",
            )
        )

    assert "carrier_phone_lookup_attempt" in caplog.text
    assert "matched=true" in caplog.text
    assert "541***073" in caplog.text
    assert "541135690073" not in caplog.text
    assert "+5491135690073" not in caplog.text


def test_unregistered_carrier_phone_sets_sender_type_producer() -> None:
    orchestrator, _, _, messages, _, offers, _ = build_orchestrator(FakeProducerAIClient())

    result = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "35 cabezas de novillos de Azul a Liniers, Juan",
            phone_number="+5491199999999",
            idempotency_key="evt_producer_phone",
        )
    )

    assert result.message.sender_type == "Producer"
    assert messages.list()[0].sender_type == "Producer"
    assert result.shipment_request is None
    assert result.response_text is not None
    assert "fecha u horario" in result.response_text.lower()
    assert result.trip_offer is None
    assert offers.list() == []


def test_existing_producer_conversation_prioritizes_carrier_phone() -> None:
    orchestrator, carriers, conversations, messages, shipments, offers, _ = build_orchestrator()
    carriers.add(
        Carrier(
            id="car_shared_phone",
            name="Carrier Shared Phone",
            normalized_phone_number="+5491111111111",
        )
    )
    conversations.add(
        ConversationSession(
            id="conv_existing_producer",
            channel="kapso",
            external_conversation_id="producer_conv_1",
            provider_name="kapso",
            provider_contact_id="producer_contact_1",
            provider_conversation_id="producer_conv_1",
            participant_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
        )
    )
    messages.add(
        Message(
            conversation_session_id="conv_existing_producer",
            provider="kapso",
            direction="inbound",
            sender_type="Producer",
            message_type="text",
            idempotency_key="evt_original_producer",
            raw_content="Necesito una carga",
        )
    )
    shipment = shipments.add(ShipmentRequest(id="sr_shared_phone", status="PUBLISHED"))

    result = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "sí",
            phone_number="+5491111111111",
            idempotency_key="evt_shared_phone_carrier_yes",
            correlation_id="shipment:sr_shared_phone:carrier:car_shared_phone:NEW_LOAD_ALERT",
            conversation_id="producer_conv_1",
            provider_contact_id="producer_contact_1",
        )
    )

    assert result.conversation_session.id == "conv_existing_producer"
    assert result.message.sender_type == "Carrier"
    assert result.shipment_request == shipment
    assert result.trip_offer is not None
    assert result.trip_offer.carrier_id == "car_shared_phone"
    assert offers.list()[0].response_type == "INTERESTED"


def test_carrier_no_creates_declined_trip_offer() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("2", "evt_declined"))

    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "DECLINED"
    assert offers.list()[0].response_type == "DECLINED"
    assert result.events[-1].event_type == "CARRIER_DECLINED"


def test_carrier_no_puedo_creates_declined_trip_offer() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("no puedo", "evt_declined_text"))

    assert result.trip_offer is not None
    assert result.trip_offer.response_type == "DECLINED"
    assert offers.list()[0].response_type == "DECLINED"
    assert result.events[-1].event_type == "CARRIER_DECLINED"


def test_carrier_numeric_more_info_returns_load_details() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("3", "evt_numeric_more_info"))

    assert result.trip_offer is None
    assert offers.list() == []
    assert result.handoff_required is False
    assert result.shipment_request is not None
    assert result.shipment_request.id == "sr_1"
    assert "Carga recibida:" in (result.response_text or "")
    assert not any(event.event_type == "CARRIER_RESPONSE_AMBIGUOUS" for event in result.events)
    assert not any(event.event_type == "HUMAN_REVIEW_REQUESTED" for event in result.events)


def test_carrier_more_info_text_requests_human_review() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("cuanto pagan?", "evt_more_info_text"))

    assert result.trip_offer is None
    assert offers.list() == []
    assert result.handoff_required is True
    assert result.events[-2].event_type == "CARRIER_RESPONSE_AMBIGUOUS"
    assert result.events[-1].event_type == "HUMAN_REVIEW_REQUESTED"


def test_operator_command_from_registered_carrier_phone_is_not_carrier_ambiguous_response() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(
        inbound(
            "seleccionar oferta off_1 para carga sr_1",
            "evt_operator_command_same_phone",
        )
    )

    assert result.trip_offer is None
    assert offers.list() == []
    assert result.handoff_required is False
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "OPERATOR_COMMAND_ROUTED_TO_KAPSO",
    ]
    assert [event.event_type for event in event_log.events].count("CARRIER_RESPONSE_AMBIGUOUS") == 0
    assert [event.event_type for event in event_log.events].count("HUMAN_REVIEW_REQUESTED") == 0


def test_carrier_response_without_related_shipment_requests_handoff() -> None:
    orchestrator, carriers, _, offers, _ = build_carrier_orchestrator()
    carriers.add(
        Carrier(
            id="car_1",
            name="Carrier 1",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )

    result = orchestrator.handle_inbound_message(inbound("sí", "evt_no_shipment"))

    assert result.trip_offer is None
    assert offers.list() == []
    assert result.handoff_required is True
    assert result.events[-1].event_type == "HUMAN_REVIEW_REQUESTED"


def test_duplicate_carrier_response_does_not_duplicate_offer_or_events() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    seed_carrier_alert(carriers, shipments, event_log)
    message = inbound("me interesa", "evt_duplicate_carrier")

    first = orchestrator.handle_inbound_message(message)
    duplicate = orchestrator.handle_inbound_message(message)

    assert first.trip_offer is not None
    assert duplicate.trip_offer is None
    assert duplicate.events == ()
    assert len(offers.list()) == 1
    assert [event.event_type for event in event_log.events].count("CARRIER_INTERESTED") == 1


def test_carrier_response_uses_latest_active_notification_for_carrier() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    carrier = carriers.add(
        Carrier(
            id="car_1",
            name="Carrier 1",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )
    older = shipments.add(ShipmentRequest(id="sr_older", status="PUBLISHED"))
    closed = shipments.add(ShipmentRequest(id="sr_closed", status="CLOSED"))
    latest = shipments.add(ShipmentRequest(id="sr_latest", status="MATCHING"))
    for index, shipment in enumerate((older, closed, latest), start=1):
        event_log.record(
            event_type="CARRIER_NOTIFICATION_SENT",
            actor_type="SYSTEM",
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            summary="Notificacion enviada",
            related_entity_ids={"carrierId": carrier.id},
            payload={
                "carrier_id": carrier.id,
                "shipment_request_id": shipment.id,
                "destination": "conv_carrier_1",
            },
            source="mock_whatsapp",
            idempotency_key=f"notification_sent_{index}",
        )

    result = orchestrator.handle_inbound_message(
        inbound_from_phone(
            "1",
            phone_number="+5491111111111",
            idempotency_key="evt_latest_active_notification",
            correlation_id="corr_without_shipment_id",
            conversation_id="conv_carrier_1",
            provider_contact_id="contact_carrier_1",
        )
    )

    assert result.shipment_request == latest
    assert result.trip_offer is not None
    assert result.trip_offer.shipment_request_id == latest.id
    assert result.response_text == (
        'Recibido, marcamos tu interés por la última carga enviada (sr_latest). '
        'Si querías una anterior, respondé "me interesa sr_...".'
    )
    assert len(offers.list()) == 1


def test_carrier_response_with_explicit_shipment_id_overrides_latest_notification() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    carrier = carriers.add(
        Carrier(
            id="car_1",
            name="Carrier 1",
            normalized_phone_number="+5491111111111",
            provider_contact_id="contact_carrier_1",
            provider_conversation_id="conv_carrier_1",
        )
    )
    older = shipments.add(ShipmentRequest(id="sr_older", status="PUBLISHED"))
    latest = shipments.add(ShipmentRequest(id="sr_latest", status="PUBLISHED"))
    for index, shipment in enumerate((older, latest), start=1):
        event_log.record(
            event_type="CARRIER_NOTIFICATION_SENT",
            actor_type="SYSTEM",
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            summary="Notificacion enviada",
            related_entity_ids={"carrierId": carrier.id},
            payload={
                "carrier_id": carrier.id,
                "shipment_request_id": shipment.id,
                "destination": "conv_carrier_1",
            },
            source="mock_whatsapp",
            idempotency_key=f"notification_sent_explicit_{index}",
        )

    result = orchestrator.handle_inbound_message(
        inbound("me interesa sr_older", "evt_explicit_shipment_interest")
    )

    assert result.shipment_request == older
    assert result.trip_offer is not None
    assert result.trip_offer.shipment_request_id == older.id
    assert result.response_text == "Listo, registré tu interés. El productor puede verlo y confirmar el viaje."
    assert shipments.get(latest.id).status == "PUBLISHED"  # type: ignore[union-attr]
    assert len(offers.list()) == 1


def test_carrier_response_with_invalid_explicit_shipment_id_falls_back_to_latest_notification() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, latest = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(
        inbound("me interesa sr_inexistente", "evt_invalid_explicit_shipment_interest")
    )

    assert result.shipment_request == latest
    assert result.trip_offer is not None
    assert result.trip_offer.shipment_request_id == latest.id
    assert len(offers.list()) == 1


def test_carrier_single_active_notification_gets_interest_ack_without_disambiguation_hint() -> None:
    orchestrator, carriers, shipments, offers, event_log = build_carrier_orchestrator()
    _, shipment = seed_carrier_alert(carriers, shipments, event_log)

    result = orchestrator.handle_inbound_message(inbound("me interesa", "evt_single_notification_interest"))

    assert result.shipment_request == shipment
    assert result.trip_offer is not None
    assert result.response_text == "Listo, registré tu interés. El productor puede verlo y confirmar el viaje."
    assert len(offers.list()) == 1


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "carrier-responses.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("WHATSAPP_ALLOWLIST_SOURCE", "db_then_env")
    monkeypatch.setenv("WHATSAPP_ALLOWLIST_DEFAULT_ALLOW", "false")
    monkeypatch.setenv("WHATSAPP_DEV_ALLOWLIST", "+5491111111111,+5491135690073")
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


def test_sql_conversation_persists_route_capture_context(sql_runtime: sessionmaker[Session]) -> None:
    capture = {"step": "capacity", "test_run_id": "qa_sql_capture", "origin": "Pergamino"}
    with sql_runtime() as session:
        repo = SqlConversationSessionRepository(session)
        repo.add(ConversationSession(id="cs_sql_capture", channel="kapso", route_availability_capture=capture))
        session.commit()

    with sql_runtime() as session:
        restored = SqlConversationSessionRepository(session).get("cs_sql_capture")
        assert restored is not None
        assert restored.route_availability_capture == capture


def test_sql_webhook_persists_carrier_trip_offer_and_event_log(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        carrier = SqlCarrierRepository(session).add(
            Carrier(
                id="car_sql_1",
                name="Carrier SQL",
                normalized_phone_number="+5491111111111",
                provider_name="kapso",
                provider_contact_id="contact_sql_1",
                provider_conversation_id="conv_sql_1",
            )
        )
        shipment = SqlShipmentRequestRepository(session).add(ShipmentRequest(id="sr_sql_1", status="PUBLISHED"))
        SqlEventLogService(session).record(
            event_type="CARRIER_NOTIFICATION_SENT",
            actor_type="SYSTEM",
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            summary="Notificacion enviada",
            related_entity_ids={"carrierId": carrier.id},
            payload={
                "carrier_id": carrier.id,
                "shipment_request_id": shipment.id,
                "destination": "conv_sql_1",
            },
            source="mock_whatsapp",
            idempotency_key="sql_notification_sent_1",
        )
        session.commit()

    client = TestClient(app)
    payload = {
        "event_type": "message.received",
        "idempotency_key": "sql_carrier_yes",
        "provider_message_id": "wamid_sql_carrier_yes",
        "provider_contact_id": "contact_sql_1",
        "conversation_id": "conv_sql_1",
        "phone_number": "+5491111111111",
        "payload": {"text": "lo hago"},
    }
    raw = __import__("json").dumps(payload).encode()
    import hashlib
    import hmac

    secret = get_settings().kapso_webhook_secret
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    response = client.post(
        "/api/v1/webhooks/kapso",
        content=raw,
        headers={"X-Webhook-Signature": f"sha256={signature}"},
    )

    assert response.status_code == 200
    with sql_runtime() as session:
        offers = session.scalars(select(TripOfferRecord)).all()
        stored_shipment = session.get(ShipmentRequestRecord, "sr_sql_1")
        event_types = [event.event_type for event in session.scalars(select(EventLogRecord)).all()]

    assert len(offers) == 1
    assert offers[0].response_type == "INTERESTED"
    assert stored_shipment is not None
    assert stored_shipment.status == "MATCHING"
    assert "CARRIER_INTERESTED" in event_types
    assert event_types.count("LOAD_MATCHING_STARTED") == 1


def test_sql_meta_webhook_phone_without_mobile_9_matches_carrier_and_persists_offer(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        carrier = SqlCarrierRepository(session).add(
            Carrier(
                id="car_sql_real_phone",
                name="Carrier SQL Real Phone",
                normalized_phone_number="+5491135690073",
                provider_name="kapso",
            )
        )
        shipment = SqlShipmentRequestRepository(session).add(ShipmentRequest(id="sr_sql_real_phone", status="PUBLISHED"))
        SqlEventLogService(session).record(
            event_type="CARRIER_NOTIFICATION_SENT",
            actor_type="SYSTEM",
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            summary="Notificacion enviada",
            related_entity_ids={"carrierId": carrier.id},
            payload={
                "carrier_id": carrier.id,
                "shipment_request_id": shipment.id,
                "destination": "+5491135690073",
            },
            source="mock_whatsapp",
            idempotency_key="sql_real_phone_notification_sent_1",
        )
        session.commit()

    client = TestClient(app)
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "541135690073"}],
                            "messages": [
                                {
                                    "id": "wamid_sql_real_phone_yes",
                                    "from": "541135690073",
                                    "timestamp": "1770000000",
                                    "text": {"body": "1"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    raw = __import__("json").dumps(payload).encode()
    import hashlib
    import hmac

    secret = get_settings().kapso_webhook_secret
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    response = client.post(
        "/api/v1/webhooks/kapso",
        content=raw,
        headers={
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Event": "message.received",
            "X-Idempotency-Key": "sql_real_phone_carrier_yes",
        },
    )

    assert response.status_code == 200
    with sql_runtime() as session:
        messages = session.scalars(select(models.MessageRecord)).all()
        offers = session.scalars(select(TripOfferRecord)).all()
        event_types = [event.event_type for event in session.scalars(select(EventLogRecord)).all()]
        outbox = session.scalars(select(NotificationOutboxRecord)).all()

    inbound_messages = [message for message in messages if message.direction == "inbound"]
    outbound_messages = [message for message in messages if message.direction == "outbound"]
    assert inbound_messages[-1].sender_type == "Carrier"
    assert outbound_messages == []
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"
    assert "CONVERSATION_REPLY_QUEUED" in event_types
    assert len(offers) == 1
    assert offers[0].carrier_id == carrier.id
    assert offers[0].response_type == "INTERESTED"
    assert "CARRIER_INTERESTED" in event_types
    assert event_types.count("LOAD_MATCHING_STARTED") == 1
