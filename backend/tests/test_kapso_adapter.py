import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from app.infrastructure.adapters.idempotency import InMemoryIdempotencyStore
from app.infrastructure.adapters.kapso import KapsoProvider, WebhookPayloadError, WebhookSignatureError
from app.infrastructure.adapters.whatsapp import OutboundMessage, WhatsAppProvider


def signed_headers(raw_body: bytes, secret: str, timestamp: str | None = None) -> dict[str, str]:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    headers = {"X-Webhook-Signature": f"sha256={digest}"}
    if timestamp is not None:
        headers["x-kapso-timestamp"] = timestamp
    return headers


def kapso_docs_signed_headers(payload: object, secret: str) -> dict[str, str]:
    canonical_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), canonical_body, hashlib.sha256).hexdigest()
    return {"X-Webhook-Signature": f"sha256={digest}"}


def test_kapso_provider_satisfies_whatsapp_provider_contract() -> None:
    provider: WhatsAppProvider = KapsoProvider(webhook_secret="secret")

    assert provider.provider_name == "kapso"


def test_verify_and_normalize_inbound_event() -> None:
    secret = "secret"
    payload = {
        "event_type": "message.received",
        "idempotency_key": "evt_1",
        "provider_message_id": "wamid_1",
        "conversation_id": "conv_1",
        "workflow_execution_id": "wf_1",
        "phone_number": "+549...",
        "payload": {"text": "Necesito camion"},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    provider = KapsoProvider(webhook_secret=secret)

    event = provider.verify_and_normalize(
        raw_body=raw_body,
        headers=signed_headers(raw_body, secret),
    )

    assert event.provider == "kapso"
    assert event.event_type == "message.received"
    assert event.idempotency_key == "evt_1"
    assert event.provider_message_id == "wamid_1"
    assert event.conversation_id == "conv_1"
    assert event.workflow_execution_id == "wf_1"
    assert event.text == "Necesito camion"
    assert event.correlation_id.startswith("corr_")


def test_verify_and_normalize_accepts_kapso_docs_json_payload_signature() -> None:
    secret = "secret"
    payload = {
        "event_type": "message.received",
        "idempotency_key": "evt_docs_signature",
        "provider_message_id": "wamid_docs_signature",
        "conversation_id": "conv_1",
        "payload": {"text": "Necesito camión"},
    }
    raw_body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    provider = KapsoProvider(webhook_secret=secret)

    event = provider.verify_and_normalize(
        raw_body=raw_body,
        headers=kapso_docs_signed_headers(payload, secret),
    )

    assert event.idempotency_key == "evt_docs_signature"
    assert event.text == "Necesito camión"


def test_normalize_inbound_supports_nested_kapso_message_payload() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "event": "message.received",
        "data": {
            "message": {
                "id": "wamid_nested",
                "text": {"body": "35 novillos de Azul a Liniers"},
                "from": "+5491111111111",
            },
            "conversation": {"id": "conv_nested"},
            "contact": {"id": "contact_nested", "phone_number": "+5491111111111"},
            "timestamp": "2026-05-01T12:00:00Z",
        },
    }

    event = provider.normalize_inbound(payload=payload, headers={})

    assert event.event_type == "message.received"
    assert event.provider_message_id == "wamid_nested"
    assert event.conversation_id == "conv_nested"
    assert event.provider_contact_id == "contact_nested"
    assert event.phone_number == "+5491111111111"
    assert event.text == "35 novillos de Azul a Liniers"


def test_normalize_inbound_extracts_document_media_from_payload_container() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "event_type": "message.received",
        "idempotency_key": "evt_media_doc",
        "provider_message_id": "wamid_media_doc",
        "phone_number": "+5491111111111",
        "payload": {
            "type": "document",
            "caption": "cedula verde",
            "media": {
                "id": "media_doc_1",
                "url": "https://kapso.example/media/doc_1",
                "mime_type": "application/pdf",
                "filename": "cedula.pdf",
                "sha256": "abc123",
            },
        },
    }

    event = provider.normalize_inbound(payload=payload, headers={})

    assert event.media is not None
    assert event.media.media_type == "document"
    assert event.media.provider_media_id == "media_doc_1"
    assert event.media.external_url == "https://kapso.example/media/doc_1"
    assert event.media.mime_type == "application/pdf"
    assert event.media.file_name == "cedula.pdf"
    assert event.media.sha256 == "abc123"
    assert event.media.caption == "cedula verde"
    assert event.text == "cedula verde"


def test_normalize_inbound_extracts_image_media_from_nested_message() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "event": "message.received",
        "data": {
            "message": {
                "id": "wamid_media_img",
                "type": "image",
                "from": "+5491111111111",
                "image": {
                    "id": "media_img_1",
                    "url": "https://kapso.example/media/dni.jpg",
                    "mime_type": "image/jpeg",
                    "caption": "DNI frente",
                },
            },
            "conversation": {"id": "conv_media_img"},
            "contact": {"id": "contact_media_img", "phone_number": "+5491111111111"},
        },
    }

    event = provider.normalize_inbound(payload=payload, headers={})

    assert event.media is not None
    assert event.media.media_type == "image"
    assert event.media.provider_media_id == "media_img_1"
    assert event.media.external_url == "https://kapso.example/media/dni.jpg"
    assert event.media.mime_type == "image/jpeg"
    assert event.media.caption == "DNI frente"
    assert event.text == "DNI frente"


