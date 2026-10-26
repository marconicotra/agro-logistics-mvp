from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.application.ai import AIExtractionError, LoadDataExtraction
from app.application.conversation_orchestrator import (
    ConversationOrchestrator,
    InboundConversationMessage,
)
from app.domain.events import EventLogService
from app.domain.models import Carrier, ConversationSession, Location, Message, ShipmentRequest, TripOffer
from app.infrastructure.repositories.memory import InMemoryRepository


class FakeAIClient:
    def __init__(self, extraction: LoadDataExtraction | None = None, error: Exception | None = None) -> None:
        self.extraction = extraction
        self.error = error

    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        if self.error:
            raise self.error
        assert self.extraction is not None
        return self.extraction


class RecordingNotificationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def send_new_load_alerts(
        self,
        *,
        shipment: ShipmentRequest,
        carrier_ids: list[str],
        operator_user_id: str | None,
    ) -> tuple[object, ...]:
        self.calls.append((shipment.id, list(carrier_ids)))
        return ()


def build_orchestrator(ai_client: FakeAIClient) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        ai_client=ai_client,
        conversation_sessions=InMemoryRepository[ConversationSession](),
        messages=InMemoryRepository[Message](),
        shipment_requests=InMemoryRepository[ShipmentRequest](),
        locations=InMemoryRepository[Location](),
        event_log=EventLogService(),
    )


def inbound_message(text: str, idempotency_key: str = "evt_1") -> InboundConversationMessage:
    return InboundConversationMessage(
        provider="kapso",
        conversation_id="conv_1",
        workflow_execution_id="wf_1",
        provider_message_id="wamid_1",
        phone_number="+5491111111111",
        idempotency_key=idempotency_key,
        correlation_id="corr_1",
        occurred_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        text=text,
    )


def test_inbound_message_prepares_incomplete_load_preview_without_persisting_load() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(
            LoadDataExtraction(
                raw_text="Necesito camion desde Rauch para 35 cabezas de novillos",
                origin="Rauch",
                livestock_type="novillos",
                quantity_estimate=Decimal("35"),
                confidence="medium",
                field_confidence={
                    "origin": "provided",
                    "livestock_type": "provided",
                    "quantity_estimate": "estimated",
                },
            )
        )
    )

    result = orchestrator.handle_inbound_message(
        inbound_message("Necesito camion desde Rauch para 35 cabezas de novillos")
    )

    assert result.conversation_session.channel == "kapso"
    assert result.conversation_session.external_conversation_id == "conv_1"
    assert result.message.raw_content == "Necesito camion desde Rauch para 35 cabezas de novillos"
    assert result.shipment_request is None
    assert orchestrator._shipment_requests.list() == []
    assert result.response_text is not None
    assert "destino" in result.response_text
    assert [event.payload["missing_fields"] for event in result.events if event.event_type == "LOAD_PREVIEW_PREPARED"] == [
        ["destination", "date_window"]
    ]
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED", "LOAD_PREVIEW_PREPARED", "HUMAN_REVIEW_REQUESTED"
    ]


def test_complete_extraction_prepares_canonical_confirmation_preview() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(
            LoadDataExtraction(
                raw_text="Miercoles 35 cabezas de terneros de Azul a Liniers, hablar con Juan",
                origin="Azul",
                destination="Liniers",
                date_window_start=datetime(2026, 4, 29, 8, 0, tzinfo=UTC),
                livestock_type="terneros",
                quantity_estimate=Decimal("35"),
                contact="Juan +5492222222222",
                confidence="high",
                field_confidence={
                    "origin": "provided",
                    "destination": "provided",
                    "date_window": "provided",
                    "livestock_type": "provided",
                    "quantity_estimate": "provided",
                    "contact": "provided",
                },
            )
        )
    )

    result = orchestrator.handle_inbound_message(
        inbound_message("Miercoles 35 cabezas de terneros de Azul a Liniers, hablar con Juan")
    )

    assert result.shipment_request is None
    assert result.handoff_required is False
    assert result.response_text is not None
    assert "29/04/2026" in result.response_text
    assert "¿Confirmás esta información?" in result.response_text
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "LOAD_PREVIEW_PREPARED",
    ]


