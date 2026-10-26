import json
from datetime import UTC, datetime

import httpx

from app.application.interactive import build_text_fallback, prepare_outbound_message
from app.application.notifications import NotificationService
from app.domain.events import EventLogService
from app.domain.models import ShipmentRequest
from app.infrastructure.adapters.kapso import KapsoProvider
from app.infrastructure.adapters.whatsapp import OutboundAction, OutboundMessage, ProviderCapabilities


def test_outbound_action_serializes_to_metadata() -> None:
    action = OutboundAction(
        id="yes",
        label="Sí",
        value="yes",
        metadata={"flow": "carrier_onboarding"},
    )

    assert action.as_metadata() == {
        "id": "yes",
        "label": "Sí",
        "value": "yes",
        "kind": "quick_reply",
        "metadata": {"flow": "carrier_onboarding"},
    }


def test_text_fallback_numbers_actions_centrally() -> None:
    body = build_text_fallback(
        "¿Tenés empresa?",
        (
            OutboundAction(id="yes", label="Sí", value="yes"),
            OutboundAction(id="no", label="No", value="no"),
        ),
    )

    assert body == (
        "¿Tenés empresa?\n\n"
        "1. Sí\n"
        "2. No\n\n"
        "Respondé con el número o el texto de la opción."
    )


def test_prepare_outbound_uses_fallback_when_provider_has_no_interactive_support() -> None:
    message, delivery = prepare_outbound_message(
        OutboundMessage(
            conversation_id="conv_1",
            body="¿Qué querés hacer?",
            actions=(
                OutboundAction(id="shipper", label="Tengo carga", value="PRODUCER_LOAD"),
                OutboundAction(id="carrier", label="Soy transportista", value="CARRIER"),
                OutboundAction(id="empty_return", label="Vuelvo vacío", value="EMPTY_RETURN"),
            ),
        ),
        ProviderCapabilities(),
    )

    assert delivery == "text_fallback"
    assert message.message_type == "text"
    assert message.body.endswith("Respondé con el número o el texto de la opción.")
    assert message.metadata["interactive_delivery"] == "text_fallback"
    assert message.metadata["interactive_actions"][0]["value"] == "PRODUCER_LOAD"


def test_prepare_outbound_keeps_buttons_when_provider_supports_interactive() -> None:
    message, delivery = prepare_outbound_message(
        OutboundMessage(
            conversation_id="conv_1",
            body="Confirmo la ruta detectada: Corrientes Capital → Buenos Aires",
            actions=(
                OutboundAction(id="confirm", label="Confirmar", value="CONFIRM"),
                OutboundAction(id="correct", label="Corregir", value="CORRECT"),
            ),
        ),
        ProviderCapabilities(supports_interactive_messages=True, supports_buttons=True),
    )

    assert delivery == "buttons"
    assert message.message_type == "interactive"
    assert message.body.startswith("Confirmo la ruta")
    assert message.metadata["interactive_delivery"] == "buttons"


def test_prepare_outbound_uses_interactive_list_for_five_option_menu() -> None:
    actions = tuple(
        OutboundAction(id=f"choice_{index}", label=f"Opción {index}", value=f"opcion {index}")
        for index in range(1, 6)
    )

    message, delivery = prepare_outbound_message(
        OutboundMessage(conversation_id="conv_1", body="¿Qué querés hacer?", actions=actions),
        ProviderCapabilities(
            supports_interactive_messages=True,
            supports_buttons=True,
            supports_list_messages=True,
        ),
    )

    assert delivery == "list"
    assert message.message_type == "interactive_list"
    assert message.body == "¿Qué querés hacer?"
    assert message.metadata["interactive_delivery"] == "list"


def test_kapso_interactive_list_payload_contains_all_action_ids() -> None:
    provider = KapsoProvider(webhook_secret="secret", interactive_enabled=True)
    payload = provider._whatsapp_payload(
        OutboundMessage(
            conversation_id="+5491111111111",
            body="¿Qué querés hacer?",
            message_type="interactive_list",
            actions=tuple(
                OutboundAction(id=f"choice_{index}", label=f"Opción {index}", value=f"opcion {index}")
                for index in range(1, 6)
            ),
        )
    )

    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["action"]["button"] == "Ver opciones"
    assert [row["id"] for row in payload["interactive"]["action"]["sections"][0]["rows"]] == [
        f"choice_{index}" for index in range(1, 6)
    ]


def test_kapso_parses_interactive_list_reply() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    selection = provider._extract_action_selection(
        {"interactive": {"list_reply": {"id": "ver_viaje", "title": "Ver mi viaje"}}}
    )

    assert selection is not None
    assert selection.id == "ver_viaje"
    assert selection.value == "ver_viaje"
    assert selection.label == "Ver mi viaje"


def test_kapso_interactive_disabled_uses_notification_fallback() -> None:
    event_log = EventLogService()
    provider = KapsoProvider(webhook_secret="secret", interactive_enabled=False)
    service = NotificationService(provider=provider, event_log=event_log)

    result = service.send_new_load_alert(
        shipment=ShipmentRequest(
            id="sr_interactive_fallback",
            livestock_type="novillos",
            quantity_estimate=35,
            date_window_start=datetime(2026, 5, 2, 8, 30, tzinfo=UTC),
        ),
        carrier_id="+5491111111111",
        operator_user_id=None,
    )

    assert result.status == "sent"
    assert provider.sent_messages[0].message_type == "text"
    assert "1. Me interesa" in provider.sent_messages[0].body
    assert event_log.events[-1].payload["interactive_delivery"] == "text_fallback"


def test_kapso_interactive_enabled_generates_button_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid_buttons"}]})

    provider = KapsoProvider(
        webhook_secret="secret",
        api_key="test-key",
        base_url="https://kapso.example.test",
        phone_number_id="phone_number_1",
        interactive_enabled=True,
        enable_real_outbound=True,
        allowlist={"+5491111111111"},
        enforce_allowlist=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    service = NotificationService(provider=provider, event_log=EventLogService())

    result = service.send_new_load_alert(
        shipment=ShipmentRequest(id="sr_buttons", livestock_type="novillos", quantity_estimate=35),
        carrier_id="+5491111111111",
        operator_user_id=None,
    )

    assert result.status == "sent"
    payload = json.loads(requests[0].content)
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "button"
    assert payload["interactive"]["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "interested", "title": "Me interesa"}},
        {"type": "reply", "reply": {"id": "declined", "title": "No puedo"}},
        {"type": "reply", "reply": {"id": "more_info", "title": "Más info"}},
    ]
