"""SQL-backed, transactionally persisted WhatsApp notification intents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.domain.events import current_test_run_id
from app.infrastructure.adapters.whatsapp import (
    OutboundAction,
    OutboundMessage,
    OutboundResult,
    ProviderCapabilities,
    WhatsAppProvider,
)
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.models import (
    ConversationSessionRecord,
    MessageRecord,
    NotificationOutboxRecord,
)
from app.infrastructure.repositories.routing import RoutingOperationRecord


def _serialize_message(message: OutboundMessage) -> dict[str, Any]:
    return {
        "conversation_id": message.conversation_id,
        "body": message.body,
        "message_type": message.message_type,
        "correlation_id": message.correlation_id,
        "metadata": message.metadata,
        "actions": [action.as_metadata() for action in message.actions],
        "allowlist_phone_number": message.allowlist_phone_number,
    }


def _deserialize_message(payload: dict[str, Any]) -> OutboundMessage:
    actions = tuple(
        OutboundAction(
            id=str(item["id"]),
            label=str(item["label"]),
            value=str(item["value"]),
            kind=str(item.get("kind", "quick_reply")),
            metadata=item.get("metadata", {}),
        )
        for item in payload.get("actions", [])
    )
    return OutboundMessage(
        conversation_id=str(payload["conversation_id"]),
        body=str(payload["body"]),
        message_type=str(payload.get("message_type", "text")),
        correlation_id=payload.get("correlation_id"),
        metadata=payload.get("metadata", {}),
        actions=actions,
        allowlist_phone_number=payload.get("allowlist_phone_number"),
    )


class SqlNotificationOutboxProvider:
    """Provider-shaped adapter that queues instead of making network calls."""

    def __init__(self, *, provider: WhatsAppProvider, session: Session) -> None:
        self.provider_name = provider.provider_name
        self.provider_scope = getattr(provider, "outbound_scope", None)
        self.capabilities: ProviderCapabilities = provider.capabilities
        self._provider = provider
        self._session = session

    def normalize_inbound(self, *, payload: dict[str, Any], headers: dict[str, str]):
        return self._provider.normalize_inbound(payload=payload, headers=headers)

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        key = message.metadata.get("outbox_idempotency_key") or message.correlation_id
        if not key:
            raise ValueError("Outbox messages require a deterministic correlation/idempotency key")
        key = str(key)
        payload = _serialize_message(message)
        metadata = dict(payload["metadata"])
        test_run_id = metadata.get("qa_test_run_id") or current_test_run_id.get()
        self._session.flush()
        session_context = self._snapshot_conversation_context(message, test_run_id)
        if session_context is not None:
            metadata.update(session_context)
        metadata["outbox_idempotency_key"] = key
        if test_run_id:
            metadata["qa_test_run_id"] = str(test_run_id)
        payload["metadata"] = metadata
        existing = self._session.scalar(
            select(NotificationOutboxRecord).where(NotificationOutboxRecord.idempotency_key == key)
        )
        if existing is None:
            entity_type = metadata.get("entity_type")
            entity_id = metadata.get("entity_id")
            record = NotificationOutboxRecord(
                id=f"out_{uuid4().hex}",
                idempotency_key=key,
                provider=self.provider_name,
                provider_scope=self.provider_scope,
                message_payload=payload,
                entity_type=str(entity_type) if entity_type else None,
                entity_id=str(entity_id) if entity_id else None,
                test_run_id=str(test_run_id) if test_run_id else None,
                status="PENDING",
                attempts=0,
                available_at=datetime.now(UTC),
            )
            self._session.add(record)
            self._session.flush()
            existing = record
        elif existing.message_payload != payload:
            raise ValueError("Outbox idempotency key was reused with a different message payload")
        return OutboundResult(
            provider=self.provider_name,
            accepted=True,
            correlation_id=key,
            payload={"outbox_queued": True, "outbox_id": existing.id},
        )

    def _snapshot_conversation_context(
        self,
        message: OutboundMessage,
        test_run_id: str | None,
    ) -> dict[str, str] | None:
        metadata = message.metadata
        if metadata.get("entity_type") == "ConversationSession" and metadata.get("entity_id"):
            conversation = self._session.get(ConversationSessionRecord, str(metadata["entity_id"]))
            if conversation is None:
                return {"conversation_session_id": str(metadata["entity_id"])}
            return {
                "conversation_session_id": conversation.id,
                **({"qa_role": conversation.role_override} if conversation.role_override else {}),
                **({"qa_test_run_id": str(test_run_id)} if test_run_id else {}),
            }

        raw_phone = (
            message.allowlist_phone_number
            or metadata.get("producer_phone_number")
            or message.conversation_id
        )
        try:
            phone = normalize_phone_number(str(raw_phone))
        except PhoneNormalizationError:
            return None
        candidates = self._session.scalars(
            select(ConversationSessionRecord).where(
                (ConversationSessionRecord.normalized_phone_number == phone)
                | (ConversationSessionRecord.participant_phone == phone)
            )
        ).all()
        if test_run_id:
            candidates = [candidate for candidate in candidates if candidate.active_test_run_id == test_run_id]
        else:
            candidates = [candidate for candidate in candidates if candidate.status == "OPEN"]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.last_message_at or item.started_at, reverse=True)
        selected = candidates[0]
        return {
            "conversation_session_id": selected.id,
            **({"qa_role": metadata.get("qa_role") or selected.role_override} if metadata.get("qa_role") or selected.role_override else {}),
            **({"qa_test_run_id": str(test_run_id)} if test_run_id else {}),
        }


class NotificationOutboxDispatcher:
    """Dispatch queued messages only after their business transaction commits.

    A network exception is inherently ambiguous: the provider might have
    accepted a request before the connection failed. Such rows are quarantined
    for reconciliation and are never retried automatically.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        provider: WhatsAppProvider,
        max_attempts: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._max_attempts = max_attempts

    def dispatch_one(self) -> str | None:
        self._quarantine_stale_claims()
        claimed = self._claim_next()
        if claimed is None:
            return None
        record_id, payload, queued_provider, queued_scope = claimed
        active_provider = self._provider.provider_name
        active_scope = getattr(self._provider, "outbound_scope", None)
        if queued_provider != active_provider or queued_scope != active_scope:
            self._finish(
                record_id,
                status="CONFIGURATION_MISMATCH",
                error_code="provider_or_account_changed",
            )
            return "CONFIGURATION_MISMATCH"
        message = _deserialize_message(payload)
        try:
            if message.metadata.get("routing_guard") or message.metadata.get("notification_type") == "TRIP_TRACKING":
                from app.infrastructure.db.routing_guard import route_message_allowed
                with self._session_factory() as guard_session, guard_session.begin():
                    try:
                        allowed = route_message_allowed(guard_session, message)
                    except ValueError:
                        allowed = False
                    if not allowed:
                        self._finish(record_id, status="CANCELLED", error_code="routing_context_changed")
                        return "CANCELLED"
                    result = self._provider.send_message(message)
            else:
                result = self._provider.send_message(message)
        except Exception as exc:  # noqa: BLE001
            self._finish(
                record_id,
                status="RECONCILE_REQUIRED",
                error_code=exc.__class__.__name__,
            )
            return "RECONCILE_REQUIRED"

        if not result.accepted:
            self._retry_rejected(record_id)
            return "RETRY" if self._attempt_count(record_id) < self._max_attempts else "FAILED"

        with self._session_factory() as session, session.begin():
            record = session.get(NotificationOutboxRecord, record_id)
            if record is None or record.status != "PROCESSING":
                return "LOST_CLAIM"
            record.status = "ACCEPTED"
            record.provider_message_id = result.provider_message_id
            record.last_error_code = None
            metadata = message.metadata
            session_id = str(metadata["conversation_session_id"]) if metadata.get("conversation_session_id") else None
            if session_id:
                existing = session.scalar(
                    select(MessageRecord).where(
                        MessageRecord.idempotency_key == f"{record.idempotency_key}:outbound"
                    )
                )
                if existing is None:
                    session.add(
                        MessageRecord(
                            id=f"msg_{uuid4().hex}",
                            conversation_session_id=str(session_id),
                            provider=result.provider,
                            direction="outbound",
                            sender_type="Agent",
                            message_type=message.message_type,
                            test_run_id=record.test_run_id,
                            provider_message_id=result.provider_message_id,
                            idempotency_key=f"{record.idempotency_key}:outbound",
                            raw_content=message.body,
                            normalized_content=message.body,
                            sent_at=datetime.now(UTC),
                            correlation_id=record.idempotency_key,
                            related_entity_ids=self._related_message_ids(message, record.test_run_id),
                        )
                    )
            event_log = SqlEventLogService(session)
            event_log.record(
                event_type="NOTIFICATION_OUTBOX_ACCEPTED",
                actor_type="SYSTEM",
                entity_type=record.entity_type or "Notification",
                entity_id=record.entity_id or record.id,
                summary="Proveedor acepto una notificacion encolada",
                related_entity_ids={"outboxId": record.id},
                payload={
                    "provider": result.provider,
                    "provider_message_id": result.provider_message_id,
                    "attempts": record.attempts,
                },
                source="notification_outbox",
                correlation_id=record.idempotency_key,
                idempotency_key=f"{record.idempotency_key}:outbox_accepted",
                test_run_id=record.test_run_id,
            )
            notification_type = str(metadata.get("notification_type", ""))
            if metadata.get("entity_type") == "ConversationSession":
                accepted_event_type = "CONVERSATION_REPLY_SENT"
                accepted_summary = "Proveedor acepto la respuesta conversacional"
            elif metadata.get("producer_phone_number"):
                accepted_event_type = "PRODUCER_NOTIFICATION_SENT"
                accepted_summary = "Proveedor acepto la notificacion a productor"
            elif metadata.get("carrier_id"):
                accepted_event_type = "CARRIER_NOTIFICATION_SENT"
                accepted_summary = "Proveedor acepto la notificacion a transportista"
            else:
                accepted_event_type = None
                accepted_summary = ""
            if accepted_event_type:
                event_log.record(
                    event_type=accepted_event_type,
                    actor_type="SYSTEM",
                    entity_type=record.entity_type or "Notification",
                    entity_id=record.entity_id or record.id,
                    summary=accepted_summary,
                    related_entity_ids={
                        "outboxId": record.id,
                        **({"carrierId": str(metadata["carrier_id"])} if metadata.get("carrier_id") else {}),
                        **({"qaRole": str(metadata["qa_role"])} if metadata.get("qa_role") else {}),
                    },
                    payload={
                        "provider": result.provider,
                        "provider_message_id": result.provider_message_id,
                        "notification_type": notification_type,
                        "outbox_id": record.id,
                        **self._response_routing_metadata(metadata, message),
                    },
                    source="notification_outbox",
                    correlation_id=record.idempotency_key,
                    idempotency_key=f"{record.idempotency_key}:provider_accepted",
                    test_run_id=record.test_run_id,
                )
        return "ACCEPTED"

    @staticmethod
    def _related_message_ids(message: OutboundMessage, test_run_id: str | None) -> dict[str, str]:
        related: dict[str, str] = {}
        if test_run_id:
            related["testRunId"] = test_run_id
        role = message.metadata.get("qa_role")
        if role:
            related["qaRole"] = str(role)
        return related

    @staticmethod
    def _response_routing_metadata(metadata: dict[str, Any], message: OutboundMessage) -> dict[str, Any]:
        routing: dict[str, Any] = {
            "interactive_delivery": metadata.get("interactive_delivery", "text"),
            "message_type": message.message_type,
        }
        shipment_request_id = metadata.get("shipment_request_id") or metadata.get("entity_id")
        if shipment_request_id and metadata.get("entity_type") == "ShipmentRequest":
            routing["shipment_request_id"] = str(shipment_request_id)
        if message.actions:
            routing["interactive_actions"] = [action.as_metadata() for action in message.actions]
        if metadata.get("carrier_id"):
            routing["carrier_id"] = str(metadata["carrier_id"])
        return routing

    def _claim_next(self) -> tuple[str, dict[str, Any], str, str | None] | None:
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            candidate = session.scalar(
                select(NotificationOutboxRecord)
                .where(
                    NotificationOutboxRecord.status.in_(("PENDING", "RETRY")),
                    NotificationOutboxRecord.available_at <= now,
                )
                .order_by(NotificationOutboxRecord.created_at, NotificationOutboxRecord.id)
                .limit(1)
            )
            if candidate is None:
                return None
            claimed = session.execute(
                update(NotificationOutboxRecord)
                .where(
                    NotificationOutboxRecord.id == candidate.id,
                    NotificationOutboxRecord.status == candidate.status,
                )
                .values(
                    status="PROCESSING",
                    attempts=NotificationOutboxRecord.attempts + 1,
                    processing_started_at=now,
                )
            )
            if claimed.rowcount != 1:
                return None
            return (
                candidate.id,
                dict(candidate.message_payload),
                candidate.provider,
                candidate.provider_scope,
            )

    def _quarantine_stale_claims(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(minutes=5)
        with self._session_factory() as session, session.begin():
            stale_ids = session.scalars(
                select(NotificationOutboxRecord).where(
                    NotificationOutboxRecord.status == "PROCESSING",
                    NotificationOutboxRecord.processing_started_at < cutoff,
                )
            ).all()
            for stale_record in stale_ids:
                claimed = session.execute(
                    update(NotificationOutboxRecord)
                    .where(
                        NotificationOutboxRecord.id == stale_record.id,
                        NotificationOutboxRecord.status == "PROCESSING",
                        NotificationOutboxRecord.processing_started_at < cutoff,
                    )
                    .values(status="RECONCILE_REQUIRED", last_error_code="worker_claim_expired")
                )
                if claimed.rowcount != 1:
                    continue
                SqlEventLogService(session).record(
                    event_type="NOTIFICATION_OUTBOX_RECONCILE_REQUIRED",
                    actor_type="SYSTEM",
                    entity_type=stale_record.entity_type or "Notification",
                    entity_id=stale_record.entity_id or stale_record.id,
                    summary="Proceso de envio interrumpido; requiere conciliacion manual",
                    related_entity_ids={"outboxId": stale_record.id},
                    payload={"error_code": "worker_claim_expired", "attempts": stale_record.attempts},
                    source="notification_outbox",
                    correlation_id=stale_record.idempotency_key,
                    idempotency_key=f"{stale_record.idempotency_key}:outbox_reconcile_required",
                    test_run_id=stale_record.test_run_id,
                )

    def _finish(self, record_id: str, *, status: str, error_code: str) -> None:
        with self._session_factory() as session, session.begin():
            record = session.get(NotificationOutboxRecord, record_id)
            if record is not None and record.status == "PROCESSING":
                record.status = status
                record.last_error_code = error_code[:128]
                SqlEventLogService(session).record(
                    event_type=f"NOTIFICATION_OUTBOX_{status}",
                    actor_type="SYSTEM",
                    entity_type=record.entity_type or "Notification",
                    entity_id=record.entity_id or record.id,
                    summary=(
                        "Notificacion encolada requiere conciliacion manual"
                        if status == "RECONCILE_REQUIRED"
                        else "Notificacion encolada detenida por cambio de proveedor/cuenta"
                    ),
                    related_entity_ids={"outboxId": record.id},
                    payload={"error_code": error_code[:128], "attempts": record.attempts},
                    source="notification_outbox",
                    correlation_id=record.idempotency_key,
                    idempotency_key=f"{record.idempotency_key}:outbox_{status.lower()}",
                    test_run_id=record.test_run_id,
                )
                metadata = record.message_payload.get("metadata", {})
                checkpoint_id = metadata.get("checkpoint_id")
                if status == "CONFIGURATION_MISMATCH" and checkpoint_id and record.message_payload.get("message_type") == "location_request":
                    checkpoint = session.get(RoutingOperationRecord, str(checkpoint_id))
                    if checkpoint and checkpoint.status == "REQUESTED":
                        checkpoint.status = "CANCELLED"
                        for job in session.scalars(select(RoutingOperationRecord).where(
                            RoutingOperationRecord.kind == "job",
                            RoutingOperationRecord.entity_id == checkpoint.entity_id,
                            RoutingOperationRecord.test_run_id == checkpoint.test_run_id,
                            RoutingOperationRecord.status == "PENDING",
                        )).all():
                            if job.data.get("checkpoint_id") == checkpoint.id and job.data.get("action") in {"REMIND", "OVERDUE"}:
                                job.status = "CANCELLED"
                        SqlEventLogService(session).record(
                            event_type="TRIP_LOCATION_REQUEST_CANCELLED",
                            actor_type="SYSTEM",
                            entity_type="Trip",
                            entity_id=checkpoint.entity_id,
                            summary="Solicitud de ubicación cancelada porque el aviso no se envió",
                            related_entity_ids={"checkpointId": checkpoint.id, "outboxId": record.id},
                            payload={"stage": checkpoint.data.get("stage"), "error_code": error_code[:128]},
                            source="notification_outbox",
                            correlation_id=record.idempotency_key,
                            idempotency_key=f"{record.idempotency_key}:location_request_cancelled",
                            test_run_id=record.test_run_id,
                        )

    def _retry_rejected(self, record_id: str) -> None:
        with self._session_factory() as session, session.begin():
            record = session.get(NotificationOutboxRecord, record_id)
            if record is None or record.status != "PROCESSING":
                return
            if record.attempts >= self._max_attempts:
                status = "FAILED"
                available_at = record.available_at
            else:
                status = "RETRY"
                available_at = datetime.now(UTC) + timedelta(seconds=min(30 * 2 ** (record.attempts - 1), 1800))
            record.status = status
            record.available_at = available_at
            record.last_error_code = "provider_rejected"
            SqlEventLogService(session).record(
                event_type=f"NOTIFICATION_OUTBOX_{status}",
                actor_type="SYSTEM",
                entity_type=record.entity_type or "Notification",
                entity_id=record.entity_id or record.id,
                summary="Proveedor rechazo una notificacion encolada",
                related_entity_ids={"outboxId": record.id},
                payload={"error_code": "provider_rejected", "attempts": record.attempts},
                source="notification_outbox",
                correlation_id=record.idempotency_key,
                idempotency_key=f"{record.idempotency_key}:outbox_attempt_{record.attempts}",
                test_run_id=record.test_run_id,
            )

    def _attempt_count(self, record_id: str) -> int:
        with self._session_factory() as session:
            record = session.get(NotificationOutboxRecord, record_id)
            return record.attempts if record else self._max_attempts


def cancel_unstarted_test_run_notifications(session: Session, test_run_id: str) -> int:
    """Cancel only pending/retry notices when a QA scenario closes."""
    session.flush()
    rows = session.scalars(
        select(NotificationOutboxRecord).where(
            NotificationOutboxRecord.test_run_id == test_run_id,
            NotificationOutboxRecord.status.in_(("PENDING", "RETRY")),
        )
    ).all()
    changed = 0
    event_log = SqlEventLogService(session)
    for row in rows:
        cancelled = session.execute(
            update(NotificationOutboxRecord)
            .where(
                NotificationOutboxRecord.id == row.id,
                NotificationOutboxRecord.status.in_(("PENDING", "RETRY")),
            )
            .values(status="CANCELLED", last_error_code="qa_scenario_closed")
        )
        if cancelled.rowcount != 1:
            continue
        event_log.record(
            event_type="NOTIFICATION_OUTBOX_CANCELLED",
            actor_type="SYSTEM",
            entity_type=row.entity_type or "Notification",
            entity_id=row.entity_id or row.id,
            summary="Aviso pendiente cancelado al cerrar escenario QA",
            related_entity_ids={"outboxId": row.id},
            payload={"reason": "qa_scenario_closed", "attempts": row.attempts},
            source="notification_outbox",
            correlation_id=row.idempotency_key,
            idempotency_key=f"{row.idempotency_key}:qa_scenario_cancelled",
            test_run_id=test_run_id,
        )
        changed += 1
    return changed