def test_normalize_inbound_supports_meta_messages_from_and_contacts_wa_id() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "541135690073"}],
                            "messages": [
                                {
                                    "id": "wamid_meta_1",
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

    event = provider.normalize_inbound(
        payload=payload,
        headers={"X-Webhook-Event": "message.received", "X-Idempotency-Key": "evt_meta_1"},
    )

    assert event.provider_message_id == "wamid_meta_1"
    assert event.provider_contact_id == "541135690073"
    assert event.phone_number == "541135690073"
    assert event.text == "1"


def test_normalize_inbound_extracts_interactive_button_reply() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "event_type": "message.received",
        "idempotency_key": "evt_button_reply",
        "provider_message_id": "wamid_button_reply",
        "phone_number": "+5491111111111",
        "payload": {
            "interactive": {
                "type": "button_reply",
                "button_reply": {
                    "id": "yes",
                    "title": "Sí",
                },
            }
        },
    }

    event = provider.normalize_inbound(payload=payload, headers={})

    assert event.action_selection is not None
    assert event.action_selection.id == "yes"
    assert event.action_selection.value == "yes"
    assert event.action_selection.label == "Sí"
    assert event.text == "yes"


def test_normalize_inbound_supports_header_event_and_whatsapp_message_payload() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "data": {
            "id": "evt_real_1",
            "whatsapp_message": {
                "id": "wamid_whatsapp",
                "text": "Necesito camion",
                "from": "+5491111111111",
            },
            "conversation": {"id": "conv_whatsapp"},
            "contact": {"id": "contact_whatsapp"},
        },
    }

    event = provider.normalize_inbound(
        payload=payload,
        headers={"X-Webhook-Event": "message.received"},
    )

    assert event.event_type == "message.received"
    assert event.idempotency_key
    assert event.provider_message_id == "wamid_whatsapp"
    assert event.conversation_id == "conv_whatsapp"
    assert event.provider_contact_id == "contact_whatsapp"
    assert event.text == "Necesito camion"


def test_invalid_hmac_signature_is_rejected() -> None:
    provider = KapsoProvider(webhook_secret="secret")

    with pytest.raises(WebhookSignatureError):
        provider.verify_webhook_signature(
            raw_body=b"{}",
            headers={"X-Webhook-Signature": "sha256=bad"},
        )


def test_legacy_kapso_signature_header_is_still_accepted() -> None:
    secret = "secret"
    raw_body = b"{}"
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provider = KapsoProvider(webhook_secret=secret)

    provider.verify_webhook_signature(
        raw_body=raw_body,
        headers={"x-kapso-signature": f"sha256={digest}"},
    )


def test_stale_kapso_timestamp_is_rejected_when_header_is_present() -> None:
    secret = "secret"
    raw_body = b"{}"
    provider = KapsoProvider(webhook_secret=secret)

    with pytest.raises(WebhookSignatureError, match="outside replay window"):
        provider.verify_webhook_signature(
            raw_body=raw_body,
            headers=signed_headers(raw_body, secret, "2000-01-01T00:00:00Z"),
        )


def test_fresh_kapso_timestamp_is_accepted_when_header_is_present() -> None:
    secret = "secret"
    raw_body = b"{}"
    provider = KapsoProvider(webhook_secret=secret)
    timestamp = datetime.now(UTC).isoformat()

    provider.verify_webhook_signature(
        raw_body=raw_body,
        headers=signed_headers(raw_body, secret, timestamp),
    )


def test_missing_required_payload_fields_are_rejected() -> None:
    provider = KapsoProvider(webhook_secret="secret")

    with pytest.raises(WebhookPayloadError):
        provider.normalize_inbound(payload={"idempotency_key": "evt_1"}, headers={})


def test_idempotency_detects_duplicate_provider_key() -> None:
    store = InMemoryIdempotencyStore()
    provider = KapsoProvider(webhook_secret="secret", idempotency_store=store)
    payload = {
        "event_type": "message.received",
        "idempotency_key": "evt_1",
        "provider_message_id": "wamid_1",
    }

    first = provider.normalize_inbound(payload=payload, headers={})
    duplicate = provider.check_idempotency(first.idempotency_key)

    assert duplicate.is_duplicate is True


def test_fallback_idempotency_key_uses_stable_external_fields() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    payload = {
        "event_type": "message.received",
        "provider_message_id": "wamid_1",
        "conversation_id": "conv_1",
        "occurred_at": "2026-04-25T20:00:00Z",
    }

    first = provider.normalize_inbound(payload=payload, headers={})
    second = provider.normalize_inbound(payload=payload, headers={})

    assert first.idempotency_key == second.idempotency_key


def test_out_of_order_webhooks_normalize_without_state_assumptions() -> None:
    provider = KapsoProvider(webhook_secret="secret")
    later_payload = {
        "event_type": "message.received",
        "provider_message_id": "wamid_later",
        "conversation_id": "conv_1",
        "occurred_at": "2026-04-25T20:10:00Z",
        "payload": {"text": "si"},
    }
    earlier_payload = {
        "event_type": "message.received",
        "provider_message_id": "wamid_earlier",
        "conversation_id": "conv_1",
        "occurred_at": "2026-04-25T20:00:00Z",
        "payload": {"text": "puede ser"},
    }

    later = provider.normalize_inbound(payload=later_payload, headers={})
    earlier = provider.normalize_inbound(payload=earlier_payload, headers={})

    assert later.conversation_id == earlier.conversation_id == "conv_1"
    assert later.text == "si"
    assert earlier.text == "puede ser"
    assert later.idempotency_key != earlier.idempotency_key


def test_send_message_is_mockable_and_does_not_touch_domain() -> None:
    provider = KapsoProvider(webhook_secret="secret")

    result = provider.send_message(
        OutboundMessage(
            conversation_id="conv_1",
            body="Mensaje operativo",
            correlation_id="corr_1",
        )
    )

    assert result.accepted is True
    assert result.provider == "kapso"
    assert result.provider_message_id is not None
    assert provider.sent_messages[0].body == "Mensaje operativo"
