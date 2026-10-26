from collections.abc import Iterator
from datetime import UTC, datetime
import json

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_whatsapp_provider, reset_app_state
from app.application.contact_mapping import normalize_phone_number
from app.application.notifications import NotificationService
from app.core.config import get_settings
from app.domain.events import EventLogService
from app.domain.models import Carrier, ConversationSession, Location, Message, ShipmentRequest
from app.infrastructure.adapters.kapso import KapsoProvider
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import EventLogRecord, NotificationOutboxRecord
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlShipmentRequestRepository
from app.infrastructure.db.session import get_engine, get_session_factory
from app.main import app


OPERATOR_HEADERS = {"x-operator-user-id": "user_operator", "x-operator-role": "operator"}


@pytest.fixture(autouse=True)
def clean_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_mock_notification_service_sends_and_records_events() -> None:
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    service = NotificationService(provider=provider, event_log=event_log)
    shipment = ShipmentRequest(id="sr_1", livestock_type="novillos", quantity_estimate=35)

    result = service.send_new_load_alert(
        shipment=shipment,
        carrier_id="car_1",
        operator_user_id="user_operator",
    )

    assert result.status == "sent"
    assert result.provider == "mock_whatsapp"
    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0].conversation_id == "car_1"
    assert [event.event_type for event in event_log.events] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_SENT",
    ]


def test_backend_conversation_reply_is_sent_once_and_text_is_not_audited() -> None:
    provider = MockWhatsAppProvider()
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_conversation_reply(
        phone_number="+5491111111111",
        body="¿Qué cantidad necesitás transportar?",
        conversation_session_id="conv_test",
        inbound_idempotency_key="inbound_test",
        correlation_id="corr_test",
    )
    duplicate_result = service.send_conversation_reply(
        phone_number="+5491111111111",
        body="¿Qué cantidad necesitás transportar?",
        conversation_session_id="conv_test",
        inbound_idempotency_key="inbound_test",
        correlation_id="corr_test",
    )

    assert result == "sent"
    assert duplicate_result == "skipped_duplicate"
    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0].body == "¿Qué cantidad necesitás transportar?"
    assert all("body" not in event.payload for event in event_log.events)
    assert [event.event_type for event in event_log.events] == [
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


def test_backend_conversation_reply_is_persisted_once_with_qa_context() -> None:
    state = reset_app_state()
    conversation = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(
            id="cs_reply_persistence",
            channel="kapso",
            active_test_run_id="qa_synthetic_run",
            role_override="Carrier",
        )
    )
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    service = NotificationService(
        provider=provider,
        event_log=event_log,
        conversation_sessions=state.conversation_sessions,  # type: ignore[attr-defined]
        messages=state.messages,  # type: ignore[attr-defined]
    )

    service.send_conversation_reply(
        phone_number="+5491111111111",
        body="Mensaje sintetico del agente",
        conversation_session_id=conversation.id,
        inbound_idempotency_key="inbound_persisted",
        correlation_id="corr_persisted",
    )
    service.send_conversation_reply(
        phone_number="+5491111111111",
        body="Mensaje sintetico del agente",
        conversation_session_id=conversation.id,
        inbound_idempotency_key="inbound_persisted",
        correlation_id="corr_persisted",
    )

    messages = state.messages.list()  # type: ignore[attr-defined]
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, Message)
    assert message.direction == "outbound"
    assert message.sender_type == "Agent"
    assert message.raw_content == "Mensaje sintetico del agente"
    assert message.test_run_id == "qa_synthetic_run"
    assert message.related_entity_ids["qaRole"] == "Carrier"


