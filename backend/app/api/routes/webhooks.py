import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.dependencies import (
    get_conversation_orchestrator,
    get_kapso_provider,
    get_notification_service,
    get_whatsapp_allowlist_service,
)
from app.core.config import get_settings
from app.application.conversation_orchestrator import ConversationOrchestrator, InboundConversationMessage
from app.application.notifications import NotificationService
from app.application.whatsapp_allowlist import WhatsappAllowlistService
from app.infrastructure.adapters.kapso import KapsoProvider, WebhookPayloadError, WebhookSignatureError
from app.infrastructure.adapters.whatsapp import NormalizedInboundEvent


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class KapsoWebhookItemResponse(BaseModel):
    correlation_id: str
    accepted: bool
    duplicate: bool
    handoff_required: bool


class KapsoWebhookResponse(BaseModel):
    accepted: bool
    provider: str
    processed: int
    duplicates: int
    results: list[KapsoWebhookItemResponse]


@router.post("/kapso", response_model=KapsoWebhookResponse)
async def receive_kapso_webhook(
    request: Request,
    provider: KapsoProvider = Depends(get_kapso_provider),
    orchestrator: ConversationOrchestrator = Depends(get_conversation_orchestrator),
    notifications: NotificationService = Depends(get_notification_service),
    allowlist: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
) -> KapsoWebhookResponse:
    settings = get_settings()
    if not settings.debug and (
        len(settings.kapso_webhook_secret) < 32
        or settings.kapso_webhook_secret == "local-dev-secret"
        or not settings.internal_api_key
        or len(settings.internal_api_key) < 32
        or settings.effective_whatsapp_allowlist_default_allow
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secure webhook and internal API secrets must be configured",
        )
    raw_body = await request.body()
    headers = dict(request.headers)
    payload: Any | None = None
    try:
        provider.verify_webhook_signature(raw_body=raw_body, headers=headers)
        payload = json.loads(raw_body.decode("utf-8"))
        payloads = _extract_payloads(payload)
        _apply_header_idempotency_key(payloads, headers)
        normalized_events = [
            provider.normalize_inbound(payload=item, headers=headers)
            for item in payloads
        ]
    except WebhookSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, WebhookPayloadError, TypeError) as exc:
        _log_kapso_payload_error(payload=payload, headers=headers, error=exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload") from exc

    results: list[KapsoWebhookItemResponse] = []
    for event in normalized_events:
        decision = allowlist.is_phone_allowed(
            phone_number=event.phone_number,
            provider=provider.provider_name,
            correlation_id=event.correlation_id,
            idempotency_key=event.idempotency_key,
            record_event=True,
        )
        if not decision.allowed:
            logger.info(
                "kapso_webhook_blocked_by_allowlist correlation_id=%s phone=%s reason=%s",
                event.correlation_id,
                event.phone_number,
                decision.reason,
            )
            results.append(
                KapsoWebhookItemResponse(
                    correlation_id=event.correlation_id,
                    accepted=False,
                    duplicate=False,
                    handoff_required=False,
                )
            )
            continue
        try:
            result = orchestrator.handle_inbound_message(_to_inbound_message(event))
        except Exception:
            logger.exception(
                "kapso_webhook_processing_failed correlation_id=%s provider_message_id=%s",
                event.correlation_id,
                event.provider_message_id,
            )
            try:
                orchestrator.record_webhook_processing_failed(
                    provider=event.provider,
                    idempotency_key=event.idempotency_key,
                    correlation_id=event.correlation_id,
                    provider_message_id=event.provider_message_id,
                )
            except Exception:
                logger.exception(
                    "kapso_webhook_failure_event_log_failed correlation_id=%s",
                    event.correlation_id,
                )
            results.append(
                KapsoWebhookItemResponse(
                    correlation_id=event.correlation_id,
                    accepted=True,
                    duplicate=False,
                    handoff_required=True,
                )
            )
            continue

        is_duplicate = result.shipment_request is None and result.response_text is None and not result.events
        handoff_required = result.handoff_required
        if result.response_text and event.phone_number:
            reply_status = notifications.send_conversation_reply(
                phone_number=event.phone_number,
                body=result.response_text,
                conversation_session_id=result.conversation_session.id,
                inbound_idempotency_key=event.idempotency_key,
                correlation_id=event.correlation_id,
                actions=result.actions,
            )
            handoff_required = handoff_required or reply_status == "failed"
        results.append(
            KapsoWebhookItemResponse(
                correlation_id=event.correlation_id,
                accepted=True,
                duplicate=is_duplicate,
                handoff_required=handoff_required,
            )
        )

    return KapsoWebhookResponse(
        accepted=True,
        provider=provider.provider_name,
        processed=len(results),
        duplicates=sum(1 for item in results if item.duplicate),
        results=results,
    )


def _extract_payloads(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("events"), list):
        items = payload["events"]
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise WebhookPayloadError("Webhook payload must be an object or batch")

    if not items:
        raise WebhookPayloadError("Webhook batch is empty")
    if not all(isinstance(item, dict) for item in items):
        raise WebhookPayloadError("Webhook batch items must be objects")
    return items


def _apply_header_idempotency_key(payloads: list[dict[str, Any]], headers: dict[str, str]) -> None:
    idempotency_key = _get_header(headers, "x-idempotency-key")
    if not idempotency_key:
        return
    for index, payload in enumerate(payloads):
        payload.setdefault(
            "_header_idempotency_key",
            idempotency_key if len(payloads) == 1 else f"{idempotency_key}:{index}",
        )


def _get_header(headers: dict[str, str], name: str) -> str | None:
    lower_name = name.lower()
    for key, value in headers.items():
        if key.lower() == lower_name:
            return value
    return None


def _log_kapso_payload_error(*, payload: Any | None, headers: dict[str, str], error: Exception) -> None:
    logger.warning(
        "kapso_webhook_payload_invalid top_level_keys=%s webhook_event=%s payload_version=%s "
        "idempotency_header_present=%s error=%s",
        _safe_top_level_keys(payload),
        _get_header(headers, "x-webhook-event") or "none",
        _get_header(headers, "x-webhook-payload-version") or "none",
        _get_header(headers, "x-idempotency-key") is not None,
        str(error),
    )


def _safe_top_level_keys(payload: Any | None) -> list[str]:
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload.keys())
    if isinstance(payload, list):
        return ["<list>"]
    if payload is None:
        return ["<unparsed>"]
    return [type(payload).__name__]


def _to_inbound_message(event: NormalizedInboundEvent) -> InboundConversationMessage:
    return InboundConversationMessage(
        provider=event.provider,
        idempotency_key=event.idempotency_key,
        correlation_id=event.correlation_id,
        conversation_id=event.conversation_id,
        workflow_execution_id=event.workflow_execution_id,
        provider_contact_id=event.provider_contact_id,
        provider_message_id=event.provider_message_id,
        phone_number=event.phone_number,
        occurred_at=_parse_optional_datetime(event.occurred_at),
        text=event.text,
        location=event.location,
        reply_to_message_id=event.reply_to_message_id,
        media=event.media,
        action_selection=event.action_selection,
    )


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