def test_grain_preview_asks_for_missing_unit_even_if_ai_guesses_tons() -> None:
    text = "Necesito transportar 30 de soja desde Tandil hasta Rosario mañana"
    orchestrator = build_orchestrator(
        FakeAIClient(
            LoadDataExtraction(
                raw_text=text,
                cargo_category="GRAIN",
                cargo_type="soja",
                quantity_unit="TON",
                origin="Tandil",
                destination="Rosario",
                date_window_start=datetime(2026, 4, 26, 8, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
                quantity_estimate=Decimal("30"),
                confidence="high",
            )
        )
    )

    result = orchestrator.handle_inbound_message(inbound_message(text))

    preview = next(event for event in result.events if event.event_type == "LOAD_PREVIEW_PREPARED")
    assert preview.payload["quantity_unit"] is None
    assert preview.payload["missing_fields"] == ["quantity_unit"]
    assert result.response_text is not None
    assert "unidad de cantidad" in result.response_text


def test_confirmation_does_not_create_grain_load_without_explicit_unit() -> None:
    text = "Necesito transportar 30 de soja desde Tandil hasta Rosario mañana"
    orchestrator = build_orchestrator(
        FakeAIClient(
            LoadDataExtraction(
                raw_text=text,
                cargo_category="GRAIN",
                cargo_type="soja",
                quantity_unit="TON",
                origin="Tandil",
                destination="Rosario",
                date_window_start=datetime(2026, 4, 26, 8, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
                quantity_estimate=Decimal("30"),
                confidence="high",
            )
        )
    )
    orchestrator.handle_inbound_message(inbound_message(text))
    confirmation = replace(
        inbound_message("confirmo", "evt_2"),
        provider_message_id="wamid_2",
    )

    result = orchestrator.handle_inbound_message(confirmation)

    assert orchestrator._shipment_requests.list() == []
    assert result.shipment_request is None
    assert result.response_text is not None
    assert "unidad de cantidad" in result.response_text


def test_standalone_unit_reply_is_treated_as_load_update() -> None:
    orchestrator = build_orchestrator(FakeAIClient(LoadDataExtraction(raw_text="toneladas")))

    assert orchestrator._looks_like_partial_chat_shipment_update("toneladas") is True


def test_low_confidence_or_ambiguous_location_requests_human_review() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(
            LoadDataExtraction(
                raw_text="Del campo de siempre al remate",
                origin="campo de siempre",
                destination="remate",
                date_window_start=datetime(2026, 4, 29, 8, 0, tzinfo=UTC),
                livestock_type="vacas",
                quantity_estimate=Decimal("20"),
                contact="Pedro",
                confidence="low",
                has_ambiguous_location=True,
            )
        )
    )

    result = orchestrator.handle_inbound_message(inbound_message("Del campo de siempre al remate"))

    assert result.shipment_request is None
    assert result.handoff_required is True
    assert result.events[-1].event_type == "HUMAN_REVIEW_REQUESTED"
    assert "Ubicacion ambigua" in result.events[-1].payload["reason"]


def test_ai_failure_keeps_message_and_requests_human_review() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI provider unavailable"))
    )

    result = orchestrator.handle_inbound_message(inbound_message("Necesito camion para manana"))

    assert result.shipment_request is None
    assert result.message.id.startswith("msg_")
    assert result.handoff_required is True
    assert result.response_text == "Recibimos el mensaje. Un operador lo revisa para continuar."
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "HUMAN_REVIEW_REQUESTED",
    ]


