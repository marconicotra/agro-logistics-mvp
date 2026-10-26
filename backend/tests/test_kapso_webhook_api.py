import hashlib
import hmac
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_ai_extraction_client,
    get_speech_to_text_client,
    get_whatsapp_provider,
    reset_app_state,
)
from app.application.ai import AIExtractionError, LoadDataExtraction
from app.core.config import get_settings
from app.domain.models import (
    Carrier,
    CarrierOnboarding,
    ConversationSession,
    Driver,
    Location,
    ShipmentRequest,
    TripOffer,
    Vehicle,
)
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    DocumentRecord,
    EventLogRecord,
    MediaAssetRecord,
    MessageRecord,
    NotificationOutboxRecord,
    ShipmentRequestRecord,
)
from app.infrastructure.db.repositories import SqlCarrierOnboardingRepository, SqlCarrierRepository
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider
from app.infrastructure.db.session import get_engine, get_session_factory
from app.main import app


SECRET = "test-secret"
OPERATOR_HEADERS = {"x-operator-user-id": "user_operator", "x-operator-role": "operator"}


def inbound_messages(messages):
    return [message for message in messages if message.direction == "inbound"]


class FakeAIClient:
    def __init__(self, extraction: LoadDataExtraction | None = None, error: Exception | None = None) -> None:
        self.extraction = extraction
        self.error = error

    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        if self.error is not None:
            raise self.error
        assert self.extraction is not None
        return self.extraction


class FakeSTTClient:
    def __init__(self, transcript_text: str = "Hola, quiero cargar 50 cabezas de vacas de Cordoba a La Plata el 15 de junio") -> None:
        self.transcript_text = transcript_text

    def transcribe(self, *, audio_path, model: str, timeout_seconds: int) -> str:  # noqa: ANN001
        assert audio_path.exists()
        assert model
        assert timeout_seconds > 0
        return self.transcript_text


class FakeDownloadResponse:
    def __init__(self, body: bytes) -> None:
        self.headers = {"content-length": str(len(body))}
        self._body = body

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            return self._body
        return self._body[:amount]

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ANN204
        return False


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("KAPSO_TIMESTAMP_TOLERANCE_SECONDS", "300")
    monkeypatch.setenv("WHATSAPP_ALLOWLIST_SOURCE", "db_then_env")
    monkeypatch.setenv("WHATSAPP_ALLOWLIST_DEFAULT_ALLOW", "false")
    monkeypatch.setenv("WHATSAPP_DEV_ALLOWLIST", "+5491111111111")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_app_state()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_app_state()


def signed_headers(raw_body: bytes, timestamp: str | None = None) -> dict[str, str]:
    digest = hmac.new(SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    headers = {"X-Webhook-Signature": f"sha256={digest}"}
    if timestamp is not None:
        headers["x-kapso-timestamp"] = timestamp
    return headers


def kapso_docs_signed_headers(payload: object) -> dict[str, str]:
    canonical_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(SECRET.encode("utf-8"), canonical_body, hashlib.sha256).hexdigest()
    return {"X-Webhook-Signature": f"sha256={digest}"}


def post_kapso(client: TestClient, payload: object, timestamp: str | None = None):
    raw_body = json.dumps(payload).encode("utf-8")
    return client.post(
        "/api/v1/webhooks/kapso",
        content=raw_body,
        headers=signed_headers(raw_body, timestamp),
    )


def complete_extraction(raw_text: str = "35 cabezas de novillos de Azul a Liniers el miercoles, Juan") -> LoadDataExtraction:
    return LoadDataExtraction(
        raw_text=raw_text,
        origin="Azul",
        destination="Liniers",
        date_window_start=datetime(2026, 5, 6, 8, 0, tzinfo=UTC),
        livestock_type="novillos",
        quantity_estimate=Decimal("35"),
        contact="Juan",
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


def kapso_payload(
    *,
    idempotency_key: str = "evt_1",
    provider_message_id: str = "wamid_1",
    conversation_id: str = "conv_1",
    text: str = "35 cabezas de novillos de Azul a Liniers el miercoles, Juan",
) -> dict[str, object]:
    return {
        "event_type": "message.received",
        "idempotency_key": idempotency_key,
        "provider_contact_id": "contact_1",
        "provider_message_id": provider_message_id,
        "conversation_id": conversation_id,
        "workflow_execution_id": "wf_1",
        "phone_number": "+5491111111111",
        "occurred_at": "2026-05-01T12:00:00Z",
        "payload": {"text": text},
    }


def kapso_audio_payload(
    *,
    idempotency_key: str = "evt_audio_1",
    provider_message_id: str = "wamid_audio_1",
    conversation_id: str = "conv_audio_1",
    caption: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = kapso_payload(
        idempotency_key=idempotency_key,
        provider_message_id=provider_message_id,
        conversation_id=conversation_id,
        text="",
    )
    audio_payload: dict[str, object] = {
        "type": "audio",
        "audio": {
            "id": "media_audio_1",
            "url": "https://kapso.example/media/audio-note.ogg",
            "mime_type": "audio/ogg",
            "filename": "audio-note.ogg",
            "sha256": "audio123",
        },
    }
    if caption is not None:
        audio_payload["caption"] = caption
    payload["payload"] = audio_payload
    return payload


def test_valid_kapso_webhook_prepares_confirmation_preview_in_memory() -> None:
    state = reset_app_state()
    whatsapp_provider = MockWhatsAppProvider()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    app.dependency_overrides[get_whatsapp_provider] = lambda: whatsapp_provider
    client = TestClient(app)

    response = post_kapso(client, kapso_payload())

    assert response.status_code == 200
    assert len(state.conversation_sessions.list()) == 1
    conversation = state.conversation_sessions.list()[0]
    assert conversation.provider_name == "kapso"
    assert conversation.provider_contact_id == "contact_1"
    assert conversation.provider_conversation_id == "conv_1"
    assert conversation.normalized_phone_number == "+5491111111111"
    assert conversation.last_inbound_at is not None
    assert len(inbound_messages(state.messages.list())) == 1
    assert len(state.shipment_requests.list()) == 0
    assert len(whatsapp_provider.sent_messages) == 1
    assert whatsapp_provider.sent_messages[0].conversation_id == "+5491111111111"
    assert "06/05/2026" in whatsapp_provider.sent_messages[0].body
    assert [event.event_type for event in state.event_log.events] == [
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "LOAD_PREVIEW_PREPARED",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


def test_producer_edit_command_asks_for_the_field_to_change() -> None:
    whatsapp_provider = MockWhatsAppProvider()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        complete_extraction(
            "Quiero transportar 25 terneros de 300 kilos desde Ayacucho a Cañuelas, para el 27/10/2026"
        )
    )
    app.dependency_overrides[get_whatsapp_provider] = lambda: whatsapp_provider
    client = TestClient(app)

    preview = post_kapso(
        client,
        kapso_payload(
            text="Quiero transportar 25 terneros de 300 kilos desde Ayacucho a Cañuelas, para el 27/10/2026"
        ),
    )
    edit = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_edit_load",
            provider_message_id="wamid_edit_load",
            text="Editar",
        ),
    )
    date_update = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_edit_load_date",
            provider_message_id="wamid_edit_load_date",
            text="destino San Vicente",
        ),
    )

    assert preview.status_code == edit.status_code == date_update.status_code == 200
    assert len(whatsapp_provider.sent_messages) == 3
    assert "¿Confirmás esta información?" in whatsapp_provider.sent_messages[0].body
    assert "Cantidad: 25 cabezas" in whatsapp_provider.sent_messages[0].body
    assert "Pesaje: 300 kg por cabeza" in whatsapp_provider.sent_messages[0].body
    assert "Destino: Cañuelas" in whatsapp_provider.sent_messages[0].body
    assert "Cañuelas, para" not in whatsapp_provider.sent_messages[0].body
    assert "qué dato querés cambiar" in whatsapp_provider.sent_messages[1].body
    assert "¿Confirmás esta información?" in whatsapp_provider.sent_messages[2].body
    assert "¿Qué necesitás hacer hoy?" not in whatsapp_provider.sent_messages[2].body
    assert "Cantidad: 25 cabezas" in whatsapp_provider.sent_messages[2].body
    assert "Pesaje: 300 kg por cabeza" in whatsapp_provider.sent_messages[2].body