def test_carrier_notification_is_added_to_matching_conversation_thread() -> None:
    state = reset_app_state()
    conversation = state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(
            id="cs_carrier_notification",
            channel="kapso",
            participant_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
            active_test_run_id="qa_synthetic_run",
            role_override="Carrier",
        )
    )
    provider = MockWhatsAppProvider()
    service = NotificationService(
        provider=provider,
        event_log=state.event_log,
        conversation_sessions=state.conversation_sessions,  # type: ignore[attr-defined]
        messages=state.messages,  # type: ignore[attr-defined]
    )

    result = service.send_carrier_message(
        carrier_id="carrier_synthetic",
        destination="+5491111111111",
        allowlist_phone_number="+5491111111111",
        body="Aviso sintetico de una carga.",
        entity_type="ShipmentRequest",
        entity_id="shipment_synthetic",
        notification_type="NEW_LOAD_ALERT",
        operator_user_id=None,
        idempotency_key="notification_synthetic",
    )

    assert result.status == "sent"
    messages = state.messages.list()  # type: ignore[attr-defined]
    assert len(messages) == 1
    assert messages[0].conversation_session_id == conversation.id
    assert messages[0].direction == "outbound"
    assert messages[0].sender_type == "Agent"
    assert messages[0].raw_content == "Aviso sintetico de una carga."
    assert messages[0].test_run_id == "qa_synthetic_run"


def test_manual_trip_notice_uses_carrier_routing_and_notification_type() -> None:
    state = reset_app_state()
    carrier = state.carriers.add(
        Carrier(
            id="car_trip_notice",
            name="Transportista QA",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
            provider_conversation_id="kapso_conversation_qa",
        )
    )
    provider = MockWhatsAppProvider()
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log, carriers=state.carriers)

    result = service.send_manual_message(
        carrier_id=carrier.id,
        body="El viaje quedó planificado.",
        entity_type="Trip",
        entity_id="trip_qa",
        operator_user_id="qa_operator",
        idempotency_key="trip_planned_qa",
        notification_type="TRIP_PLANNED",
    )

    assert result.status == "sent"
    assert provider.sent_messages[0].conversation_id == "kapso_conversation_qa"
    assert provider.sent_messages[0].allowlist_phone_number == "+5491111111111"
    assert event_log.events[-1].payload["notification_type"] == "TRIP_PLANNED"


def test_manual_carrier_notice_with_missing_routing_is_recorded_failed() -> None:
    state = reset_app_state()
    provider = MockWhatsAppProvider()
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log, carriers=state.carriers)

    result = service.send_manual_message(
        carrier_id="car_missing",
        body="El viaje quedó planificado.",
        entity_type="Trip",
        entity_id="trip_qa",
        operator_user_id="qa_operator",
        idempotency_key="trip_planned_missing_carrier",
        notification_type="TRIP_PLANNED",
    )

    assert result.status == "failed"
    assert provider.sent_messages == []
    assert [event.event_type for event in event_log.events] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_FAILED",
    ]
    assert event_log.events[-1].payload["notification_type"] == "TRIP_PLANNED"


def test_new_load_alert_body_is_clear_text_with_future_actions_metadata() -> None:
    state = reset_app_state()
    origin = state.locations.add(Location(id="loc_origin", original_text="Azul"))
    destination = state.locations.add(Location(id="loc_destination", original_text="Liniers"))
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    service = NotificationService(
        provider=provider,
        event_log=event_log,
        locations=state.locations,
    )
    shipment = ShipmentRequest(
        id="sr_1",
        origin_location_id=origin.id,
        destination_location_id=destination.id,
        date_window_start=datetime(2026, 5, 2, 8, 30, tzinfo=UTC),
        livestock_type="novillos",
        quantity_estimate=35,
        operational_notes="Cargar por manga del fondo. Avisar al encargado.",
    )

    result = service.send_new_load_alert(
        shipment=shipment,
        carrier_id="car_1",
        operator_user_id="user_operator",
    )

    assert result.status == "sent"
    assert provider.sent_messages[0].body == (
        "📦 Nueva carga disponible\n"
        "Carga ID sr_1 - 🐄 35 novillos\n"
        "📍 Azul → Liniers\n"
        "📅 02/05/2026 08:30\n"
        '📝 Cargar por manga del fondo. Avisar al encargado. | Si es por esta carga: "me interesa sr_1"\n\n'
        "1. Me interesa\n"
        "2. No puedo\n"
        "3. Más info\n\n"
        "Respondé con el número o el texto de la opción."
    )
    sent_event = event_log.events[-1]
    assert sent_event.payload["interactive_actions"] == [
        {"id": "interested", "label": "Me interesa", "value": "INTERESTED", "kind": "quick_reply"},
        {"id": "declined", "label": "No puedo", "value": "DECLINED", "kind": "quick_reply"},
        {"id": "more_info", "label": "Más info", "value": "MORE_INFO", "kind": "quick_reply"},
    ]
    assert sent_event.payload["interactive_delivery"] == "text_fallback"


