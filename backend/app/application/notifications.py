from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from app.application.interactive import prepare_outbound_message
from app.domain.cargo import quantity_unit_label
from app.domain.events import EventLog, EventLogService, current_test_run_id
from app.domain.models import Carrier, ConversationSession, Location, Message, ShipmentRequest, utc_now
from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.infrastructure.adapters.whatsapp import OutboundAction, OutboundMessage, WhatsAppProvider


class CarrierRepository(Protocol):
    def get(self, entity_id: str) -> Carrier | None:
        pass

    def save(self, entity: Carrier) -> Carrier:
        pass


class LocationRepository(Protocol):
    def get(self, entity_id: str) -> Location | None:
        pass


class ConversationSessionRepository(Protocol):
    def get(self, entity_id: str) -> ConversationSession | None:
        pass


class MessageRepository(Protocol):
    def add(self, entity: Message) -> Message:
        pass

    def list(self, *, include_deleted: bool = False) -> list[Message]:
        pass


@dataclass(frozen=True)
class CarrierAlertMessage:
    body: str
    actions: tuple[OutboundAction, ...]


@dataclass(frozen=True)
class NotificationResult:
    carrier_id: str
    status: str
    provider: str
    idempotency_key: str
    provider_message_id: str | None = None
    error: str | None = None
    events: tuple[EventLog, ...] = ()


@dataclass(frozen=True)
class ProducerNotificationResult:
    phone_number: str
    status: str
    provider: str
    idempotency_key: str
    provider_message_id: str | None = None
    error: str | None = None
    events: tuple[EventLog, ...] = ()