def test_kapso_webhook_multiturn_confirmation_accepts_si_confirmalo(
    sql_runtime: sessionmaker[Session],
) -> None:
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        error=AIExtractionError("AI extraction client is not configured")
    )
    client = TestClient(app)

    step_1 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_si_confirmalo_sql_1",
            provider_message_id="wamid_si_confirmalo_sql_1",
            text="quiero crear una carga, necesito transportar 40 cabezas de vacas de santa fe a cordoba, para el 11 de septiembre",
        ),
    )
    step_2 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_si_confirmalo_sql_2",
            provider_message_id="wamid_si_confirmalo_sql_2",
            text="si confirmalo",
        ),
    )

    assert step_1.status_code == 200
    assert step_2.status_code == 200

    with sql_runtime() as session:
        shipments = session.scalars(select(ShipmentRequestRecord)).all()
        events = session.scalars(select(EventLogRecord).order_by(EventLogRecord.occurred_at)).all()

    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment.status == "PUBLISHED"
    assert shipment.livestock_type == "vacas"
    assert shipment.quantity_estimate == Decimal("40")
    assert "SHIPMENT_DRAFT_CREATED_FROM_CHAT" in [event.event_type for event in events]


def test_backend_answers_producer_menu_and_empty_dashboard_without_calling_ai() -> None:
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        error=AIExtractionError("should not parse a menu command")
    )
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    client = TestClient(app)

    menu = post_kapso(
        client,
        kapso_payload(idempotency_key="evt_menu", provider_message_id="wamid_menu", text="Hola"),
    )
    dashboard = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_dashboard_empty",
            provider_message_id="wamid_dashboard_empty",
            text="ver mi carga",
        ),
    )

    assert menu.status_code == dashboard.status_code == 200
    assert "1. 📦 Crear carga" in provider.sent_messages[0].body
    assert "4. 👥 Ver interesados" in provider.sent_messages[0].body
    assert provider.sent_messages[1].body == "No encontré cargas para este número."


def test_backend_lists_and_accepts_producer_offer_by_whatsapp_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    state = reset_app_state()
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        error=AIExtractionError("should not parse a producer query")
    )
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    state.carriers.add(
        Carrier(
            id="car_producer_offer",
            name="Camila",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
        )
    )
    origin = state.locations.add(Location(original_text="Pergamino"))
    destination = state.locations.add(Location(original_text="Rosario"))
    shipment = state.shipment_requests.add(
        ShipmentRequest(
            id="sr_producer_offer",
            producer_phone_number="+5491111111111",
            origin_location_id=origin.id,
            destination_location_id=destination.id,
            status="MATCHING",
            cargo_category="LIVESTOCK",
            livestock_type="novillos",
            quantity_estimate=Decimal("30"),
        )
    )
    state.trip_offers.add(
        TripOffer(
            id="off_producer_offer",
            shipment_request_id=shipment.id,
            carrier_id="car_producer_offer",
            response_type="INTERESTED",
            status="RECEIVED",
        )
    )
    client = TestClient(app)

    listing = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_offer_listing",
            provider_message_id="wamid_offer_listing",
            text="ver interesados",
        ),
    )
    acceptance = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_offer_acceptance",
            provider_message_id="wamid_offer_acceptance",
            text="aceptar oferta 1",
        ),
    )
    confirmed = post_kapso(client, kapso_payload(idempotency_key="evt_offer_confirmed", provider_message_id="wamid_offer_confirmed", text="confirmar"))
    assert confirmed.status_code == 200
    assert state.assignments.list(), " | ".join(m.body for m in provider.sent_messages)
    repeated_acceptance = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_offer_acceptance_repeat",
            provider_message_id="wamid_offer_acceptance_repeat",
            text="elegir 1",
        ),
    )

    assert listing.status_code == acceptance.status_code == repeated_acceptance.status_code == 200
    assert "1. Camila" in provider.sent_messages[0].body
    assert "Aceptar 1" in provider.sent_messages[0].body
    assert any("El viaje quedó planificado." in item.body for item in provider.sent_messages), [m.body for m in provider.sent_messages]
    assert "No hay ofertas pendientes para aceptar" in provider.sent_messages[-1].body
    assert len(state.assignments.list()) == 1
    assert len(state.trips.list()) == 1
    assert state.assignments.list()[0].status == "CONFIRMED"
    assert state.trips.list()[0].status == "PLANNED"