def test_new_load_alert_body_supports_grain_loads() -> None:
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    service = NotificationService(provider=provider, event_log=event_log)
    shipment = ShipmentRequest(
        id="sr_grain",
        cargo_category="GRAIN",
        cargo_type="soja",
        quantity_unit="TON",
        quantity_estimate=30,
        operational_notes="30 toneladas de soja de Tandil a Rosario mañana.",
    )

    result = service.send_new_load_alert(
        shipment=shipment,
        carrier_id="car_1",
        operator_user_id="user_operator",
    )

    assert result.status == "sent"
    assert provider.sent_messages[0].body == (
        "📦 Nueva carga disponible\n"
        "Carga ID sr_grain - 🌾 30 toneladas soja\n"
        "📍 origen a confirmar → destino a confirmar\n"
        "📅 fecha/hora a confirmar\n"
        '📝 30 toneladas de soja de Tandil a Rosario mañana. | Si es por esta carga: "me interesa sr_grain"\n\n'
        "1. Me interesa\n"
        "2. No puedo\n"
        "3. Más info\n\n"
        "Respondé con el número o el texto de la opción."
    )
    assert event_log.events[-1].payload["cargo_category"] == "GRAIN"
    assert event_log.events[-1].payload["cargo_type"] == "soja"
    assert event_log.events[-1].payload["quantity_unit"] == "TON"
    assert provider.sent_messages[0].metadata["template_body_parameters"] == [
        "Carga ID sr_grain - 🌾 30 toneladas soja",
        "origen a confirmar → destino a confirmar",
        "fecha/hora a confirmar",
        '30 toneladas de soja de Tandil a Rosario mañana. | Si es por esta carga: "me interesa sr_grain"',
    ]


def test_argentina_phone_normalization() -> None:
    assert normalize_phone_number("+5491135690073") == "+5491135690073"
    assert normalize_phone_number("5491135690073") == "+5491135690073"
    assert normalize_phone_number("541135690073") == "+541135690073"
    assert normalize_phone_number("1135690073") == "+5491135690073"
    assert normalize_phone_number("11 3569 0073") == "+5491135690073"
    assert normalize_phone_number("11-3569-0073") == "+5491135690073"
    assert normalize_phone_number("+54 9 11 1234-5678") == "+5491112345678"
    assert normalize_phone_number("11 15 1234 5678") == "+5491112345678"
    assert normalize_phone_number("0223 15 1234567") == "+5492231234567"


def test_carrier_without_phone_or_provider_mapping_does_not_receive_outbound() -> None:
    state = reset_app_state()
    carrier = state.carriers.add(Carrier(id="car_no_phone", name="Sin telefono"))
    provider = MockWhatsAppProvider()
    service = NotificationService(provider=provider, event_log=state.event_log, carriers=state.carriers)

    result = service.send_new_load_alert(
        shipment=ShipmentRequest(id="sr_1", status="PUBLISHED"),
        carrier_id=carrier.id,
        operator_user_id="user_operator",
    )

    assert result.status == "failed"
    assert len(provider.sent_messages) == 0
    assert [event.event_type for event in state.event_log.events] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_FAILED",
    ]