class NotificationService:
    def __init__(
        self,
        *,
        provider: WhatsAppProvider,
        event_log: EventLogService,
        carriers: CarrierRepository | None = None,
        locations: LocationRepository | None = None,
        conversation_sessions: ConversationSessionRepository | None = None,
        messages: MessageRepository | None = None,
    ) -> None:
        self._provider = provider
        self._event_log = event_log
        self._carriers = carriers
        self._locations = locations
        self._conversation_sessions = conversation_sessions
        self._messages = messages

    def send_conversation_reply(
        self,
        *,
        phone_number: str,
        body: str,
        conversation_session_id: str,
        inbound_idempotency_key: str,
        correlation_id: str,
        actions: tuple[OutboundAction, ...] = (),
    ) -> str:
        """Send one backend-authored reply and audit the result without logging its text."""
        idempotency_key = f"{inbound_idempotency_key}:conversation_reply"
        if self._has_event(f"{idempotency_key}:sent") or self._has_event(f"{idempotency_key}:queued"):
            return "skipped_duplicate"
        try:
            destination = normalize_phone_number(phone_number)
        except PhoneNormalizationError:
            self._record_conversation_reply_event(
                event_type="CONVERSATION_REPLY_FAILED",
                session_id=conversation_session_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={"error": "invalid_destination"},
            )
            return "failed"

        session = (
            self._conversation_sessions.get(conversation_session_id)
            if self._conversation_sessions is not None
            else None
        )
        reply_metadata = {
            "entity_type": "ConversationSession",
            "entity_id": conversation_session_id,
            "notification_type": "CONVERSATION_REPLY",
            "outbox_idempotency_key": idempotency_key,
            **({"qa_role": session.role_override} if session and session.role_override else {}),
            **({"qa_test_run_id": session.active_test_run_id} if session and session.active_test_run_id else {}),
        }

        outbound_message, interactive_delivery = prepare_outbound_message(
            OutboundMessage(
                conversation_id=destination,
                body=body,
                correlation_id=correlation_id,
                allowlist_phone_number=destination,
                metadata=reply_metadata,
                actions=actions,
            ),
            self._provider.capabilities,
        )

        self._record_conversation_reply_event(
            event_type="CONVERSATION_REPLY_REQUESTED",
            session_id=conversation_session_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload={
                "provider": self._provider.provider_name,
                "interactive_delivery": interactive_delivery,
                "message_type": outbound_message.message_type,
                **({"interactive_actions": [action.as_metadata() for action in actions]} if actions else {}),
            },
        )
        try:
            result = self._provider.send_message(outbound_message)
        except Exception as exc:  # noqa: BLE001
            self._record_conversation_reply_event(
                event_type="CONVERSATION_REPLY_FAILED",
                session_id=conversation_session_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={"error": exc.__class__.__name__},
            )
            return "failed"
        if result.payload.get("outbox_queued"):
            self._record_conversation_reply_event(
                event_type="CONVERSATION_REPLY_QUEUED",
                session_id=conversation_session_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={
                    "provider": result.provider,
                    "outbox_id": result.payload.get("outbox_id"),
                    "interactive_delivery": interactive_delivery,
                    "message_type": outbound_message.message_type,
                    **({"interactive_actions": [action.as_metadata() for action in actions]} if actions else {}),
                },
            )
            return "queued"
        if not result.accepted:
            self._record_conversation_reply_event(
                event_type="CONVERSATION_REPLY_FAILED",
                session_id=conversation_session_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={"error": "provider_rejected"},
            )
            return "failed"
        self._record_conversation_reply_event(
            event_type="CONVERSATION_REPLY_SENT",
            session_id=conversation_session_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload={
                "provider": result.provider,
                "provider_message_id": result.provider_message_id,
                "interactive_delivery": interactive_delivery,
                "message_type": outbound_message.message_type,
                **({"interactive_actions": [action.as_metadata() for action in actions]} if actions else {}),
            },
        )
        self._record_outbound_message(
            conversation_session_id=conversation_session_id,
            phone_number=destination,
            provider=result.provider,
            provider_message_id=result.provider_message_id,
            body=body,
            message_type=outbound_message.message_type,
            idempotency_key=f"{idempotency_key}:outbound",
            correlation_id=correlation_id,
        )
        return "sent"

    def _record_outbound_message(
        self,
        *,
        conversation_session_id: str | None = None,
        phone_number: str | None,
        provider: str,
        provider_message_id: str | None,
        body: str,
        message_type: str = "text",
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        if self._messages is None:
            return
        if any(message.idempotency_key == idempotency_key for message in self._messages.list()):
            return

        session = self._conversation_sessions.get(conversation_session_id) if (
            self._conversation_sessions is not None and conversation_session_id
        ) else None
        if session is None and self._conversation_sessions is not None and phone_number:
            candidates: list[ConversationSession] = []
            for candidate in self._conversation_sessions.list():
                candidate_phone = candidate.normalized_phone_number or candidate.participant_phone
                try:
                    normalized_candidate = normalize_phone_number(candidate_phone) if candidate_phone else None
                except PhoneNormalizationError:
                    normalized_candidate = None
                if normalized_candidate == phone_number:
                    candidates.append(candidate)
            active_run_id = current_test_run_id.get()
            candidates.sort(
                key=lambda candidate: (
                    bool(active_run_id and candidate.active_test_run_id == active_run_id),
                    candidate.status == "OPEN",
                    candidate.last_message_at or candidate.started_at,
                ),
                reverse=True,
            )
            session = candidates[0] if candidates else None
        if session is None:
            return

        conversation_session_id = session.id
        test_run_id = current_test_run_id.get() or (session.active_test_run_id if session else None)
        qa_role = session.role_override if session else None
        related_entity_ids = {}
        if test_run_id:
            related_entity_ids["testRunId"] = test_run_id
        if qa_role:
            related_entity_ids["qaRole"] = qa_role

        self._messages.add(
            Message(
                conversation_session_id=conversation_session_id,
                provider=provider,
                direction="outbound",
                sender_type="Agent",
                message_type=message_type,
                test_run_id=test_run_id,
                provider_message_id=provider_message_id,
                idempotency_key=idempotency_key,
                raw_content=body,
                normalized_content=body,
                sent_at=utc_now(),
                correlation_id=correlation_id,
                related_entity_ids=related_entity_ids,
            )
        )

    def _record_conversation_reply_event(
        self,
        *,
        event_type: str,
        session_id: str,
        idempotency_key: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        session = (
            self._conversation_sessions.get(session_id)
            if self._conversation_sessions is not None
            else None
        )
        self._event_log.record(
            event_type=event_type,
            actor_type="SYSTEM",
            entity_type="ConversationSession",
            entity_id=session_id,
            related_entity_ids={
                "conversationSessionId": session_id,
                **({"qaRole": session.role_override} if session and session.role_override else {}),
            },
            summary="Respuesta conversacional gestionada por backend",
            payload=payload,
            source=self._provider.provider_name,
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}:{event_type.rsplit('_', 1)[-1].lower()}",
        )

    def send_new_load_alerts(
        self,
        *,
        shipment: ShipmentRequest,
        carrier_ids: list[str],
        operator_user_id: str | None,
    ) -> tuple[NotificationResult, ...]:
        return tuple(
            self.send_new_load_alert(
                shipment=shipment,
                carrier_id=carrier_id,
                operator_user_id=operator_user_id,
            )
            for carrier_id in carrier_ids
        )

    def send_new_load_alert(
        self,
        *,
        shipment: ShipmentRequest,
        carrier_id: str,
        operator_user_id: str | None,
        route_context: dict | None = None,
    ) -> NotificationResult:
        alert_message = self._build_new_load_alert_message(shipment)
        idempotency_key = self._carrier_alert_idempotency_key(shipment.id, carrier_id)
        routing = self._resolve_carrier_routing(carrier_id)
        if routing is None:
            return self._record_unroutable_carrier_alert(
                shipment=shipment,
                carrier_id=carrier_id,
                operator_user_id=operator_user_id,
                idempotency_key=idempotency_key,
            )
        return self.send_carrier_message(
            carrier_id=carrier_id,
            destination=routing[0],
            body=alert_message.body + ("\n🛣️ Coincide con tu recorrido habitual. Confirmá si tenés disponibilidad." if route_context and route_context.get("stage") == "PREFERENCE" else ""),
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            notification_type="NEW_LOAD_ALERT",
            operator_user_id=operator_user_id,
            idempotency_key=idempotency_key,
            allowlist_phone_number=routing[1],
            metadata={
                "routing_guard": bool(route_context),
                **(route_context or {}),
                "shipment_request_id": shipment.id,
                "qa_test_run_id": shipment.test_run_id,
                "cargo_category": shipment.cargo_category,
                "cargo_type": shipment.cargo_type,
                "quantity_unit": shipment.quantity_unit,
                "template_body_parameters": self._new_load_template_body_parameters(shipment),
            },
            actions=alert_message.actions,
        )

    def send_reminder(
        self,
        *,
        carrier_id: str,
        body: str,
        entity_type: str,
        entity_id: str,
        operator_user_id: str | None = None,
        idempotency_key: str,
    ) -> NotificationResult:
        return self.send_carrier_message(
            carrier_id=carrier_id,
            destination=carrier_id,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
            notification_type="REMINDER",
            operator_user_id=operator_user_id,
            idempotency_key=idempotency_key,
        )

    def send_manual_message(
        self,
        *,
        carrier_id: str,
        body: str,
        entity_type: str,
        entity_id: str,
        operator_user_id: str,
        idempotency_key: str,
        notification_type: str = "MANUAL_MESSAGE",
    ) -> NotificationResult:
        routing = self._resolve_carrier_routing(carrier_id)
        if routing is None:
            requested = self._event_log.record(
                event_type="CARRIER_NOTIFICATION_REQUESTED",
                actor_type="OPERATOR" if operator_user_id else "SYSTEM",
                actor_id=operator_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                summary="Notificacion a transportista solicitada",
                related_entity_ids={"carrierId": carrier_id},
                payload={
                    "carrier_id": carrier_id,
                    "notification_type": notification_type,
                    "provider": self._provider.provider_name,
                    "attempt_type": "text",
                    "template_fallback_used": False,
                    "template_name": None,
                },
                source="notification_service",
                idempotency_key=f"{idempotency_key}:requested",
            )
            failed = self._record_failed_event(
                carrier_id=carrier_id,
                entity_type=entity_type,
                entity_id=entity_id,
                notification_type=notification_type,
                idempotency_key=idempotency_key,
                error="Carrier does not have a valid phone or provider conversation mapping",
                metadata={
                    "attempt_type": "text",
                    "template_fallback_used": False,
                    "template_name": None,
                },
            )
            return NotificationResult(
                carrier_id=carrier_id,
                status="failed",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                error=failed.payload["error"],
                events=(requested, failed),
            )

        destination, allowlist_phone_number = routing
        return self.send_carrier_message(
            carrier_id=carrier_id,
            destination=destination,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
            notification_type=notification_type,
            operator_user_id=operator_user_id,
            idempotency_key=idempotency_key,
            allowlist_phone_number=allowlist_phone_number,
        )

    def send_producer_message(
        self,
        *,
        phone_number: str,
        body: str,
        entity_type: str,
        entity_id: str,
        operator_user_id: str,
        idempotency_key: str,
        notification_type: str = "MANUAL_MESSAGE",
    ) -> ProducerNotificationResult:
        if self._has_event(f"{idempotency_key}:sent") or self._has_event(f"{idempotency_key}:queued"):
            return ProducerNotificationResult(
                phone_number=phone_number,
                status="skipped_duplicate",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                events=(),
            )

        try:
            normalized_phone = normalize_phone_number(phone_number)
        except PhoneNormalizationError as exc:
            failed_event = self._event_log.record(
                event_type="PRODUCER_NOTIFICATION_FAILED",
                actor_type="SYSTEM",
                entity_type=entity_type,
                entity_id=entity_id,
                summary="Fallo envio de notificacion a productor",
                related_entity_ids={"producerPhoneNumber": phone_number},
                payload={
                    "phone_number": phone_number,
                    "notification_type": notification_type,
                    "provider": self._provider.provider_name,
                    "error": str(exc),
                },
                source=self._provider.provider_name,
                correlation_id=idempotency_key,
                idempotency_key=f"{idempotency_key}:failed",
            )
            return ProducerNotificationResult(
                phone_number=phone_number,
                status="failed",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                error=str(exc),
                events=(failed_event,),
            )

        outbound_message = OutboundMessage(
            conversation_id=normalized_phone,
            body=body,
            correlation_id=idempotency_key,
            allowlist_phone_number=normalized_phone,
            metadata={
                "producer_phone_number": normalized_phone,
                **({"qa_role": "Producer", "qa_test_run_id": current_test_run_id.get()} if current_test_run_id.get() else {}),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "notification_type": notification_type,
                "outbox_idempotency_key": idempotency_key,
            },
        )
        events: list[EventLog] = [
            self._event_log.record(
                event_type="PRODUCER_NOTIFICATION_REQUESTED",
                actor_type="OPERATOR",
                actor_id=operator_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                summary="Notificacion a productor solicitada",
                related_entity_ids={"producerPhoneNumber": normalized_phone},
                payload={
                    "phone_number": normalized_phone,
                    "notification_type": notification_type,
                    "provider": self._provider.provider_name,
                    **outbound_message.metadata,
                },
                source="notification_service",
                idempotency_key=f"{idempotency_key}:requested",
            )
        ]
        try:
            provider_result = self._provider.send_message(outbound_message)
        except Exception as exc:
            events.append(
                self._event_log.record(
                    event_type="PRODUCER_NOTIFICATION_FAILED",
                    actor_type="SYSTEM",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    summary="Fallo envio de notificacion a productor",
                    related_entity_ids={"producerPhoneNumber": normalized_phone},
                payload={
                    "phone_number": normalized_phone,
                    "notification_type": notification_type,
                    "provider": self._provider.provider_name,
                    "attempt_type": "text",
                    "template_fallback_used": False,
                    "template_name": None,
                    "error": str(exc),
                },
                source=self._provider.provider_name,
                correlation_id=idempotency_key,
                    idempotency_key=f"{idempotency_key}:failed",
                )
            )
            return ProducerNotificationResult(
                phone_number=normalized_phone,
                status="failed",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                error=str(exc),
                events=tuple(events),
            )

        if not provider_result.accepted:
            error = "Provider rejected outbound message"
            events.append(
                self._event_log.record(
                    event_type="PRODUCER_NOTIFICATION_FAILED",
                    actor_type="SYSTEM",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    summary="Fallo envio de notificacion a productor",
                    related_entity_ids={"producerPhoneNumber": normalized_phone},
                payload={
                    "phone_number": normalized_phone,
                    "notification_type": notification_type,
                    "provider": self._provider.provider_name,
                    "attempt_type": "text",
                    "template_fallback_used": False,
                    "template_name": None,
                    "error": error,
                },
                source=self._provider.provider_name,
                correlation_id=idempotency_key,
                    idempotency_key=f"{idempotency_key}:failed",
                )
            )
            return ProducerNotificationResult(
                phone_number=normalized_phone,
                status="failed",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                provider_message_id=provider_result.provider_message_id,
                error=error,
                events=tuple(events),
            )

        events.append(
            self._event_log.record(
                event_type=(
                    "PRODUCER_NOTIFICATION_QUEUED"
                    if provider_result.payload.get("outbox_queued")
                    else "PRODUCER_NOTIFICATION_SENT"
                ),
                actor_type="SYSTEM",
                entity_type=entity_type,
                entity_id=entity_id,
                summary=(
                    "Notificacion a productor encolada"
                    if provider_result.payload.get("outbox_queued")
                    else "Notificacion a productor enviada"
                ),
                related_entity_ids={"producerPhoneNumber": normalized_phone},
                payload={
                    "phone_number": normalized_phone,
                    "notification_type": notification_type,
                    "provider": provider_result.provider,
                    "provider_message_id": provider_result.provider_message_id,
                    "outbox_id": provider_result.payload.get("outbox_id"),
                    "attempt_type": self._attempt_type_from_provider_result(provider_result.payload),
                    "template_fallback_used": bool(provider_result.payload.get("template_fallback_used")),
                    "template_name": provider_result.payload.get("template_name"),
                    **outbound_message.metadata,
                },
                source=self._provider.provider_name,
                correlation_id=idempotency_key,
                idempotency_key=(
                    f"{idempotency_key}:queued"
                    if provider_result.payload.get("outbox_queued")
                    else f"{idempotency_key}:sent"
                ),
            )
        )
        queued = bool(provider_result.payload.get("outbox_queued"))
        if not queued:
            self._record_outbound_message(
                phone_number=normalized_phone,
                provider=provider_result.provider,
                provider_message_id=provider_result.provider_message_id,
                body=outbound_message.body,
                message_type="text",
                idempotency_key=f"{idempotency_key}:outbound",
                correlation_id=idempotency_key,
            )
        return ProducerNotificationResult(
            phone_number=normalized_phone,
            status="queued" if queued else "sent",
            provider=self._provider.provider_name,
            idempotency_key=idempotency_key,
            provider_message_id=provider_result.provider_message_id,
            events=tuple(events),
        )

    def send_carrier_message(
        self,
        *,
        carrier_id: str,
        destination: str,
        body: str,
        entity_type: str,
        entity_id: str,
        notification_type: str,
        operator_user_id: str | None,
        idempotency_key: str,
        allowlist_phone_number: str | None = None,
        metadata: dict[str, Any] | None = None,
        actions: tuple[OutboundAction, ...] = (),
    ) -> NotificationResult:
        if self._has_event(f"{idempotency_key}:sent") or self._has_event(f"{idempotency_key}:queued"):
            return NotificationResult(
                carrier_id=carrier_id,
                status="skipped_duplicate",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                events=(),
            )

        outbound_message, interactive_delivery = prepare_outbound_message(
            OutboundMessage(
                conversation_id=destination,
                body=body,
                correlation_id=idempotency_key,
                allowlist_phone_number=allowlist_phone_number,
                metadata={
                    "carrier_id": carrier_id,
                    "destination": destination,
                    "allowlist_phone_number": allowlist_phone_number,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "notification_type": notification_type,
                    "outbox_idempotency_key": idempotency_key,
                    **(metadata or {}),
                },
                actions=actions,
            ),
            self._provider.capabilities,
        )

        events: list[EventLog] = []
        events.append(
            self._event_log.record(
                event_type="CARRIER_NOTIFICATION_REQUESTED",
                actor_type="OPERATOR" if operator_user_id else "SYSTEM",
                actor_id=operator_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                summary="Notificacion a transportista solicitada",
                related_entity_ids={"carrierId": carrier_id},
                payload={
                    "carrier_id": carrier_id,
                    "notification_type": notification_type,
                    "provider": self._provider.provider_name,
                    "attempt_type": "text",
                    "template_fallback_used": False,
                    "template_name": None,
                    **outbound_message.metadata,
                },
                source="notification_service",
                idempotency_key=f"{idempotency_key}:requested",
            )
        )

        try:
            provider_result = self._provider.send_message(outbound_message)
        except Exception as exc:
            error = str(exc)
            events.append(
                self._record_failed_event(
                    carrier_id=carrier_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    notification_type=notification_type,
                    idempotency_key=idempotency_key,
                    error=error,
                    metadata=self._failure_metadata_from_error(error),
                )
            )
            return NotificationResult(
                carrier_id=carrier_id,
                status="failed",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                error=error,
                events=tuple(events),
            )

        if not provider_result.accepted:
            error = "Provider rejected outbound message"
            events.append(
                self._record_failed_event(
                    carrier_id=carrier_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    notification_type=notification_type,
                    idempotency_key=idempotency_key,
                    error=error,
                    metadata={"attempt_type": "text", "template_fallback_used": False, "template_name": None},
                )
            )
            return NotificationResult(
                carrier_id=carrier_id,
                status="failed",
                provider=self._provider.provider_name,
                idempotency_key=idempotency_key,
                provider_message_id=provider_result.provider_message_id,
                error=error,
                events=tuple(events),
            )

        events.append(
            self._event_log.record(
                event_type=(
                    "CARRIER_NOTIFICATION_QUEUED"
                    if provider_result.payload.get("outbox_queued")
                    else "CARRIER_NOTIFICATION_SENT"
                ),
                actor_type="SYSTEM",
                entity_type=entity_type,
                entity_id=entity_id,
                summary=(
                    "Notificacion a transportista encolada"
                    if provider_result.payload.get("outbox_queued")
                    else "Notificacion a transportista enviada"
                ),
                related_entity_ids={"carrierId": carrier_id},
                payload={
                    "carrier_id": carrier_id,
                    "destination": destination,
                    "notification_type": notification_type,
                    "provider": provider_result.provider,
                    "provider_message_id": provider_result.provider_message_id,
                    "outbox_id": provider_result.payload.get("outbox_id"),
                    "attempt_type": self._attempt_type_from_provider_result(provider_result.payload),
                    "template_fallback_used": bool(provider_result.payload.get("template_fallback_used")),
                    "template_name": provider_result.payload.get("template_name"),
                    "interactive_delivery": interactive_delivery if actions else None,
                    **outbound_message.metadata,
                },
                source=self._provider.provider_name,
                correlation_id=idempotency_key,
                idempotency_key=(
                    f"{idempotency_key}:queued"
                    if provider_result.payload.get("outbox_queued")
                    else f"{idempotency_key}:sent"
                ),
            )
        )
        queued = bool(provider_result.payload.get("outbox_queued"))
        if not queued:
            self._record_outbound_message(
                phone_number=allowlist_phone_number,
                provider=provider_result.provider,
                provider_message_id=provider_result.provider_message_id,
                body=outbound_message.body,
                message_type=outbound_message.message_type,
                idempotency_key=f"{idempotency_key}:outbound",
                correlation_id=idempotency_key,
            )
        return NotificationResult(
            carrier_id=carrier_id,
            status="queued" if queued else "sent",
            provider=self._provider.provider_name,
            idempotency_key=idempotency_key,
            provider_message_id=provider_result.provider_message_id,
            events=tuple(events),
        )

    def _record_failed_event(
        self,
        *,
        carrier_id: str,
        entity_type: str,
        entity_id: str,
        notification_type: str,
        idempotency_key: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> EventLog:
        return self._event_log.record(
            event_type="CARRIER_NOTIFICATION_FAILED",
            actor_type="SYSTEM",
            entity_type=entity_type,
            entity_id=entity_id,
            summary="Fallo envio de notificacion a transportista",
            related_entity_ids={"carrierId": carrier_id},
            payload={
                "carrier_id": carrier_id,
                "notification_type": notification_type,
                "provider": self._provider.provider_name,
                "error": error,
                **(metadata or {}),
            },
            source=self._provider.provider_name,
            correlation_id=idempotency_key,
            idempotency_key=f"{idempotency_key}:failed",
        )

    def _record_unroutable_carrier_alert(
        self,
        *,
        shipment: ShipmentRequest,
        carrier_id: str,
        operator_user_id: str | None,
        idempotency_key: str,
    ) -> NotificationResult:
        requested = self._event_log.record(
            event_type="CARRIER_NOTIFICATION_REQUESTED",
            actor_type="OPERATOR" if operator_user_id else "SYSTEM",
            actor_id=operator_user_id,
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            summary="Notificacion a transportista solicitada",
            related_entity_ids={"carrierId": carrier_id},
            payload={
                "carrier_id": carrier_id,
                "notification_type": "NEW_LOAD_ALERT",
                "provider": self._provider.provider_name,
                "shipment_request_id": shipment.id,
                "attempt_type": "text",
                "template_fallback_used": False,
                "template_name": None,
            },
            source="notification_service",
            idempotency_key=f"{idempotency_key}:requested",
        )
        failed = self._record_failed_event(
            carrier_id=carrier_id,
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            notification_type="NEW_LOAD_ALERT",
            idempotency_key=idempotency_key,
            error="Carrier does not have a valid phone or provider conversation mapping",
            metadata={
                "attempt_type": "text",
                "template_fallback_used": False,
                "template_name": None,
            },
        )
        return NotificationResult(
            carrier_id=carrier_id,
            status="failed",
            provider=self._provider.provider_name,
            idempotency_key=idempotency_key,
            error=failed.payload["error"],
            events=(requested, failed),
        )

    def _resolve_carrier_destination(self, carrier_id: str) -> str | None:
        routing = self._resolve_carrier_routing(carrier_id)
        if routing is None:
            return None
        return routing[0]

    def _resolve_carrier_routing(self, carrier_id: str) -> tuple[str, str | None] | None:
        if self._carriers is None:
            return carrier_id, None
        carrier = self._carriers.get(carrier_id)
        if carrier is None:
            return None
        normalized_phone = None
        try:
            normalized_phone = carrier.normalized_phone_number or normalize_phone_number(carrier.contact_phone)
        except PhoneNormalizationError:
            normalized_phone = None

        destination = carrier.provider_conversation_id or carrier.provider_contact_id
        if destination:
            return destination, normalized_phone
        if not normalized_phone:
            return None
        carrier.normalized_phone_number = normalized_phone
        carrier.provider_name = carrier.provider_name or self._provider.provider_name
        carrier.last_outbound_at = utc_now()
        self._carriers.save(carrier)
        return normalized_phone, normalized_phone

    def _build_new_load_alert_message(self, shipment: ShipmentRequest) -> CarrierAlertMessage:
        return CarrierAlertMessage(
            body=self._build_new_load_alert_body(shipment),
            actions=(
                OutboundAction(id="interested", label="Me interesa", value="INTERESTED"),
                OutboundAction(id="declined", label="No puedo", value="DECLINED"),
                OutboundAction(id="more_info", label="Más info", value="MORE_INFO"),
            ),
        )

    def _build_new_load_alert_body(self, shipment: ShipmentRequest) -> str:
        load_line = self._format_load_line(shipment)
        origin = self._location_label(shipment.origin_location_id, "origen a confirmar")
        destination = self._location_label(shipment.destination_location_id, "destino a confirmar")
        date_window = self._format_date_window(shipment)
        notes = self._carrier_alert_notes(shipment)
        return (
            "📦 Nueva carga disponible\n"
            f"{load_line}\n"
            f"📍 {origin} → {destination}\n"
            f"📅 {date_window}\n"
            f"📝 {notes}"
        )

    def _new_load_template_body_parameters(self, shipment: ShipmentRequest) -> list[str]:
        origin = self._location_label(shipment.origin_location_id, "origen a confirmar")
        destination = self._location_label(shipment.destination_location_id, "destino a confirmar")
        return [
            self._format_load_line(shipment),
            f"{origin} → {destination}",
            self._format_date_window(shipment),
            self._carrier_alert_notes(shipment),
        ]

    def _format_load_line(self, shipment: ShipmentRequest) -> str:
        quantity = self._format_quantity(shipment.quantity_estimate)
        cargo_category = shipment.cargo_category or ("LIVESTOCK" if shipment.livestock_type else None)
        cargo_type = shipment.cargo_type or shipment.livestock_type
        if cargo_category == "GRAIN":
            unit = self._format_quantity_unit(shipment.quantity_unit)
            type_label = cargo_type or "grano"
            if shipment.quantity_estimate is None:
                return f"Carga ID {shipment.id} - 🌾 {type_label}"
            return f"Carga ID {shipment.id} - 🌾 {quantity} {unit} {type_label}".strip()
        type_label = cargo_type or "hacienda"
        return f"Carga ID {shipment.id} - 🐄 {quantity} {type_label}"

    def _format_quantity_unit(self, quantity_unit: str | None) -> str:
        return quantity_unit_label(quantity_unit) or quantity_unit or ""

    def _format_quantity(self, quantity: Decimal | None) -> str:
        if quantity is None:
            return "cantidad a confirmar"
        if isinstance(quantity, Decimal) and quantity == quantity.to_integral_value():
            return str(quantity.to_integral_value())
        return f"{quantity:g}"

    def _location_label(self, location_id: str | None, fallback: str) -> str:
        if not location_id or self._locations is None:
            return fallback
        location = self._locations.get(location_id)
        if location is None:
            return fallback
        return location.normalized_name or location.original_text or fallback

    def _format_date_window(self, shipment: ShipmentRequest) -> str:
        if shipment.date_window_start and shipment.date_window_end:
            return (
                f"{self._format_datetime(shipment.date_window_start)} - "
                f"{self._format_datetime(shipment.date_window_end)}"
            )
        if shipment.date_window_start:
            return self._format_datetime(shipment.date_window_start)
        if shipment.date_window_end:
            return f"hasta {self._format_datetime(shipment.date_window_end)}"
        return "fecha/hora a confirmar"

    def _format_datetime(self, value: datetime) -> str:
        return value.strftime("%d/%m/%Y %H:%M")

    def _brief_notes(self, notes: str | None) -> str:
        if not notes:
            return "sin observaciones"
        compact = " ".join(notes.split())
        if len(compact) <= 120:
            return compact
        return f"{compact[:117].rstrip()}..."

    def _carrier_alert_notes(self, shipment: ShipmentRequest) -> str:
        base_notes = self._brief_notes(shipment.operational_notes)
        hint = f'Si es por esta carga: "me interesa {shipment.id}"'
        return f"{base_notes} | {hint}"

    def _attempt_type_from_provider_result(self, payload: dict[str, Any]) -> str:
        explicit = payload.get("attempt_type")
        if explicit in {"text", "template"}:
            return str(explicit)
        return "template" if payload.get("template_fallback_used") else "text"

    def _failure_metadata_from_error(self, error: str) -> dict[str, Any]:
        lowered = error.lower()
        is_template = "template outbound" in lowered or "template message" in lowered
        template_fallback_used = "fallback_used=true" in lowered if is_template else False
        return {
            "attempt_type": "template" if is_template else "text",
            "template_fallback_used": template_fallback_used,
            "template_name": getattr(self._provider, "_new_load_template_name", None) if is_template else None,
            "provider_error_summary": error,
        }

    def _carrier_alert_idempotency_key(self, shipment_request_id: str, carrier_id: str) -> str:
        return f"shipment:{shipment_request_id}:carrier:{carrier_id}:NEW_LOAD_ALERT"

    def _has_event(self, idempotency_key: str) -> bool:
        queued_key = f"{idempotency_key[:-5]}:queued" if idempotency_key.endswith(":sent") else idempotency_key
        return any(event.idempotency_key in {idempotency_key, queued_key} for event in self._event_log.events)