def test_backend_carrier_menu_and_received_load_answer_without_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_TEST_ROLE_SWITCHING", "true")
    get_settings.cache_clear()
    state = reset_app_state()
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        error=AIExtractionError("should not parse a carrier menu")
    )
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    carrier = state.carriers.add(
        Carrier(
            id="car_received_load",
            name="Transportista QA",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
        )
    )
    state.conversation_sessions.add(
        ConversationSession(
            channel="kapso",
            provider_name="kapso",
            provider_conversation_id="conv_1",
            normalized_phone_number="+5491111111111",
            participant_phone="+5491111111111",
            role_override="Carrier",
            active_test_run_id="qa_carrier_menu",
        )
    )
    origin = state.locations.add(Location(original_text="Azul"))
    destination = state.locations.add(Location(original_text="Rosario"))
    shipment = state.shipment_requests.add(
        ShipmentRequest(
            id="sr_received_load",
            test_run_id="qa_carrier_menu",
            producer_phone_number="+5491199999999",
            origin_location_id=origin.id,
            destination_location_id=destination.id,
            status="PUBLISHED",
            livestock_type="novillos",
            quantity_unit="HEAD",
            quantity_estimate=Decimal("45"),
            date_window_start=datetime(2026, 10, 2, 8, tzinfo=UTC),
        )
    )
    state.event_log.record(
        event_type="CARRIER_NOTIFICATION_SENT",
        actor_type="SYSTEM",
        entity_type="ShipmentRequest",
        entity_id=shipment.id,
        test_run_id="qa_carrier_menu",
        summary="Notificacion enviada",
        related_entity_ids={"carrierId": carrier.id},
        payload={"shipment_request_id": shipment.id},
        idempotency_key="carrier_received_load_sent",
    )
    client = TestClient(app)

    menu = post_kapso(
        client,
        kapso_payload(idempotency_key="evt_carrier_menu", provider_message_id="wamid_carrier_menu", text="Hola"),
    )
    received = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_carrier_received",
            provider_message_id="wamid_carrier_received",
            text="ver carga recibida",
        ),
    )

    assert menu.status_code == received.status_code == 200
    assert "1. 📦 Carga recibida" in provider.sent_messages[0].body
    assert "Carga recibida: 45 cabezas de novillos" in provider.sent_messages[1].body
    assert "Origen: Azul" in provider.sent_messages[1].body
    assert "Fecha: 02/10/2026" in provider.sent_messages[1].body

    more_info = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_carrier_more_info",
            provider_message_id="wamid_carrier_more_info",
            text="Más info",
        ),
    )
    availability = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_carrier_availability_text",
            provider_message_id="wamid_carrier_availability_text",
            text="Informar disponibilidad",
        ),
    )

    assert more_info.status_code == availability.status_code == 200
    assert "Fecha: 02/10/2026" in provider.sent_messages[-2].body
    assert "¿Desde qué localidad salís?" in provider.sent_messages[-1].body
    assert len(state.trip_offers.list()) == 0


def test_valid_kapso_webhook_accepts_docs_json_payload_signature() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)
    payload = kapso_payload(idempotency_key="evt_docs_signature", provider_message_id="wamid_docs_signature")
    raw_body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    response = client.post(
        "/api/v1/webhooks/kapso",
        content=raw_body,
        headers=kapso_docs_signed_headers(payload),
    )

    assert response.status_code == 200
    messages = inbound_messages(state.messages.list())
    assert len(messages) == 1
    assert messages[0].idempotency_key == "evt_docs_signature"


def test_valid_kapso_webhook_accepts_nested_real_payload_with_header_fallbacks() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)
    payload = {
        "data": {
            "message": {
                "id": "wamid_real_nested",
                "text": {"body": "35 cabezas de novillos de Azul a Liniers el miercoles, Juan"},
                "from": "+5491111111111",
            },
            "conversation": {"id": "conv_real_nested"},
            "contact": {"id": "contact_real_nested", "phone_number": "+5491111111111"},
            "timestamp": "2026-05-01T12:00:00Z",
        },
    }
    raw_body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    headers = kapso_docs_signed_headers(payload)
    headers["X-Webhook-Event"] = "message.received"
    headers["X-Webhook-Payload-Version"] = "1"
    headers["X-Idempotency-Key"] = "evt_real_nested"

    response = client.post("/api/v1/webhooks/kapso", content=raw_body, headers=headers)

    assert response.status_code == 200
    messages = inbound_messages(state.messages.list())
    assert len(messages) == 1
    message = messages[0]
    assert message.idempotency_key == "evt_real_nested"
    assert message.provider_message_id == "wamid_real_nested"
    conversation = state.conversation_sessions.list()[0]
    assert conversation.provider_contact_id == "contact_real_nested"
    assert conversation.provider_conversation_id == "conv_real_nested"