def test_send_producer_message_sends_and_records_events() -> None:
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_producer_message(
        phone_number="+5491111111111",
        body="Tu carga recibió un interesado.",
        entity_type="ShipmentRequest",
        entity_id="sr_1",
        operator_user_id="user_operator",
        idempotency_key="producer_message_1",
        notification_type="INTEREST_REGISTERED",
    )

    assert result.status == "sent"
    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0].conversation_id == "+5491111111111"
    assert [event.event_type for event in event_log.events] == [
        "PRODUCER_NOTIFICATION_REQUESTED",
        "PRODUCER_NOTIFICATION_SENT",
    ]


def test_whatsapp_provider_defaults_to_mock_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "mock")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "false")
    monkeypatch.delenv("KAPSO_API_KEY", raising=False)
    monkeypatch.delenv("KAPSO_BASE_URL", raising=False)
    get_settings.cache_clear()

    provider = get_whatsapp_provider()

    assert isinstance(provider, MockWhatsAppProvider)


def test_kapso_provider_uses_mock_when_real_whatsapp_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "false")
    monkeypatch.setenv("KAPSO_API_KEY", "test-key")
    monkeypatch.setenv("KAPSO_BASE_URL", "https://kapso.example.test")
    monkeypatch.setenv("KAPSO_PHONE_NUMBER_ID", "phone_number_1")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "test-secret")
    get_settings.cache_clear()

    provider = get_whatsapp_provider()

    assert isinstance(provider, MockWhatsAppProvider)


def test_kapso_real_provider_requires_explicit_enable_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "true")
    monkeypatch.setenv("KAPSO_API_KEY", "test-key")
    monkeypatch.setenv("KAPSO_BASE_URL", "https://kapso.example.test")
    monkeypatch.setenv("KAPSO_PHONE_NUMBER_ID", "phone_number_1")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("WHATSAPP_DEV_ALLOWLIST", "+5491111111111")
    get_settings.cache_clear()

    provider = get_whatsapp_provider()

    assert isinstance(provider, KapsoProvider)
    assert provider.capabilities.supports_interactive_messages is False


def test_kapso_real_provider_interactive_capability_is_behind_env_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "true")
    monkeypatch.setenv("KAPSO_API_KEY", "test-key")
    monkeypatch.setenv("KAPSO_BASE_URL", "https://kapso.example.test")
    monkeypatch.setenv("KAPSO_PHONE_NUMBER_ID", "phone_number_1")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("WHATSAPP_DEV_ALLOWLIST", "+5491111111111")
    monkeypatch.setenv("KAPSO_INTERACTIVE_ENABLED", "true")
    get_settings.cache_clear()

    provider = get_whatsapp_provider()

    assert isinstance(provider, KapsoProvider)
    assert provider.capabilities.supports_interactive_messages is True
    assert provider.capabilities.supports_buttons is True


def test_kapso_real_provider_requires_phone_number_id_in_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "true")
    monkeypatch.setenv("KAPSO_API_KEY", "test-key")
    monkeypatch.setenv("KAPSO_BASE_URL", "https://kapso.example.test")
    monkeypatch.setenv("KAPSO_PHONE_NUMBER_ID", "")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "test-secret")
    get_settings.cache_clear()

    with pytest.raises(Exception) as exc_info:
        get_whatsapp_provider()

    assert "KAPSO_PHONE_NUMBER_ID" in str(exc_info.value)


def test_kapso_real_provider_blocks_destination_outside_dev_allowlist() -> None:
    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
    )
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_manual_message(
        carrier_id="+5492222222222",
        body="Mensaje de prueba",
        entity_type="ShipmentRequest",
        entity_id="sr_1",
        operator_user_id="user_operator",
        idempotency_key="manual_outside_allowlist",
    )

    assert result.status == "failed"
    assert [event.event_type for event in event_log.events] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_FAILED",
    ]
    assert "WHATSAPP_DEV_ALLOWLIST" in event_log.events[-1].payload["error"]


