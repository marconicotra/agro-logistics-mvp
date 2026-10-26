import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from app.infrastructure.adapters.idempotency import InMemoryIdempotencyStore, IdempotencyResult
from app.infrastructure.adapters.whatsapp import (
    InboundActionSelection,
    InboundMedia,
    NormalizedInboundEvent,
    OutboundMessage,
    OutboundResult,
    ProviderCapabilities,
)

logger = logging.getLogger(__name__)


class WebhookSignatureError(ValueError):
    pass


class WebhookPayloadError(ValueError):
    pass


class KapsoConfigurationError(RuntimeError):
    pass


class KapsoOutboundError(RuntimeError):
    pass


class KapsoProvider:
    provider_name = "kapso"

    def __init__(
        self,
        *,
        webhook_secret: str,
        idempotency_store: InMemoryIdempotencyStore | None = None,
        replay_window_seconds: int = 300,
        api_key: str | None = None,
        base_url: str | None = None,
        phone_number_id: str | None = None,
        send_message_path: str = "/messages",
        new_load_template_name: str | None = None,
        allow_test_run_freeform_new_loads: bool = False,
        template_language_code: str = "es_AR",
        interactive_enabled: bool = False,
        enable_real_outbound: bool = False,
        allowlist: set[str] | None = None,
        enforce_allowlist: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._webhook_secret = webhook_secret
        self._idempotency_store = idempotency_store or InMemoryIdempotencyStore()
        self._replay_window_seconds = replay_window_seconds
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") if base_url else None
        self._phone_number_id = phone_number_id.strip("/") if phone_number_id else None
        self._send_message_path = send_message_path
        self._new_load_template_name = new_load_template_name
        self._allow_test_run_freeform_new_loads = allow_test_run_freeform_new_loads
        self._template_language_code = template_language_code
        self._interactive_enabled = interactive_enabled
        self._enable_real_outbound = enable_real_outbound
        self._allowlist = allowlist or set()
        self._enforce_allowlist = enforce_allowlist
        self._http_client = http_client or httpx.Client(timeout=10)
        self.sent_messages: list[OutboundMessage] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_interactive_messages=self._interactive_enabled,
            supports_buttons=self._interactive_enabled,
            supports_list_messages=self._interactive_enabled,
        )

    @property
    def outbound_scope(self) -> str | None:
        """Non-secret phone-number identifier used to prevent cross-account dispatch."""
        return self._phone_number_id

    def verify_webhook_signature(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> None:
        signature_header = self._signature_header(headers)
        signature = signature_header[1] if signature_header else None
        logger.info(
            "kapso_webhook_signature_header_present header=%s signature_length=%s",
            signature_header[0] if signature_header else "none",
            len(signature) if signature else 0,
        )
        if not signature:
            raise WebhookSignatureError("Missing KAPSO webhook signature")

        canonical_json_body = self._canonical_json_body(raw_body)
        if canonical_json_body is not None and self._signature_matches(signature, canonical_json_body):
            logger.info("kapso_webhook_signature_validated method=json_payload")
            self._validate_replay_window(headers)
            return

        if self._signature_matches(signature, raw_body):
            logger.info("kapso_webhook_signature_validated method=raw_body")
            self._validate_replay_window(headers)
            return

        raise WebhookSignatureError("Invalid KAPSO webhook signature")

    def normalize_inbound(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> NormalizedInboundEvent:
        event_type = self._extract_event_type(payload, headers)
        provider_message_id = self._extract_provider_message_id(payload)
        conversation_id = self._extract_conversation_id(payload)
        provider_contact_id = self._extract_provider_contact_id(payload)
        occurred_at = self._extract_occurred_at(payload)
        idempotency_key = self._idempotency_key(
            payload,
            event_type=event_type,
            provider_message_id=provider_message_id,
            conversation_id=conversation_id,
            occurred_at=occurred_at,
        )
        correlation_id = self._optional_str(payload.get("correlation_id")) or f"corr_{uuid4().hex}"

        idempotency = self.check_idempotency(idempotency_key)
        if idempotency.is_duplicate:
            logger.info(
                "kapso_webhook_duplicate provider=%s idempotency_key=%s correlation_id=%s",
                self.provider_name,
                idempotency.key,
                correlation_id,
            )

        normalized = NormalizedInboundEvent(
            provider=self.provider_name,
            event_type=event_type,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            conversation_id=conversation_id,
            workflow_execution_id=self._extract_workflow_execution_id(payload),
            provider_contact_id=provider_contact_id,
            provider_message_id=provider_message_id,
            phone_number=self._extract_phone_number(payload),
            occurred_at=occurred_at,
            text=self._extract_text(payload),
            location=self._extract_location(payload),
            reply_to_message_id=self._extract_reply_context(payload),
            media=self._extract_media(payload),
            action_selection=self._extract_action_selection(payload),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else payload,
        )
        logger.info(
            "kapso_webhook_normalized event_type=%s correlation_id=%s provider_message_id=%s",
            normalized.event_type,
            normalized.correlation_id,
            normalized.provider_message_id,
        )
        return normalized

    def check_idempotency(self, idempotency_key: str) -> IdempotencyResult:
        return self._idempotency_store.check_and_store(
            provider=self.provider_name,
            idempotency_key=idempotency_key,
        )

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        if self._enable_real_outbound:
            if self._should_send_new_load_template_directly(message):
                return self._send_real_template_message(message, fallback_used=False)
            return self._send_real_message(message)
        self.sent_messages.append(message)
        provider_message_id = f"kapso_msg_{uuid4().hex}"
        logger.info(
            "kapso_outbound_queued conversation_id=%s correlation_id=%s",
            message.conversation_id,
            message.correlation_id,
        )
        return OutboundResult(
            provider=self.provider_name,
            accepted=True,
            provider_message_id=provider_message_id,
            correlation_id=message.correlation_id,
            payload={
                "conversation_id": message.conversation_id,
                "message_type": message.message_type,
            },
        )

    def _send_real_message(self, message: OutboundMessage) -> OutboundResult:
        self._validate_real_outbound_config()
        self._validate_allowlist(message)
        assert self._base_url is not None
        assert self._api_key is not None
        assert self._phone_number_id is not None
        url = self._outbound_messages_url()
        payload = self._whatsapp_payload(message)
        try:
            response = self._http_client.post(
                url,
                json=payload,
                headers={
                    "x-api-key": self._api_key,
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if self._should_retry_with_new_load_template(message, exc.response):
                return self._send_real_template_message(message)
            raise KapsoOutboundError(
                f"KAPSO outbound request failed status_code={exc.response.status_code} "
                f"response={self._safe_response_summary(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise KapsoOutboundError(f"KAPSO outbound request failed error={exc.__class__.__name__}") from exc

        response_payload = self._parse_response_payload(response)
        response_payload["attempt_type"] = "text"
        provider_message_id = self._extract_provider_message_id(response_payload)
        return OutboundResult(
            provider=self.provider_name,
            accepted=True,
            provider_message_id=provider_message_id,
            correlation_id=message.correlation_id,
            payload=response_payload,
        )

    def _send_real_template_message(
        self,
        message: OutboundMessage,
        *,
        fallback_used: bool = True,
    ) -> OutboundResult:
        assert self._base_url is not None
        assert self._api_key is not None
        url = self._outbound_messages_url()
        payload = self._whatsapp_new_load_template_payload(message)
        try:
            response = self._http_client.post(
                url,
                json=payload,
                headers={
                    "x-api-key": self._api_key,
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KapsoOutboundError(
                f"KAPSO template outbound request failed fallback_used={str(fallback_used).lower()} "
                f"status_code={exc.response.status_code} "
                f"response={self._safe_response_summary(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise KapsoOutboundError(
                f"KAPSO template outbound request failed fallback_used={str(fallback_used).lower()} "
                f"error={exc.__class__.__name__}"
            ) from exc

        response_payload = self._parse_response_payload(response)
        response_payload["attempt_type"] = "template"
        response_payload["template_fallback_used"] = fallback_used
        response_payload["template_name"] = self._new_load_template_name
        provider_message_id = self._extract_provider_message_id(response_payload)
        return OutboundResult(
            provider=self.provider_name,
            accepted=True,
            provider_message_id=provider_message_id,
            correlation_id=message.correlation_id,
            payload=response_payload,
        )

    def _validate_real_outbound_config(self) -> None:
        missing = []
        if not self._api_key:
            missing.append("KAPSO_API_KEY")
        if not self._base_url:
            missing.append("KAPSO_BASE_URL")
        if not self._phone_number_id:
            missing.append("KAPSO_PHONE_NUMBER_ID")
        if not self._webhook_secret:
            missing.append("KAPSO_WEBHOOK_SECRET")
        if missing:
            raise KapsoConfigurationError(f"Missing KAPSO outbound configuration: {', '.join(missing)}")

    def _outbound_messages_url(self) -> str:
        assert self._base_url is not None
        assert self._phone_number_id is not None
        return f"{self._base_url}/{self._phone_number_id}/{self._send_message_path.lstrip('/')}"

    def _whatsapp_payload(self, message: OutboundMessage) -> dict[str, Any]:
        if message.message_type == "location_request":
            return {"messaging_product": "whatsapp", "to": self._whatsapp_recipient(message), "type": "interactive",
                    "interactive": {"type": "location_request_message", "body": {"text": message.body}, "action": {"name": "send_location"}}}

        if (
            self._interactive_enabled
            and message.actions
            and message.message_type == "interactive"
            and len(message.actions) <= 3
        ):
            return self._whatsapp_button_payload(message)
        if (
            self._interactive_enabled
            and message.actions
            and message.message_type == "interactive_list"
            and len(message.actions) <= 10
        ):
            return self._whatsapp_list_payload(message)
        return self._whatsapp_text_payload(message)

    def _whatsapp_text_payload(self, message: OutboundMessage) -> dict[str, Any]:
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._whatsapp_recipient(message),
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message.body,
            },
        }

    def _whatsapp_button_payload(self, message: OutboundMessage) -> dict[str, Any]:
        # TODO: confirm exact KAPSO wrapper for WhatsApp interactive messages.
        # This shape follows WhatsApp Cloud API and is guarded by KAPSO_INTERACTIVE_ENABLED.
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._whatsapp_recipient(message),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": message.body},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": action.id,
                                "title": action.label[:20],
                            },
                        }
                        for action in message.actions
                    ]
                },
            },
        }

    def _whatsapp_list_payload(self, message: OutboundMessage) -> dict[str, Any]:
        # WhatsApp list messages support up to 10 rows in one section.
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._whatsapp_recipient(message),
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": message.body},
                "action": {
                    "button": "Ver opciones",
                    "sections": [
                        {
                            "title": "Opciones",
                            "rows": [
                                {
                                    "id": action.id,
                                    "title": action.label[:24],
                                    **(
                                        {"description": str(action.metadata["description"])[:72]}
                                        if action.metadata.get("description")
                                        else {}
                                    ),
                                }
                                for action in message.actions
                            ],
                        }
                    ],
                },
            },
        }

    def _whatsapp_new_load_template_payload(self, message: OutboundMessage) -> dict[str, Any]:
        assert self._new_load_template_name is not None
        template: dict[str, Any] = {
            "name": self._new_load_template_name,
            "language": {"code": self._template_language_code},
        }
        parameters = [
            {"type": "text", "text": str(value)}
            for value in message.metadata.get("template_body_parameters", [])
            if value is not None
        ]
        if parameters:
            template["components"] = [{"type": "body", "parameters": parameters}]
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._whatsapp_recipient(message),
            "type": "template",
            "template": template,
        }

    def _should_retry_with_new_load_template(self, message: OutboundMessage, response: httpx.Response) -> bool:
        return (
            message.metadata.get("notification_type") == "NEW_LOAD_ALERT"
            and bool(self._new_load_template_name)
            and self._looks_like_whatsapp_window_error(response)
        )

    def _should_send_new_load_template_directly(self, message: OutboundMessage) -> bool:
        return (
            not (
                self._allow_test_run_freeform_new_loads
                and bool(message.metadata.get("qa_test_run_id"))
            )
            and message.metadata.get("notification_type") == "NEW_LOAD_ALERT"
            and bool(self._new_load_template_name)
        )

    def _looks_like_whatsapp_window_error(self, response: httpx.Response) -> bool:
        if response.status_code not in {400, 422}:
            return False
        summary = self._safe_response_summary(response).lower()
        return "24-hour" in summary or "24 hour" in summary or "outside the 24" in summary

    def _whatsapp_recipient(self, message: OutboundMessage) -> str:
        destination = message.allowlist_phone_number or message.conversation_id
        return destination[1:] if destination.startswith("+") else destination

    def _validate_allowlist(self, message: OutboundMessage) -> None:
        if not self._enforce_allowlist:
            return
        recipient = message.allowlist_phone_number or message.conversation_id
        recipient_key = self._phone_match_key(recipient)
        if recipient_key is None or not any(
            self._phone_match_key(item) == recipient_key for item in self._allowlist
        ):
            raise KapsoOutboundError("Outbound WhatsApp destination is not in WHATSAPP_DEV_ALLOWLIST")

    def _phone_match_key(self, phone_number: str) -> str | None:
        digits = "".join(character for character in phone_number if character.isdigit())
        if not digits:
            return None
        if digits.startswith("549"):
            return f"54{digits[3:]}"
        if digits.startswith("54"):
            return f"54{digits[2:]}"
        return digits

    def _parse_response_payload(self, response: httpx.Response) -> dict[str, Any]:
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise KapsoOutboundError("KAPSO outbound response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise KapsoOutboundError("KAPSO outbound response must be a JSON object")
        return payload

    def _safe_response_summary(self, response: httpx.Response) -> str:
        if not response.content:
            return "<empty>"
        try:
            payload = response.json()
        except ValueError:
            return response.text[:300]
        return self._redact_sensitive_value(payload)[:300]

    def _redact_sensitive_value(self, value: object) -> str:
        if isinstance(value, dict):
            redacted: dict[str, object] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in ("token", "secret", "key", "authorization")):
                    redacted[str(key)] = "<redacted>"
                else:
                    redacted[str(key)] = item
            return json.dumps(redacted, separators=(",", ":"), ensure_ascii=False)
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    def verify_and_normalize(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> NormalizedInboundEvent:
        self.verify_webhook_signature(raw_body=raw_body, headers=headers)
        payload = json.loads(raw_body.decode("utf-8"))
        return self.normalize_inbound(payload=payload, headers=headers)

    def _idempotency_key(
        self,
        payload: dict[str, Any],
        *,
        event_type: str | None = None,
        provider_message_id: str | None = None,
        conversation_id: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        explicit_key = self._optional_str(payload.get("idempotency_key") or payload.get("_header_idempotency_key"))
        if explicit_key:
            return explicit_key

        if not provider_message_id:
            raise WebhookPayloadError("Missing idempotency data")

        parts = [
            provider_message_id,
            event_type or self._optional_str(payload.get("event_type")),
            occurred_at or self._extract_occurred_at(payload),
            conversation_id or self._extract_conversation_id(payload),
        ]
        fallback = ":".join(part or "" for part in parts)
        if not fallback.replace(":", ""):
            raise WebhookPayloadError("Missing idempotency data")
        return hashlib.sha256(fallback.encode("utf-8")).hexdigest()

    def _extract_event_type(self, payload: dict[str, Any], headers: dict[str, str]) -> str:
        event_type = self._optional_str(
            payload.get("event_type")
            or payload.get("event")
            or payload.get("type")
            or self._get_header(headers, "x-webhook-event")
        )
        if not event_type:
            raise WebhookPayloadError("event_type is required")
        return event_type

    def _extract_location(self, payload):
        from app.domain.routing import coordinates
        for container in [payload, *self._message_containers(payload)]:
            location = container.get("location")
            if isinstance(location, dict):
                try:
                    lat, lng = coordinates(float(location["latitude"]), float(location["longitude"]))
                except (ValueError, KeyError, TypeError):
                    raise WebhookPayloadError("Coordenadas de ubicación inválidas") from None
                return {"latitude": lat, "longitude": lng, "name": location.get("name"), "address": location.get("address")}
        return None

    def _extract_reply_context(self, payload):
        for container in [payload, *self._message_containers(payload)]:
            context = container.get("context")
            if isinstance(context, dict) and context.get("id"):
                return str(context["id"])
        return None

    def _extract_text(self, payload: dict[str, Any]) -> str | None:
        selected_action = self._extract_action_selection(payload)
        if selected_action is not None:
            return selected_action.value
        if isinstance(payload.get("text"), str):
            return payload["text"]
        data = self._dict_value(payload, "data")
        if data and isinstance(data.get("text"), str):
            return data["text"]
        nested_payload = payload.get("payload")
        if isinstance(nested_payload, dict) and isinstance(nested_payload.get("text"), str):
            return nested_payload["text"]
        if isinstance(nested_payload, dict) and isinstance(nested_payload.get("caption"), str):
            return nested_payload["caption"]
        for container in self._message_containers(payload):
            text = container.get("text")
            if isinstance(text, str):
                return text
            if isinstance(text, dict):
                body = text.get("body")
                if isinstance(body, str):
                    return body
            body = container.get("body")
            if isinstance(body, str):
                return body
            caption = container.get("caption")
            if isinstance(caption, str):
                return caption
            for key in ("image", "document", "audio", "video", "media"):
                media = self._dict_value(container, key)
                if media and isinstance(media.get("caption"), str):
                    return media["caption"]
        return None

    def _extract_action_selection(self, payload: dict[str, Any]) -> InboundActionSelection | None:
        for container in [payload, self._dict_value(payload, "payload") or {}, self._dict_value(payload, "data") or {}]:
            selection = self._action_selection_from_container(container)
            if selection is not None:
                return selection
        for container in self._message_containers(payload):
            selection = self._action_selection_from_container(container)
            if selection is not None:
                return selection
        return None

    def _action_selection_from_container(self, container: dict[str, Any]) -> InboundActionSelection | None:
        interactive = self._dict_value(container, "interactive")
        if interactive:
            button_reply = self._dict_value(interactive, "button_reply")
            if button_reply:
                return self._selection_from_reply(button_reply)
            list_reply = self._dict_value(interactive, "list_reply")
            if list_reply:
                return self._selection_from_reply(list_reply)

        # Kapso flow responses use their own wrapper; accept the common keys
        # emitted by flow nodes without requiring the WhatsApp webhook shape.
        flow_response = self._dict_value(container, "flow_response") or self._dict_value(container, "flowResponse")
        if flow_response:
            flow_data = self._dict_value(flow_response, "response_json") or self._dict_value(flow_response, "responseJson")
            if flow_data:
                value = self._optional_str(flow_data.get("value") or flow_data.get("id") or flow_data.get("choice"))
                label = self._optional_str(flow_data.get("label") or flow_data.get("title"))
                if value:
                    return InboundActionSelection(id=value, value=value, label=label, raw=flow_data)

        button = self._dict_value(container, "button")
        if button:
            return self._selection_from_reply(button)

        button_reply = self._dict_value(container, "button_reply")
        if button_reply:
            return self._selection_from_reply(button_reply)

        payload_value = container.get("payload") or container.get("selected_payload")
        payload = self._optional_str(payload_value) if isinstance(payload_value, str) else None
        if payload:
            return InboundActionSelection(
                id=payload,
                value=payload,
                label=self._optional_str(container.get("title") or container.get("label")),
                raw=container,
            )
        return None

    def _selection_from_reply(self, reply: dict[str, Any]) -> InboundActionSelection | None:
        action_id = self._optional_str(reply.get("id") or reply.get("payload") or reply.get("value"))
        if not action_id:
            return None
        value = self._optional_str(reply.get("value") or reply.get("payload") or reply.get("id")) or action_id
        return InboundActionSelection(
            id=action_id,
            value=value,
            label=self._optional_str(reply.get("title") or reply.get("label") or reply.get("text")),
            raw=reply,
        )

    def _extract_media(self, payload: dict[str, Any]) -> InboundMedia | None:
        for container in [payload, self._dict_value(payload, "payload") or {}, self._dict_value(payload, "data") or {}]:
            media = self._media_from_container(container)
            if media is not None:
                return media
        for container in self._message_containers(payload):
            media = self._media_from_container(container)
            if media is not None:
                return media
        return None

    def _media_from_container(self, container: dict[str, Any]) -> InboundMedia | None:
        explicit_type = self._optional_str(container.get("message_type") or container.get("type"))
        for media_key in ("document", "image", "audio", "video", "media"):
            media_payload = self._dict_value(container, media_key)
            if media_payload is None:
                continue
            media_type = self._normalize_media_type(explicit_type or media_key)
            return InboundMedia(
                media_type=media_type,
                provider_media_id=self._optional_str(
                    media_payload.get("id")
                    or media_payload.get("media_id")
                    or media_payload.get("provider_media_id")
                ),
                external_url=self._optional_str(
                    media_payload.get("url")
                    or media_payload.get("link")
                    or media_payload.get("external_url")
                ),
                mime_type=self._optional_str(
                    media_payload.get("mime_type")
                    or media_payload.get("mimeType")
                    or media_payload.get("content_type")
                ),
                file_name=self._optional_str(
                    media_payload.get("filename")
                    or media_payload.get("file_name")
                    or media_payload.get("name")
                ),
                sha256=self._optional_str(media_payload.get("sha256")),
                caption=self._optional_str(media_payload.get("caption") or container.get("caption")),
                raw=media_payload,
            )

        if explicit_type and self._normalize_media_type(explicit_type) != "unknown":
            return InboundMedia(
                media_type=self._normalize_media_type(explicit_type),
                provider_media_id=self._optional_str(
                    container.get("media_id") or container.get("provider_media_id")
                ),
                external_url=self._optional_str(
                    container.get("url") or container.get("link") or container.get("external_url")
                ),
                mime_type=self._optional_str(container.get("mime_type") or container.get("mimeType")),
                file_name=self._optional_str(container.get("filename") or container.get("file_name")),
                sha256=self._optional_str(container.get("sha256")),
                caption=self._optional_str(container.get("caption")),
                raw=container,
            )
        return None

    def _normalize_media_type(self, value: str | None) -> str:
        normalized = (value or "").lower()
        if normalized in {"image", "audio", "document", "video"}:
            return normalized
        if normalized in {"file", "application", "pdf"}:
            return "document"
        return "unknown"

    def _extract_provider_message_id(self, payload: dict[str, Any]) -> str | None:
        for key in ("provider_message_id", "message_id"):
            value = self._optional_str(payload.get(key))
            if value:
                return value
        for container in self._message_containers(payload):
            for key in ("provider_message_id", "message_id", "id"):
                value = self._optional_str(container.get(key))
                if value:
                    return value
        data = self._dict_value(payload, "data")
        if data:
            value = self._optional_str(data.get("provider_message_id") or data.get("message_id") or data.get("id"))
            if value:
                return value
        return self._optional_str(payload.get("id"))

    def _extract_conversation_id(self, payload: dict[str, Any]) -> str | None:
        direct = self._optional_str(payload.get("conversation_id"))
        if direct:
            return direct
        for container in (payload, self._dict_value(payload, "data") or {}):
            conversation = self._dict_value(container, "conversation")
            if conversation:
                value = self._optional_str(conversation.get("id") or conversation.get("conversation_id"))
                if value:
                    return value
            value = self._optional_str(container.get("provider_conversation_id") or container.get("conversation_id"))
            if value:
                return value
        for container in self._message_containers(payload):
            conversation = self._dict_value(container, "conversation")
            if conversation:
                value = self._optional_str(conversation.get("id") or conversation.get("conversation_id"))
                if value:
                    return value
            value = self._optional_str(container.get("conversation_id"))
            if value:
                return value
        return None

    def _extract_provider_contact_id(self, payload: dict[str, Any]) -> str | None:
        direct = self._optional_str(payload.get("provider_contact_id") or payload.get("contact_id"))
        if direct:
            return direct
        for container in (self._dict_value(payload, "data"), self._dict_value(payload, "payload")):
            if not container:
                continue
            direct = self._optional_str(container.get("provider_contact_id") or container.get("contact_id"))
            if direct:
                return direct
            contact = self._dict_value(container, "contact")
            if contact:
                value = self._optional_str(contact.get("provider_contact_id") or contact.get("contact_id") or contact.get("id"))
                if value:
                    return value
        contact = self._dict_value(payload, "contact")
        if contact:
            return self._optional_str(
                contact.get("provider_contact_id") or contact.get("contact_id") or contact.get("id")
            )
        for contact_item in self._contact_containers(payload):
            value = self._optional_str(
                contact_item.get("provider_contact_id")
                or contact_item.get("contact_id")
                or contact_item.get("id")
                or contact_item.get("wa_id")
            )
            if value:
                return value
        return None

    def _extract_phone_number(self, payload: dict[str, Any]) -> str | None:
        for container in (payload, self._dict_value(payload, "data") or {}, self._dict_value(payload, "payload") or {}):
            value = self._optional_str(container.get("phone_number") or container.get("from"))
            if value:
                return value
            contact = self._dict_value(container, "contact")
            if contact:
                value = self._optional_str(
                    contact.get("phone_number") or contact.get("normalized_phone_number") or contact.get("phone") or contact.get("wa_id")
                )
                if value:
                    return value
        for container in self._message_containers(payload):
            value = self._optional_str(container.get("phone_number") or container.get("from"))
            if value:
                return value
        for contact in self._contact_containers(payload):
            value = self._optional_str(
                contact.get("phone_number")
                or contact.get("normalized_phone_number")
                or contact.get("phone")
                or contact.get("wa_id")
            )
            if value:
                return value
        return None

    def _extract_occurred_at(self, payload: dict[str, Any]) -> str | None:
        for container in (payload, self._dict_value(payload, "data") or {}):
            value = self._optional_str(container.get("occurred_at") or container.get("timestamp") or container.get("created_at"))
            if value:
                return value
        for container in self._message_containers(payload):
            value = self._optional_str(container.get("occurred_at") or container.get("timestamp") or container.get("created_at"))
            if value:
                return value
        return None

    def _extract_workflow_execution_id(self, payload: dict[str, Any]) -> str | None:
        for container in (payload, self._dict_value(payload, "data") or {}):
            value = self._optional_str(container.get("workflow_execution_id") or container.get("workflow_id"))
            if value:
                return value
        return None

    def _message_containers(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        containers: list[dict[str, Any]] = []
        for key in ("message", "whatsapp_message"):
            value = self._dict_value(payload, key)
            if value:
                containers.append(value)
        data = self._dict_value(payload, "data")
        if data:
            for key in ("message", "whatsapp_message"):
                value = self._dict_value(data, key)
                if value:
                    containers.append(value)
        for container in self._iter_dicts(payload):
            messages = container.get("messages")
            if isinstance(messages, list):
                containers.extend(message for message in messages if isinstance(message, dict))
        return containers

    def _contact_containers(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        containers: list[dict[str, Any]] = []
        for container in self._iter_dicts(payload):
            contacts = container.get("contacts")
            if isinstance(contacts, list):
                containers.extend(contact for contact in contacts if isinstance(contact, dict))
        return containers

    def _iter_dicts(self, value: object) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if isinstance(value, dict):
            items.append(value)
            for nested in value.values():
                items.extend(self._iter_dicts(nested))
        elif isinstance(value, list):
            for nested in value:
                items.extend(self._iter_dicts(nested))
        return items

    def _dict_value(self, payload: dict[str, Any], key: str) -> dict[str, Any] | None:
        value = payload.get(key)
        return value if isinstance(value, dict) else None

    def _optional_str(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    def _get_header(self, headers: dict[str, str], name: str) -> str | None:
        lower_name = name.lower()
        for key, value in headers.items():
            if key.lower() == lower_name:
                return value
        return None

    def _signature_header(self, headers: dict[str, str]) -> tuple[str, str] | None:
        for name in ("x-webhook-signature", "x-kapso-signature"):
            value = self._get_header(headers, name)
            if value:
                return name, value
        return None

    def _canonical_json_body(self, raw_body: bytes) -> bytes | None:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def _signature_matches(self, signature: str, body: bytes) -> bool:
        digest = hmac.new(
            self._webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, f"sha256={digest}") or hmac.compare_digest(signature, digest)

    def _validate_replay_window(self, headers: dict[str, str]) -> None:
        timestamp = self._get_header(headers, "x-kapso-timestamp")
        if not timestamp:
            return
        occurred_at = self._parse_timestamp(timestamp)
        now = datetime.now(UTC)
        age_seconds = abs((now - occurred_at).total_seconds())
        if age_seconds > self._replay_window_seconds:
            raise WebhookSignatureError("KAPSO webhook timestamp outside replay window")

    def _parse_timestamp(self, value: str) -> datetime:
        try:
            if value.isdigit():
                return datetime.fromtimestamp(int(value), tz=UTC)
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WebhookSignatureError("Invalid KAPSO webhook timestamp") from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