def test_confirmation_creates_chat_draft_from_previous_load_message_when_ai_is_unconfigured() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI provider unavailable"))
    )

    first = orchestrator.handle_inbound_message(
        inbound_message(
            "Hola, Necesito camión para 71 cabezas de vacas de Tandil a Cañuelas mañana, 250 kilos cada una",
            idempotency_key="evt_load_71",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("confirmar", idempotency_key="evt_confirm_71")
    )

    assert first.shipment_request is None
    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.livestock_type == "vacas"
    assert confirmed.shipment_request.quantity_estimate == Decimal("71")
    assert confirmed.shipment_request.operational_notes == (
        "Hola, Necesito camión para 71 cabezas de vacas de Tandil a Cañuelas mañana, 250 kilos cada una"
    )
    assert [event.event_type for event in confirmed.events] == [
        "MESSAGE_RECEIVED",
        "SHIPMENT_DRAFT_CREATED_FROM_CHAT",
        "LOAD_SELF_PUBLISHED",
        "BROADCAST_SENT",
    ]
    assert confirmed.events[1].payload["trigger"] == "producer_confirmation"
    assert confirmed.events[3].payload["trigger"] == "producer_self_publish"


def test_confirmation_persists_relative_weekday_using_argentina_calendar_date() -> None:
    buenos_aires = ZoneInfo("America/Argentina/Buenos_Aires")
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI provider unavailable"))
    )
    original_request = InboundConversationMessage(
        **{
            **inbound_message(
                "Necesito transportar 45 cabezas de novillos desde Mar del Plata hasta Rosario el viernes",
                idempotency_key="evt_load_friday",
            ).__dict__,
            "occurred_at": datetime(2026, 9, 29, 20, 55, tzinfo=UTC),
        }
    )
    confirmation = InboundConversationMessage(
        **{
            **inbound_message("confirmo", idempotency_key="evt_confirm_friday").__dict__,
            "occurred_at": datetime(2026, 9, 29, 23, 58, tzinfo=UTC),
        }
    )

    orchestrator.handle_inbound_message(original_request)
    confirmed = orchestrator.handle_inbound_message(confirmation)

    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.origin_location_id is not None
    assert confirmed.shipment_request.destination_location_id is not None
    assert confirmed.shipment_request.date_window_start == datetime(
        2026, 10, 2, 8, 0, tzinfo=buenos_aires
    )


def test_repeated_confirmation_does_not_create_duplicate_chat_draft() -> None:
    conversation_sessions: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipment_requests: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    locations: InMemoryRepository[Location] = InMemoryRepository()
    event_log = EventLogService()
    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(error=AIExtractionError("AI provider unavailable")),
        conversation_sessions=conversation_sessions,
        messages=messages,
        shipment_requests=shipment_requests,
        locations=locations,
        event_log=event_log,
    )

    orchestrator.handle_inbound_message(
        inbound_message(
            "Necesito camión para 72 cabezas de vacas de Tandil a Cañuelas mañana",
            idempotency_key="evt_load_72",
        )
    )
    first_confirmation = orchestrator.handle_inbound_message(
        inbound_message("confirmar", idempotency_key="evt_confirm_72_a")
    )
    second_confirmation = orchestrator.handle_inbound_message(
        inbound_message("confirmar", idempotency_key="evt_confirm_72_b")
    )

    assert first_confirmation.shipment_request is not None
    assert second_confirmation.shipment_request is not None
    assert first_confirmation.shipment_request.id == second_confirmation.shipment_request.id
    assert len(shipment_requests.list()) == 1
    assert [
        event.event_type
        for event in event_log.events
        if event.event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"
    ] == ["SHIPMENT_DRAFT_CREATED_FROM_CHAT"]