def test_kapso_real_provider_allows_provider_conversation_when_carrier_phone_is_allowlisted() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"provider_message_id": "kapso_real_msg_1"})

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+541135690073"},
        enforce_allowlist=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    state = reset_app_state()
    state.carriers.add(
        Carrier(
            id="car_test_1",
            name="Carrier Test",
            contact_phone="+5491135690073",
            normalized_phone_number="+5491135690073",
            provider_name="kapso",
            provider_conversation_id="kapso_conv_test_1",
        )
    )
    service = NotificationService(provider=provider, event_log=event_log, carriers=state.carriers)

    result = service.send_new_load_alert(
        shipment=ShipmentRequest(id="sr_1", livestock_type="novillos", quantity_estimate=35),
        carrier_id="car_test_1",
        operator_user_id="user_operator",
    )

    assert result.status == "sent"
    assert requests
    assert json.loads(requests[0].content)["to"] == "5491135690073"
    assert event_log.events[-1].payload["destination"] == "kapso_conv_test_1"


def test_kapso_real_provider_http_error_is_recorded_as_notification_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "temporary provider failure"})

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_manual_message(
        carrier_id="+5491111111111",
        body="Mensaje de prueba",
        entity_type="ShipmentRequest",
        entity_id="sr_1",
        operator_user_id="user_operator",
        idempotency_key="manual_http_error",
    )

    assert result.status == "failed"
    assert [event.event_type for event in event_log.events] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_FAILED",
    ]
    assert "status_code=500" in result.error
    assert "temporary provider failure" in result.error


def test_kapso_real_provider_success_uses_provider_message_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "5491111111111", "wa_id": "5491111111111"}],
                "messages": [{"id": "wamid_real_msg_1"}],
            },
        )

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        send_message_path="/custom/messages",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_manual_message(
        carrier_id="+5491111111111",
        body="Mensaje de prueba",
        entity_type="ShipmentRequest",
        entity_id="sr_1",
        operator_user_id="user_operator",
        idempotency_key="manual_success",
    )

    assert result.status == "sent"
    assert result.provider_message_id == "wamid_real_msg_1"
    assert str(requests[0].url) == "https://kapso.example.test/phone_number_1/custom/messages"
    assert requests[0].headers["x-api-key"] == "test-key"
    payload = json.loads(requests[0].content)
    assert payload == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5491111111111",
        "type": "text",
        "text": {
            "preview_url": False,
            "body": "Mensaje de prueba",
        },
    }


def test_kapso_real_provider_sends_new_load_alert_as_template_directly() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "messages": [{"id": "wamid_template_msg_1"}],
            },
        )

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        new_load_template_name="agro_new_load_available",
        template_language_code="es_AR",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    provider_wrapper = NotificationService(provider=provider, event_log=event_log)

    result = provider_wrapper.send_new_load_alert(
        shipment=ShipmentRequest(
            id="sr_template",
            cargo_category="GRAIN",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
            operational_notes="30 toneladas de soja de Tandil a Rosario mañana.",
        ),
        carrier_id="+5491111111111",
        operator_user_id=None,
    )

    assert result.status == "sent"
    assert result.provider_message_id == "wamid_template_msg_1"
    assert len(requests) == 1
    template_payload = json.loads(requests[0].content)
    assert template_payload == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5491111111111",
        "type": "template",
        "template": {
            "name": "agro_new_load_available",
            "language": {"code": "es_AR"},
            "components": [
                {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": "Carga ID sr_template - 🌾 30 toneladas soja"},
                            {"type": "text", "text": "origen a confirmar → destino a confirmar"},
                            {"type": "text", "text": "fecha/hora a confirmar"},
                            {
                                "type": "text",
                                "text": '30 toneladas de soja de Tandil a Rosario mañana. | Si es por esta carga: "me interesa sr_template"',
                            },
                        ],
                    }
            ],
        },
    }
    assert event_log.events[-1].event_type == "CARRIER_NOTIFICATION_SENT"
    assert event_log.events[-1].payload["attempt_type"] == "template"
    assert event_log.events[-1].payload["template_fallback_used"] is False
    assert event_log.events[-1].payload["template_name"] == "agro_new_load_available"