def test_invalid_kapso_payload_logs_safe_shape_metadata(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(app)
    payload = {
        "data": {
            "message": {"text": {"body": "texto sensible"}, "from": "+5491111111111"},
            "contact": {"phone_number": "+5491111111111"},
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    headers = signed_headers(raw_body)
    headers["X-Webhook-Event"] = "message.received"
    headers["X-Webhook-Payload-Version"] = "1"

    with caplog.at_level(logging.WARNING, logger="app.api.routes.webhooks"):
        response = client.post("/api/v1/webhooks/kapso", content=raw_body, headers=headers)

    assert response.status_code == 400
    assert "top_level_keys=['data']" in caplog.text
    assert "webhook_event=message.received" in caplog.text
    assert "payload_version=1" in caplog.text
    assert "idempotency_header_present=False" in caplog.text
    assert "Missing idempotency data" in caplog.text
    assert "texto sensible" not in caplog.text
    assert "+5491111111111" not in caplog.text


def test_inbound_kapso_webhook_resolves_existing_conversation_by_provider_contact() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)

    first = post_kapso(client, kapso_payload(idempotency_key="evt_contact_1", conversation_id="conv_old"))
    second = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_contact_2",
            provider_message_id="wamid_contact_2",
            conversation_id="conv_new",
        ),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(state.conversation_sessions.list()) == 1
    conversation = state.conversation_sessions.list()[0]
    assert conversation.provider_contact_id == "contact_1"
    assert conversation.provider_conversation_id == "conv_new"


def test_duplicate_kapso_webhook_does_not_duplicate_message_or_events() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)
    payload = kapso_payload(idempotency_key="evt_duplicate", provider_message_id="wamid_duplicate")

    first = post_kapso(client, payload)
    duplicate = post_kapso(client, payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicates"] == 1
    assert len(inbound_messages(state.messages.list())) == 1
    assert len(state.shipment_requests.list()) == 0
    assert len(state.event_log.events) == 5


def test_duplicate_kapso_webhook_without_explicit_key_uses_provider_message_id() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)
    payload = kapso_payload(provider_message_id="wamid_fallback_key")
    payload.pop("idempotency_key")

    first = post_kapso(client, payload)
    duplicate = post_kapso(client, payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicates"] == 1
    assert len(inbound_messages(state.messages.list())) == 1
    assert len(state.event_log.events) == 5


def test_invalid_kapso_signature_fails() -> None:
    client = TestClient(app)
    raw_body = json.dumps(kapso_payload()).encode("utf-8")

    response = client.post(
        "/api/v1/webhooks/kapso",
        content=raw_body,
        headers={"X-Webhook-Signature": "sha256=bad"},
    )

    assert response.status_code == 403


def test_invalid_kapso_payload_fails_with_400() -> None:
    client = TestClient(app)
    payload = {"provider_message_id": "wamid_without_event_type"}

    response = post_kapso(client, payload)

    assert response.status_code == 400


def test_kapso_webhook_uses_x_idempotency_key_header() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)
    payload = kapso_payload(provider_message_id="wamid_header_idempotency")
    payload.pop("idempotency_key")
    raw_body = json.dumps(payload).encode("utf-8")
    headers = signed_headers(raw_body)
    headers["X-Idempotency-Key"] = "header_evt_1"

    response = client.post("/api/v1/webhooks/kapso", content=raw_body, headers=headers)

    assert response.status_code == 200
    assert inbound_messages(state.messages.list())[0].idempotency_key == "header_evt_1"


def test_old_kapso_timestamp_fails_replay_validation() -> None:
    client = TestClient(app)

    response = post_kapso(client, kapso_payload(), timestamp="2000-01-01T00:00:00Z")

    assert response.status_code == 403


def test_batched_kapso_webhook_processes_each_event() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)
    payload = {
        "events": [
            kapso_payload(idempotency_key="evt_batch_1", provider_message_id="wamid_batch_1"),
            kapso_payload(
                idempotency_key="evt_batch_2",
                provider_message_id="wamid_batch_2",
                conversation_id="conv_2",
            ),
        ]
    }

    response = post_kapso(client, payload)

    assert response.status_code == 200
    assert response.json()["processed"] == 2
    assert len(inbound_messages(state.messages.list())) == 2
    assert len(state.shipment_requests.list()) == 0
    assert len([event for event in state.event_log.events if event.event_type == "LOAD_PREVIEW_PREPARED"]) == 2


def test_ai_failure_requests_handoff_without_exposing_internal_error() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        error=AIExtractionError("provider unavailable")
    )
    client = TestClient(app)

    response = post_kapso(client, kapso_payload())

    assert response.status_code == 200
    assert response.json()["results"][0]["handoff_required"] is True
    assert len(inbound_messages(state.messages.list())) == 1
    assert len(state.shipment_requests.list()) == 0
    assert [event.event_type for event in state.event_log.events] == [
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "HUMAN_REVIEW_REQUESTED",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


def test_kapso_media_webhook_creates_media_asset_and_carrier_document() -> None:
    state = reset_app_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_media", name="Carrier Media", contact_phone="+5491111111111")
    )
    client = TestClient(app)
    payload = kapso_payload(
        idempotency_key="evt_media_doc",
        provider_message_id="wamid_media_doc",
        text="cedula verde",
    )
    payload["payload"] = {
        "type": "document",
        "caption": "cedula verde",
        "media": {
            "id": "kapso_media_doc_1",
            "url": "https://kapso.example/media/cedula.pdf",
            "mime_type": "application/pdf",
            "filename": "cedula.pdf",
            "sha256": "abc123",
        },
    }

    response = post_kapso(client, payload)

    assert response.status_code == 200
    assert response.json()["results"][0]["handoff_required"] is False
    messages = inbound_messages(state.messages.list())  # type: ignore[attr-defined]
    assert len(messages) == 1
    message = messages[0]
    assert message.message_type == "document"
    assert len(state.media_assets.list()) == 1  # type: ignore[attr-defined]
    media_asset = state.media_assets.list()[0]  # type: ignore[attr-defined]
    assert media_asset.message_id == message.id
    assert media_asset.provider == "kapso"
    assert media_asset.provider_media_id == "kapso_media_doc_1"
    assert media_asset.status == "PROCESSED"
    assert message.media_asset_id == media_asset.id
    assert len(state.documents.list()) == 1  # type: ignore[attr-defined]
    document = state.documents.list()[0]  # type: ignore[attr-defined]
    assert document.entity_type == "carrier"
    assert document.entity_id == "car_media"
    assert document.document_type == "cedula"
    assert document.external_uri == "https://kapso.example/media/cedula.pdf"
    assert document.provider == "kapso"
    assert document.provider_media_id == "kapso_media_doc_1"
    assert document.mime_type == "application/pdf"
    assert document.file_name == "cedula.pdf"
    assert document.uploaded_by_phone == "+5491111111111"
    assert [event.event_type for event in state.event_log.events] == [
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "MEDIA_ASSET_RECEIVED",
        "CARRIER_DOCUMENT_CREATED_FROM_MEDIA",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]

    documents_response = client.get(
        "/api/v1/backoffice/carriers/car_media/documents",
        headers=OPERATOR_HEADERS,
    )
    assert documents_response.status_code == 200
    assert documents_response.json()[0]["provider_media_id"] == "kapso_media_doc_1"
    assert documents_response.json()[0]["mime_type"] == "application/pdf"