def test_multiturn_confirmation_creates_chat_draft_from_accumulated_messages() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI extraction client is not configured"))
    )

    orchestrator.handle_inbound_message(
        inbound_message("1", idempotency_key="evt_turn_1")
    )
    orchestrator.handle_inbound_message(
        inbound_message("son 50 cabezas de vacas", idempotency_key="evt_turn_2")
    )
    orchestrator.handle_inbound_message(
        inbound_message(
            "Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio",
            idempotency_key="evt_turn_3",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("confirmo", idempotency_key="evt_turn_4")
    )

    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.livestock_type == "vacas"
    assert confirmed.shipment_request.quantity_estimate == Decimal("50")
    assert confirmed.shipment_request.date_window_start == datetime(
        2026, 6, 15, 8, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
    )
    assert confirmed.shipment_request.operational_notes == (
        "son 50 cabezas de vacas Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio"
    )
    assert confirmed.events[1].event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"


def test_multiturn_confirmation_accepts_si_confirmalo_phrase() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI extraction client is not configured"))
    )

    orchestrator.handle_inbound_message(
        inbound_message(
            "quiero crear una carga, necesito transportar 40 cabezas de vacas de santa fe a cordoba, para el 11 de septiembre",
            idempotency_key="evt_si_confirmalo_1",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("si confirmalo", idempotency_key="evt_si_confirmalo_2")
    )

    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.livestock_type == "vacas"
    assert confirmed.shipment_request.quantity_estimate == Decimal("40")
    assert confirmed.shipment_request.origin_location_id is not None
    assert confirmed.shipment_request.destination_location_id is not None
    assert confirmed.events[1].event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"


def test_multiturn_confirmation_keeps_only_latest_consistent_load_context_in_notes() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI extraction client is not configured"))
    )

    orchestrator.handle_inbound_message(
        inbound_message(
            "Necesito llevar 3 toneladas de soja de buenos aires a cordoba el 20 de junio",
            idempotency_key="evt_notes_1",
        )
    )
    orchestrator.handle_inbound_message(
        inbound_message(
            "quiero cargar 5 toneladas de soja desde santa fe a misiones el 25 de junio",
            idempotency_key="evt_notes_2",
        )
    )
    orchestrator.handle_inbound_message(
        inbound_message("perdon el 25 de julio", idempotency_key="evt_notes_3")
    )
    orchestrator.handle_inbound_message(
        inbound_message("1", idempotency_key="evt_notes_4")
    )
    orchestrator.handle_inbound_message(
        inbound_message(
            "quiero cargar 13 toneladas de soja desde santa fe a misiones el 10 de agosto",
            idempotency_key="evt_notes_5",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("confirmo", idempotency_key="evt_notes_6")
    )

    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.quantity_estimate == Decimal("13")
    assert confirmed.shipment_request.operational_notes == (
        "quiero cargar 13 toneladas de soja desde santa fe a misiones el 10 de agosto"
    )


def test_known_carrier_can_still_create_load_when_messages_look_like_producer_flow() -> None:
    conversation_sessions: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipment_requests: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    trip_offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    locations: InMemoryRepository[Location] = InMemoryRepository()
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    event_log = EventLogService()
    carriers.add(
        Carrier(
            id="car_known_contact",
            name="Known Contact",
            contact_phone="+5491111111111",
            normalized_phone_number="+541111111111",
        )
    )
    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(error=AIExtractionError("AI extraction client is not configured")),
        conversation_sessions=conversation_sessions,
        messages=messages,
        shipment_requests=shipment_requests,
        locations=locations,
        event_log=event_log,
        carriers=carriers,
        trip_offers=trip_offers,
    )

    orchestrator.handle_inbound_message(
        inbound_message("son 50 cabezas de vacas", idempotency_key="evt_carrier_as_producer_1")
    )
    orchestrator.handle_inbound_message(
        inbound_message(
            "Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio",
            idempotency_key="evt_carrier_as_producer_2",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("1", idempotency_key="evt_carrier_as_producer_3")
    )

    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.livestock_type == "vacas"
    assert confirmed.shipment_request.quantity_estimate == Decimal("50")
    assert [
        message.sender_type
        for message in sorted(messages.list(), key=lambda item: item.created_at)
    ] == ["Producer", "Producer", "Producer"]


def test_known_carrier_with_active_notified_load_can_start_new_producer_flow_from_menu() -> None:
    conversation_sessions: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipment_requests: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    trip_offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    locations: InMemoryRepository[Location] = InMemoryRepository()
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    event_log = EventLogService()

    carrier = carriers.add(
        Carrier(
            id="car_dual_role",
            name="Dual Role Contact",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
            provider_name="kapso",
        )
    )
    existing_shipment = shipment_requests.add(ShipmentRequest(id="sr_existing_notified", status="MATCHING"))
    event_log.record(
        event_type="CARRIER_NOTIFICATION_SENT",
        actor_type="SYSTEM",
        actor_id="system",
        entity_type="ShipmentRequest",
        entity_id=existing_shipment.id,
        summary="Carga notificada al transportista",
        related_entity_ids={"carrierId": carrier.id},
        payload={
            "carrier_id": carrier.id,
            "shipment_request_id": existing_shipment.id,
            "destination": "+5491111111111",
        },
        source="kapso",
        idempotency_key="evt_dual_role_notification",
    )

    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(error=AIExtractionError("AI extraction client is not configured")),
        conversation_sessions=conversation_sessions,
        messages=messages,
        shipment_requests=shipment_requests,
        locations=locations,
        event_log=event_log,
        carriers=carriers,
        trip_offers=trip_offers,
    )

    greeted = orchestrator.handle_inbound_message(
        inbound_message("hola", idempotency_key="evt_dual_role_hola")
    )
    menu_choice = orchestrator.handle_inbound_message(
        inbound_message("1", idempotency_key="evt_dual_role_menu_1")
    )
    detail_1 = orchestrator.handle_inbound_message(
        inbound_message("son 50 cabezas de vacas", idempotency_key="evt_dual_role_detail_1")
    )
    detail_2 = orchestrator.handle_inbound_message(
        inbound_message(
            "Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio",
            idempotency_key="evt_dual_role_detail_2",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("confirmo", idempotency_key="evt_dual_role_confirm")
    )

    assert greeted.message.sender_type == "Producer"
    assert menu_choice.message.sender_type == "Producer"
    assert detail_1.message.sender_type == "Producer"
    assert detail_2.message.sender_type == "Producer"
    assert confirmed.message.sender_type == "Producer"
    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.id != existing_shipment.id
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert confirmed.shipment_request.livestock_type == "vacas"
    assert confirmed.shipment_request.quantity_estimate == Decimal("50")
    assert confirmed.shipment_request.producer_phone_number == "+5491111111111"
    assert "SHIPMENT_DRAFT_CREATED_FROM_CHAT" in [event.event_type for event in confirmed.events]
    assert "LOAD_SELF_PUBLISHED" in [event.event_type for event in confirmed.events]


def test_self_publish_only_targets_validated_carriers() -> None:
    conversation_sessions: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipment_requests: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    locations: InMemoryRepository[Location] = InMemoryRepository()
    carriers: InMemoryRepository[Carrier] = InMemoryRepository()
    event_log = EventLogService()
    notifications = RecordingNotificationService()
    carriers.add(
        Carrier(
            id="car_validated",
            name="Validated Carrier",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
            is_validated=True,
        )
    )
    carriers.add(
        Carrier(
            id="car_pending",
            name="Pending Carrier",
            contact_phone="+5492222222222",
            normalized_phone_number="+5492222222222",
            is_validated=False,
        )
    )
    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(error=AIExtractionError("AI extraction client is not configured")),
        conversation_sessions=conversation_sessions,
        messages=messages,
        shipment_requests=shipment_requests,
        locations=locations,
        event_log=event_log,
        carriers=carriers,
        notification_service=notifications,
    )

    orchestrator.handle_inbound_message(
        inbound_message(
            "Necesito llevar 50 cabezas de vacas desde cordoba capital a buenos aires el 15 de julio",
            idempotency_key="evt_validated_only_1",
        )
    )
    confirmed = orchestrator.handle_inbound_message(
        inbound_message("confirmo", idempotency_key="evt_validated_only_2")
    )

    assert confirmed.shipment_request is not None
    assert confirmed.shipment_request.status == "PUBLISHED"
    assert notifications.calls == [(confirmed.shipment_request.id, ["car_validated"])]
    broadcast_event = next(event for event in confirmed.events if event.event_type == "BROADCAST_SENT")
    assert broadcast_event.payload["carrier_ids"] == ["car_validated"]
    notified_events = [event for event in confirmed.events if event.event_type == "CARRIER_NOTIFIED"]
    assert [event.related_entity_ids["carrierId"] for event in notified_events] == ["car_validated"]