def test_kapso_real_provider_sends_qa_new_load_alert_as_text_when_enabled() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"messaging_product": "whatsapp", "messages": [{"id": "wamid_qa_text_1"}]},
        )

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        new_load_template_name="agro_new_load_available",
        allow_test_run_freeform_new_loads=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    provider_wrapper = NotificationService(provider=provider, event_log=event_log)

    result = provider_wrapper.send_new_load_alert(
        shipment=ShipmentRequest(
            id="sr_qa_text",
            test_run_id="qa_test_123",
            cargo_category="GRAIN",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
        ),
        carrier_id="+5491111111111",
        operator_user_id=None,
    )

    assert result.status == "sent"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["type"] == "text"
    assert payload["text"]["body"].startswith("📦 Nueva carga disponible")
    assert event_log.events[-1].event_type == "CARRIER_NOTIFICATION_SENT"
    assert event_log.events[-1].payload["attempt_type"] == "text"


def test_kapso_real_provider_records_payment_method_failure_without_template_fallback() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={
                "error": "Payment method needed.",
                "next_steps": "Add a payment method in Meta before sending business-initiated messages.",
            },
        )

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        new_load_template_name="agro_new_load_available",
        template_language_code="es_AR",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_new_load_alert(
        shipment=ShipmentRequest(
            id="sr_payment_error",
            cargo_category="GRAIN",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
            operational_notes="30 toneladas de soja de Tandil a Rosario mañana.",
        ),
        carrier_id="+5491111111111",
        operator_user_id=None,
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "Payment method needed" in result.error
    assert event_log.events[-1].event_type == "CARRIER_NOTIFICATION_FAILED"
    assert event_log.events[-1].payload["attempt_type"] == "template"
    assert event_log.events[-1].payload["template_fallback_used"] is False
    assert event_log.events[-1].payload["template_name"] == "agro_new_load_available"
    assert "Payment method needed" in event_log.events[-1].payload["provider_error_summary"]


def test_kapso_real_provider_records_template_failure_on_direct_template_send() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            422,
            json={
                "error": "Template not approved.",
            },
        )

    provider = KapsoProvider(
        webhook_secret="test-secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        new_load_template_name="agro_new_load_available",
        template_language_code="es_AR",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event_log = EventLogService()
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_new_load_alert(
        shipment=ShipmentRequest(
            id="sr_template_error",
            cargo_category="GRAIN",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
            operational_notes="30 toneladas de soja de Tandil a Rosario mañana.",
        ),
        carrier_id="+5491111111111",
        operator_user_id=None,
    )

    assert result.status == "failed"
    assert len(requests) == 1
    assert event_log.events[-1].event_type == "CARRIER_NOTIFICATION_FAILED"
    assert event_log.events[-1].payload["attempt_type"] == "template"
    assert event_log.events[-1].payload["template_fallback_used"] is False
    assert event_log.events[-1].payload["template_name"] == "agro_new_load_available"
    assert "Template not approved" in event_log.events[-1].payload["provider_error_summary"]


def test_notification_service_does_not_duplicate_sent_alert() -> None:
    event_log = EventLogService()
    provider = MockWhatsAppProvider()
    service = NotificationService(provider=provider, event_log=event_log)
    shipment = ShipmentRequest(id="sr_1", livestock_type="novillos", quantity_estimate=35)

    first = service.send_new_load_alert(
        shipment=shipment,
        carrier_id="car_1",
        operator_user_id="user_operator",
    )
    duplicate = service.send_new_load_alert(
        shipment=shipment,
        carrier_id="car_1",
        operator_user_id="user_operator",
    )

    assert first.status == "sent"
    assert duplicate.status == "skipped_duplicate"
    assert len(provider.sent_messages) == 1
    assert [event.event_type for event in event_log.events] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_SENT",
    ]