def test_kapso_media_webhook_without_matching_carrier_keeps_document_uncreated() -> None:
    state = reset_app_state()
    client = TestClient(app)
    payload = kapso_payload(
        idempotency_key="evt_media_unmatched",
        provider_message_id="wamid_media_unmatched",
        text="dni frente",
    )
    payload["payload"] = {
        "type": "image",
        "image": {
            "id": "kapso_media_img_1",
            "url": "https://kapso.example/media/dni.jpg",
            "mime_type": "image/jpeg",
            "caption": "dni frente",
        },
    }

    response = post_kapso(client, payload)

    assert response.status_code == 200
    assert response.json()["results"][0]["handoff_required"] is True
    assert len(state.media_assets.list()) == 1  # type: ignore[attr-defined]
    assert len(state.documents.list()) == 0  # type: ignore[attr-defined]
    assert [event.event_type for event in state.event_log.events] == [
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "MEDIA_ASSET_RECEIVED",
        "MEDIA_UNMATCHED_TO_CARRIER",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


def test_qa_producer_media_is_not_attached_to_carrier_with_same_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_TEST_ROLE_SWITCHING", "true")
    get_settings.cache_clear()
    state = reset_app_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_same_phone",
            name="Carrier QA",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
        )
    )
    client = TestClient(app)

    start_response = post_kapso(
        client,
        kapso_payload(idempotency_key="evt_media_qa_start", text="/test iniciar"),
    )
    role_response = post_kapso(
        client,
        kapso_payload(idempotency_key="evt_media_qa_producer", text="/soy productor"),
    )
    media_payload = kapso_payload(
        idempotency_key="evt_media_qa_producer_upload",
        provider_message_id="wamid_media_qa_producer_upload",
        text="licencia",
    )
    media_payload["payload"] = {
        "type": "image",
        "image": {
            "id": "kapso_media_qa_producer_upload",
            "url": "https://kapso.example/media/license.jpg",
            "mime_type": "image/jpeg",
            "caption": "licencia",
        },
    }
    media_response = post_kapso(client, media_payload)

    assert start_response.status_code == role_response.status_code == media_response.status_code == 200
    assert media_response.json()["results"][0]["handoff_required"] is True
    assert len(state.media_assets.list()) == 1  # type: ignore[attr-defined]
    assert len(state.documents.list()) == 0  # type: ignore[attr-defined]
    assert inbound_messages(state.messages.list())[-1].sender_type == "Producer"  # type: ignore[attr-defined]
    assert "MEDIA_UNMATCHED_TO_CARRIER" in [event.event_type for event in state.event_log.events]


def test_carrier_onboarding_capture_associates_license_to_selected_driver() -> None:
    state = reset_app_state()
    provider = MockWhatsAppProvider()
    app.dependency_overrides[get_whatsapp_provider] = lambda: provider
    client = TestClient(app)

    responses = []
    for index, text in enumerate(
        [
            "Quiero registrarme como transportista",
            "Marco QA",
            "marco.qa@example.com",
            "no corresponde",
            "20123456786",
            "2",
            "AB123CD",
            "camion jaula",
            "jaula",
            "Marco Chofer",
            "mismo",
            "B1",
        ]
    ):
        responses.append(
            post_kapso(
                client,
                kapso_payload(
                    idempotency_key=f"evt_carrier_onboarding_{index}",
                    provider_message_id=f"wamid_carrier_onboarding_{index}",
                    text=text,
                ),
            )
        )

    license_payload = kapso_payload(
        idempotency_key="evt_carrier_onboarding_license",
        provider_message_id="wamid_carrier_onboarding_license",
        text="",
    )
    license_payload["payload"] = {
        "type": "image",
        "image": {
            "id": "media_driver_license",
            "url": "https://kapso.example/media/license.jpg",
            "mime_type": "image/jpeg",
            "caption": "licencia",
        },
    }
    responses.append(post_kapso(client, license_payload))

    for index, text in enumerate(
        ("sí", "CD456EF", "camión jaula", "jaula", "Sofia Conductora", "11 2222 3333", "B1")
    ):
        responses.append(
            post_kapso(
                client,
                kapso_payload(
                    idempotency_key=f"evt_carrier_onboarding_vehicle_2_{index}",
                    provider_message_id=f"wamid_carrier_onboarding_vehicle_2_{index}",
                    text=text,
                ),
            )
        )
    second_license_payload = kapso_payload(
        idempotency_key="evt_carrier_onboarding_license_2",
        provider_message_id="wamid_carrier_onboarding_license_2",
        text="",
    )
    second_license_payload["payload"] = {
        "type": "image",
        "image": {
            "id": "media_driver_license_2",
            "url": "https://kapso.example/media/license-2.jpg",
            "mime_type": "image/jpeg",
            "caption": "licencia",
        },
    }
    responses.append(post_kapso(client, second_license_payload))
    duplicate_license_response = post_kapso(client, second_license_payload)
    responses.append(duplicate_license_response)

    for index, text in enumerate(
        ("editar", "cuit", "123", "27-12345678-6", "editar", "patente unidad 2", "CD456GZ", "confirmar")
    ):
        responses.append(
            post_kapso(
                client,
                kapso_payload(
                    idempotency_key=f"evt_carrier_onboarding_edit_{index}",
                    provider_message_id=f"wamid_carrier_onboarding_edit_{index}",
                    text=text,
                ),
            )
        )

    assert all(response.status_code == 200 for response in responses)
    carrier = next(item for item in state.carriers.list() if item.name == "Marco QA")
    drivers = [item for item in state.drivers.list() if item.carrier_id == carrier.id]
    vehicles = [item for item in state.vehicles.list() if item.carrier_id == carrier.id]
    onboarding = next(item for item in state.carrier_onboardings.list() if item.carrier_id == carrier.id)
    license_documents = state.documents.list()

    assert carrier.contact_phone == "+5491111111111"
    assert carrier.cuit == "27123456786"
    assert carrier.truck_count == 2
    assert {driver.name for driver in drivers} == {"Marco Chofer", "Sofia Conductora"}
    assert {driver.phone for driver in drivers} == {"+5491111111111", "+5491122223333"}
    assert all(driver.validation_status == "PENDING_REVIEW" for driver in drivers)
    assert {vehicle.plate for vehicle in vehicles} == {"AB123CD", "CD456GZ"}
    assert {vehicle.vehicle_type for vehicle in vehicles} == {"camion jaula"}
    assert {vehicle.validation_flags["body_type"] for vehicle in vehicles} == {"jaula"}
    assert all(vehicle.validation_status == "PENDING_REVIEW" for vehicle in vehicles)
    assert len(license_documents) == 2
    assert all(document.entity_type == "driver" for document in license_documents)
    assert {document.entity_id for document in license_documents} == {driver.id for driver in drivers}
    assert all(document.document_type == "licencia" for document in license_documents)
    assert onboarding.capture_context["step"] == "complete"
    assert onboarding.capture_context["captured_vehicle_count"] == "2"
    assert onboarding.capture_context["declared_vehicle_count"] == "2"
    assert onboarding.capture_context["vehicle_id"] in {vehicle.id for vehicle in vehicles}
    assert onboarding.capture_context["driver_id"] in {driver.id for driver in drivers}
    assert carrier.is_validated is False
    assert carrier.validation_status != "APPROVED"
    assert any(event.event_type == "CARRIER_ONBOARDING_DATA_CAPTURED" for event in state.event_log.events)
    assert any(event.event_type == "CARRIER_ONBOARDING_FIELD_CORRECTED" for event in state.event_log.events)
    assert duplicate_license_response.json()["duplicates"] == 1
    sent_bodies = [item.body for item in provider.sent_messages]
    assert any("Confirmás estos datos" in body for body in sent_bodies)
    assert any("¿Qué dato querés cambiar?" in body for body in sent_bodies)
    assert any("El CUIT debe tener 11 dígitos" in body for body in sent_bodies)
    assert any("CUIT declarado: 27123456786" in body for body in sent_bodies)
    assert "no estás homologado" in sent_bodies[-1]