def test_confirmation_without_previous_load_still_requests_human_review_on_ai_failure() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(error=AIExtractionError("AI provider unavailable"))
    )

    result = orchestrator.handle_inbound_message(inbound_message("confirmar"))

    assert result.shipment_request is None
    assert result.handoff_required is True
    assert [event.event_type for event in result.events] == [
        "MESSAGE_RECEIVED",
        "HUMAN_REVIEW_REQUESTED",
    ]


def test_duplicate_message_idempotency_does_not_create_second_message_or_load() -> None:
    orchestrator = build_orchestrator(
        FakeAIClient(
            LoadDataExtraction(
                raw_text="35 cabezas de novillos de Tandil a Cañuelas el viernes, llama Ana",
                origin="Tandil",
                destination="Cañuelas",
                date_window_start=datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
                livestock_type="novillos",
                quantity_estimate=Decimal("35"),
                contact="Ana",
                confidence="high",
            )
        )
    )

    first = orchestrator.handle_inbound_message(
        inbound_message("35 cabezas de novillos de Tandil a Cañuelas el viernes, llama Ana")
    )
    duplicate = orchestrator.handle_inbound_message(
        inbound_message("35 cabezas de novillos de Tandil a Cañuelas el viernes, llama Ana")
    )

    assert duplicate.message.id == first.message.id
    assert duplicate.shipment_request is None
    assert duplicate.events == ()