def test_admin_publish_records_partial_notification_failure(legacy_broadcast, ) -> None:
    state = reset_app_state()
    state.carriers.add(Carrier(id="car_1", name="Carrier 1", contact_phone="11 15 1111 1111"))
    state.carriers.add(Carrier(id="car_2", name="Carrier 2", contact_phone="11 15 2222 2222"))
    shipment = state.shipment_requests.add(ShipmentRequest(status="VALIDATED"))
    app.dependency_overrides[get_whatsapp_provider] = lambda: MockWhatsAppProvider(
        failing_conversation_ids={"+5491122222222"}
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={"carrier_ids": ["car_1", "car_2"]},
    )

    assert response.status_code == 200
    assert response.json()["notifications_sent"] == 1
    assert response.json()["notifications_failed"] == 1
    event_types = [event.event_type for event in state.event_log.events]
    assert event_types.count("CARRIER_NOTIFICATION_REQUESTED") == 2
    assert event_types.count("CARRIER_NOTIFICATION_SENT") == 1
    assert event_types.count("CARRIER_NOTIFICATION_FAILED") == 1


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "notifications.db"
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


def test_admin_publish_sql_backend_persists_notification_events(legacy_broadcast, 
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(
            Carrier(id="car_1", name="Carrier 1", contact_phone="+5491111111111")
        )
        shipment = SqlShipmentRequestRepository(session).add(ShipmentRequest(status="VALIDATED"))
        session.commit()

    client = TestClient(app)
    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={"carrier_ids": ["car_1"], "idempotency_key": "publish_notification_sql"},
    )

    assert response.status_code == 200
    with sql_runtime() as session:
        events = session.scalars(select(EventLogRecord)).all()
        outbox = session.scalars(select(NotificationOutboxRecord)).all()

    assert [event.event_type for event in events] == [
        "LOAD_PUBLISHED",
        "BROADCAST_SENT",
        "CARRIER_NOTIFIED",
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_QUEUED",
    ]
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"


def test_backoffice_lists_outbox_state_without_message_or_contact_data(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        session.add(
            NotificationOutboxRecord(
                id="out_private",
                idempotency_key="outbox_read_privacy_test",
                provider="kapso",
                provider_scope="sandbox_phone_id",
                message_payload={
                    "conversation_id": "+5491112345678",
                    "body": "contenido privado de prueba",
                    "metadata": {
                        "entity_type": "ShipmentRequest",
                        "entity_id": "sr_private",
                        "notification_type": "NEW_LOAD_ALERT",
                    },
                },
                entity_type="ShipmentRequest",
                entity_id="sr_private",
                status="RECONCILE_REQUIRED",
                attempts=1,
                available_at=datetime.now(UTC),
                last_error_code="TimeoutError",
            )
        )
        session.commit()

    client = TestClient(app)
    unauthorized = client.get("/api/v1/backoffice/notification-outbox")
    assert unauthorized.status_code == 401

    response = client.get(
        "/api/v1/backoffice/notification-outbox?status=RECONCILE_REQUIRED",
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["RECONCILE_REQUIRED"] == 1
    assert payload["items"][0]["notification_type"] == "NEW_LOAD_ALERT"
    assert payload["items"][0]["status"] == "RECONCILE_REQUIRED"
    assert "contenido privado de prueba" not in response.text
    assert "+5491112345678" not in response.text
    assert "sandbox_phone_id" not in response.text

    forbidden = client.post(
        "/api/v1/backoffice/notification-outbox/out_private/reconcile",
        headers=OPERATOR_HEADERS,
        json={"resolution": "RETRY_NOT_SENT", "evidence_reference": "kapso-log-123"},
    )
    assert forbidden.status_code == 403
    admin = client.post(
        "/api/v1/backoffice/notification-outbox/out_private/reconcile",
        headers={"x-operator-user-id": "admin-1", "x-operator-role": "admin"},
        json={"resolution": "RETRY_NOT_SENT", "evidence_reference": "kapso-log-123"},
    )
    assert admin.status_code == 200
    assert admin.json()["status"] == "RETRY"