def test_qa_producer_role_does_not_start_carrier_onboarding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_TEST_ROLE_SWITCHING", "true")
    get_settings.cache_clear()
    state = reset_app_state()
    client = TestClient(app)
    start_response = post_kapso(
        client,
        kapso_payload(idempotency_key="evt_onboarding_qa_start", text="/test iniciar"),
    )
    role_response = post_kapso(
        client,
        kapso_payload(idempotency_key="evt_onboarding_qa_role", text="/soy productor"),
    )
    intent_response = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_onboarding_qa_producer_intent",
            text="Quiero registrarme como transportista",
        ),
    )

    assert start_response.status_code == role_response.status_code == intent_response.status_code == 200
    assert state.carriers.list() == []
    assert state.carrier_onboardings.list() == []
    assert inbound_messages(state.messages.list())[-1].sender_type == "Producer"


def test_carrier_onboarding_capture_context_round_trips_through_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as db_session:
            repository = SqlCarrierOnboardingRepository(db_session)
            onboarding = repository.add(
                CarrierOnboarding(
                    carrier_id="carrier_sql_capture",
                    capture_context={"step": "driver_license_upload", "driver_id": "driver_sql_capture"},
                )
            )
            restored = repository.get(onboarding.id)
            assert restored is not None
            assert restored.capture_context == {
                "step": "driver_license_upload",
                "driver_id": "driver_sql_capture",
            }
    finally:
        engine.dispose()


def test_kapso_media_webhook_does_not_break_text_message_flow() -> None:
    state = reset_app_state()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)

    response = post_kapso(client, kapso_payload(idempotency_key="evt_text_after_media_changes"))

    assert response.status_code == 200
    messages = inbound_messages(state.messages.list())  # type: ignore[attr-defined]
    assert len(messages) == 1
    assert messages[0].message_type == "text"
    assert len(state.media_assets.list()) == 0  # type: ignore[attr-defined]
    assert len(state.documents.list()) == 0  # type: ignore[attr-defined]
    assert len(state.shipment_requests.list()) == 0  # type: ignore[attr-defined]