def test_duplicate_message_does_not_duplicate_repositories_or_event_log() -> None:
    conversation_sessions: InMemoryRepository[ConversationSession] = InMemoryRepository()
    messages: InMemoryRepository[Message] = InMemoryRepository()
    shipment_requests: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    trip_offers: InMemoryRepository[TripOffer] = InMemoryRepository()
    locations: InMemoryRepository[Location] = InMemoryRepository()
    event_log = EventLogService()
    orchestrator = ConversationOrchestrator(
        ai_client=FakeAIClient(
            LoadDataExtraction(
                raw_text="40 cabezas de vacas de Balcarce a Saladillo mañana, hablar con Luis",
                origin="Balcarce",
                destination="Saladillo",
                date_window_start=datetime(2026, 5, 2, 8, 0, tzinfo=UTC),
                livestock_type="vacas",
                quantity_estimate=Decimal("40"),
                contact="Luis",
                confidence="high",
            )
        ),
        conversation_sessions=conversation_sessions,
        messages=messages,
        shipment_requests=shipment_requests,
        trip_offers=trip_offers,
        locations=locations,
        event_log=event_log,
    )
    inbound = inbound_message(
        "40 cabezas de vacas de Balcarce a Saladillo mañana, hablar con Luis",
        idempotency_key="evt_duplicate_whatsapp",
    )

    orchestrator.handle_inbound_message(inbound)
    orchestrator.handle_inbound_message(inbound)

    assert len(conversation_sessions.list()) == 1
    assert len(messages.list()) == 1
    assert len(shipment_requests.list()) == 0
    assert [event.event_type for event in event_log.events] == [
        "MESSAGE_RECEIVED",
        "LOAD_PREVIEW_PREPARED",
    ]