def test_kapso_audio_webhook_skips_transcription_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    state = reset_app_state()
    monkeypatch.setenv("STT_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(app)

    response = post_kapso(client, kapso_audio_payload(idempotency_key="evt_audio_disabled"))

    assert response.status_code == 200
    assert response.json()["results"][0]["handoff_required"] is False
    messages = inbound_messages(state.messages.list())  # type: ignore[attr-defined]
    assert len(messages) == 1
    message = messages[0]
    assert message.message_type == "audio"
    assert len(state.media_assets.list()) == 1  # type: ignore[attr-defined]
    media_asset = state.media_assets.list()[0]  # type: ignore[attr-defined]
    assert media_asset.transcription_status == "SKIPPED"
    assert media_asset.transcription_error == "speech_to_text_disabled"
    assert len(state.shipment_requests.list()) == 0  # type: ignore[attr-defined]
    assert [event.event_type for event in state.event_log.events] == [  # type: ignore[attr-defined]
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "MEDIA_ASSET_RECEIVED",
        "MEDIA_TRANSCRIPTION_SKIPPED",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


def test_kapso_audio_webhook_transcribes_and_processes_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    state = reset_app_state()
    monkeypatch.setenv("STT_ENABLED", "true")
    monkeypatch.setenv("MEDIA_DOWNLOAD_ENABLED", "false")
    monkeypatch.setenv("STT_MAX_AUDIO_BYTES", "25000000")
    get_settings.cache_clear()
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        complete_extraction("Hola, quiero cargar 50 cabezas de vacas de Cordoba a La Plata el 15 de junio")
    )
    app.dependency_overrides[get_speech_to_text_client] = lambda: FakeSTTClient(
        "Hola, quiero cargar 50 cabezas de vacas de Cordoba a La Plata el 15 de junio"
    )
    monkeypatch.setattr(
        "app.application.media.urlopen",
        lambda request, timeout=10: FakeDownloadResponse(b"fake audio bytes"),
    )
    client = TestClient(app)

    response = post_kapso(client, kapso_audio_payload(idempotency_key="evt_audio_success"))

    assert response.status_code == 200
    assert response.json()["results"][0]["handoff_required"] is False
    messages = inbound_messages(state.messages.list())  # type: ignore[attr-defined]
    assert len(messages) == 1
    message = messages[0]
    assert message.message_type == "audio"
    assert message.normalized_content == "Hola, quiero cargar 50 cabezas de vacas de Cordoba a La Plata el 15 de junio"
    assert len(state.media_assets.list()) == 1  # type: ignore[attr-defined]
    media_asset = state.media_assets.list()[0]  # type: ignore[attr-defined]
    assert media_asset.status == "DOWNLOADED"
    assert media_asset.storage_uri is not None
    assert media_asset.transcription_status == "SUCCEEDED"
    assert media_asset.transcription_text == "Hola, quiero cargar 50 cabezas de vacas de Cordoba a La Plata el 15 de junio"
    assert len(state.shipment_requests.list()) == 0  # type: ignore[attr-defined]
    assert [event.event_type for event in state.event_log.events] == [  # type: ignore[attr-defined]
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "MEDIA_ASSET_RECEIVED",
        "MEDIA_TRANSCRIPTION_STARTED",
        "MEDIA_TRANSCRIPTION_SUCCEEDED",
        "LOAD_PREVIEW_PREPARED",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


def test_kapso_audio_webhook_returns_fallback_when_stt_client_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = reset_app_state()
    monkeypatch.setenv("STT_ENABLED", "true")
    get_settings.cache_clear()
    app.dependency_overrides[get_speech_to_text_client] = lambda: None
    client = TestClient(app)

    response = post_kapso(client, kapso_audio_payload(idempotency_key="evt_audio_failed"))

    assert response.status_code == 200
    assert response.json()["results"][0]["handoff_required"] is False
    assert len(state.media_assets.list()) == 1  # type: ignore[attr-defined]
    media_asset = state.media_assets.list()[0]  # type: ignore[attr-defined]
    assert media_asset.transcription_status == "FAILED"
    assert media_asset.transcription_error == "Speech-to-text client is not configured"
    assert len(state.shipment_requests.list()) == 0  # type: ignore[attr-defined]
    assert [event.event_type for event in state.event_log.events] == [  # type: ignore[attr-defined]
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "MEDIA_ASSET_RECEIVED",
        "MEDIA_TRANSCRIPTION_FAILED",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_SENT",
    ]


@pytest.fixture()
def sql_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "kapso-webhook.db"
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


def test_kapso_webhook_sql_backend_persists_message_and_confirmation_preview_event(
    sql_runtime: sessionmaker[Session],
) -> None:
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(complete_extraction())
    client = TestClient(app)

    response = post_kapso(client, kapso_payload(idempotency_key="evt_sql", provider_message_id="wamid_sql"))

    assert response.status_code == 200
    with sql_runtime() as session:
        messages = session.scalars(select(MessageRecord)).all()
        shipments = session.scalars(select(ShipmentRequestRecord)).all()
        events = session.scalars(select(EventLogRecord)).all()
        outbox = session.scalars(select(NotificationOutboxRecord)).all()

    inbound = [message for message in messages if message.direction == "inbound"]
    assert len(inbound) == 1
    assert len(shipments) == 0
    assert [event.event_type for event in events] == [
        "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST",
        "MESSAGE_RECEIVED",
        "LOAD_PREVIEW_PREPARED",
        "CONVERSATION_REPLY_REQUESTED",
        "CONVERSATION_REPLY_QUEUED",
    ]
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"


def test_kapso_webhook_sql_backend_creates_chat_draft_on_confirmation_fallback(
    sql_runtime: sessionmaker[Session],
) -> None:
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient(
        error=AIExtractionError("AI extraction client is not configured")
    )
    client = TestClient(app)

    load_response = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_sql_chat_load",
            provider_message_id="wamid_sql_chat_load",
            text="Hola, Necesito camión para 71 cabezas de vacas de Tandil a Cañuelas mañana, 250 kilos cada una",
        ),
    )
    confirm_response = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_sql_chat_confirm",
            provider_message_id="wamid_sql_chat_confirm",
            text="confirmar",
        ),
    )

    assert load_response.status_code == 200
    assert confirm_response.status_code == 200
    with sql_runtime() as session:
        messages = session.scalars(select(MessageRecord).order_by(MessageRecord.created_at)).all()
        shipments = session.scalars(select(ShipmentRequestRecord)).all()
        events = session.scalars(select(EventLogRecord).order_by(EventLogRecord.occurred_at)).all()

    assert [message.raw_content for message in messages if message.direction == "inbound"] == [
        "Hola, Necesito camión para 71 cabezas de vacas de Tandil a Cañuelas mañana, 250 kilos cada una",
        "confirmar",
    ]
    assert len(shipments) == 1
    assert shipments[0].status == "PUBLISHED"
    assert shipments[0].livestock_type == "vacas"
    assert shipments[0].quantity_estimate == Decimal("71")
    assert shipments[0].operational_notes == (
        "Hola, Necesito camión para 71 cabezas de vacas de Tandil a Cañuelas mañana, 250 kilos cada una"
    )
    assert "SHIPMENT_DRAFT_CREATED_FROM_CHAT" in [event.event_type for event in events]
    assert "LOAD_SELF_PUBLISHED" in [event.event_type for event in events]


def test_kapso_webhook_sql_backend_creates_published_shipment_from_multiturn_confirmation_and_backoffice_counts_it(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)

    step_1 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_multiturn_1",
            provider_message_id="wamid_multiturn_1",
            text="1",
        ),
    )
    step_2 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_multiturn_2",
            provider_message_id="wamid_multiturn_2",
            text="son 50 cabezas de vacas",
        ),
    )
    step_3 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_multiturn_3",
            provider_message_id="wamid_multiturn_3",
            text="Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio",
        ),
    )
    step_4 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_multiturn_4",
            provider_message_id="wamid_multiturn_4",
            text="confirmo",
        ),
    )

    assert step_1.status_code == 200
    assert step_2.status_code == 200
    assert step_3.status_code == 200
    assert step_4.status_code == 200

    with sql_runtime() as session:
        messages = session.scalars(select(MessageRecord).order_by(MessageRecord.created_at)).all()
        shipments = session.scalars(select(ShipmentRequestRecord)).all()
        events = session.scalars(select(EventLogRecord).order_by(EventLogRecord.occurred_at)).all()

    assert [message.raw_content for message in messages if message.direction == "inbound"] == [
        "1",
        "son 50 cabezas de vacas",
        "Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio",
        "confirmo",
    ]
    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment.status == "PUBLISHED"
    assert shipment.livestock_type == "vacas"
    assert shipment.quantity_estimate == Decimal("50")
    assert shipment.date_window_start == datetime(2026, 6, 15, 8, 0)
    assert shipment.operational_notes == (
        "son 50 cabezas de vacas Salimos desde cordoba capital, hasta la plata, buenos aires, el 15 de junio"
    )
    assert "SHIPMENT_DRAFT_CREATED_FROM_CHAT" in [event.event_type for event in events]
    assert "LOAD_SELF_PUBLISHED" in [event.event_type for event in events]

    overview_response = client.get("/api/v1/backoffice/overview", headers=OPERATOR_HEADERS)
    assert overview_response.status_code == 200
    assert overview_response.json()["total_shipments"] == 1
    assert overview_response.json()["published_shipments"] == 1
    assert overview_response.json()["unassigned_published_shipments"] == 1

    unassigned_response = client.get(
        "/api/v1/backoffice/shipments/unassigned",
        headers=OPERATOR_HEADERS,
    )
    assert unassigned_response.status_code == 200
    payload = unassigned_response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == shipment.id
    assert payload[0]["origin"] == "Córdoba"
    assert payload[0]["destination"] == "la plata, buenos aires"
    assert payload[0]["status"] == "PUBLISHED"


def test_kapso_webhook_sql_backend_keeps_only_latest_confirmed_load_notes_in_shipment_detail(
    sql_runtime: sessionmaker[Session],
) -> None:
    client = TestClient(app)

    for idempotency_key, provider_message_id, text in [
        ("evt_clean_notes_1", "wamid_clean_notes_1", "Necesito llevar 3 toneladas de soja de buenos aires a cordoba el 20 de junio"),
        ("evt_clean_notes_2", "wamid_clean_notes_2", "quiero cargar 5 toneladas de soja desde santa fe a misiones el 25 de junio"),
        ("evt_clean_notes_3", "wamid_clean_notes_3", "perdon el 25 de julio"),
        ("evt_clean_notes_4", "wamid_clean_notes_4", "1"),
        ("evt_clean_notes_5", "wamid_clean_notes_5", "quiero cargar 13 toneladas de soja desde santa fe a misiones el 10 de agosto"),
        ("evt_clean_notes_6", "wamid_clean_notes_6", "confirmo"),
    ]:
        response = post_kapso(
            client,
            kapso_payload(
                idempotency_key=idempotency_key,
                provider_message_id=provider_message_id,
                text=text,
            ),
        )
        assert response.status_code == 200

    with sql_runtime() as session:
        shipments = session.scalars(
            select(ShipmentRequestRecord).order_by(ShipmentRequestRecord.created_at.desc())
        ).all()

    shipment = shipments[0]

    assert shipment.operational_notes == "quiero cargar 13 toneladas de soja desde santa fe a misiones el 10 de agosto"

    detail_response = client.get(
        f"/api/v1/backoffice/shipments/{shipment.id}",
        headers=OPERATOR_HEADERS,
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["shipment"]["source_message_preview"] == (
        "quiero cargar 13 toneladas de soja desde santa fe a misiones el 10 de agosto"
    )
    assert detail_payload["shipment"]["operational_notes"] == (
        "quiero cargar 13 toneladas de soja desde santa fe a misiones el 10 de agosto"
    )


def test_kapso_webhook_sql_backend_allows_known_carrier_number_to_create_producer_load_when_no_active_carrier_shipment(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(
            Carrier(id="car_sql_known_contact", name="SQL Known Contact", contact_phone="+5491111111111")
        )
        session.commit()

    client = TestClient(app)

    step_1 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_known_contact_1",
            provider_message_id="wamid_known_contact_1",
            text="Hola que tal",
        ),
    )
    step_2 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_known_contact_2",
            provider_message_id="wamid_known_contact_2",
            text="1",
        ),
    )
    step_3 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_known_contact_3",
            provider_message_id="wamid_known_contact_3",
            text="Necesito llevar 50 cabezas de vacas desde cordoba capital a buenos aires el 15 de julio",
        ),
    )
    step_4 = post_kapso(
        client,
        kapso_payload(
            idempotency_key="evt_known_contact_4",
            provider_message_id="wamid_known_contact_4",
            text="1",
        ),
    )

    assert step_1.status_code == 200
    assert step_2.status_code == 200
    assert step_3.status_code == 200
    assert step_4.status_code == 200

    with sql_runtime() as session:
        messages = session.scalars(select(MessageRecord).order_by(MessageRecord.created_at)).all()
        shipments = session.scalars(select(ShipmentRequestRecord)).all()
        events = session.scalars(select(EventLogRecord).order_by(EventLogRecord.occurred_at)).all()

    assert [message.raw_content for message in messages if message.direction == "inbound"] == [
        "Hola que tal",
        "1",
        "Necesito llevar 50 cabezas de vacas desde cordoba capital a buenos aires el 15 de julio",
        "1",
    ]
    assert [message.sender_type for message in messages if message.direction == "inbound"] == [
        "Carrier",
        "Carrier",
        "Producer",
        "Producer",
    ]
    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment.status == "PUBLISHED"
    assert shipment.livestock_type == "vacas"
    assert shipment.quantity_estimate == Decimal("50")
    assert shipment.operational_notes == "Necesito llevar 50 cabezas de vacas desde cordoba capital a buenos aires el 15 de julio"
    assert "SHIPMENT_DRAFT_CREATED_FROM_CHAT" in [event.event_type for event in events]
    assert "LOAD_SELF_PUBLISHED" in [event.event_type for event in events]


def test_kapso_webhook_sql_backend_persists_media_asset_and_carrier_document(
    sql_runtime: sessionmaker[Session],
) -> None:
    with sql_runtime() as session:
        SqlCarrierRepository(session).add(
            Carrier(id="car_sql_media", name="SQL Media", contact_phone="+5491111111111")
        )
        session.commit()
    client = TestClient(app)
    payload = kapso_payload(
        idempotency_key="evt_sql_media",
        provider_message_id="wamid_sql_media",
        text="licencia profesional",
    )
    payload["payload"] = {
        "type": "document",
        "caption": "licencia profesional",
        "document": {
            "id": "kapso_sql_media_1",
            "url": "https://kapso.example/media/licencia.pdf",
            "mime_type": "application/pdf",
            "filename": "licencia.pdf",
        },
    }

    response = post_kapso(client, payload)

    assert response.status_code == 200
    with sql_runtime() as session:
        messages = session.scalars(select(MessageRecord)).all()
        media_assets = session.scalars(select(MediaAssetRecord)).all()
        documents = session.scalars(select(DocumentRecord)).all()

    inbound = [message for message in messages if message.direction == "inbound"]
    assert len(inbound) == 1
    assert inbound[0].message_type == "document"
    assert len(media_assets) == 1
    assert media_assets[0].message_id == inbound[0].id
    assert media_assets[0].provider_media_id == "kapso_sql_media_1"
    assert len(documents) == 1
    assert documents[0].entity_id == "car_sql_media"
    assert documents[0].document_type == "licencia"
    assert documents[0].provider_media_id == "kapso_sql_media_1"
