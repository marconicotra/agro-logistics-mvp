from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.notification_outbox_admin import (
    NotificationOutboxItem,
    NotificationOutboxStatus,
)
from app.infrastructure.db.models import MessageRecord, NotificationOutboxRecord
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.notification_outbox import NotificationOutboxDispatcher, _deserialize_message


class SqlNotificationOutboxReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def counts(self) -> dict[str, int]:
        counts = {state.value: 0 for state in NotificationOutboxStatus}
        rows = self._session.execute(
            select(NotificationOutboxRecord.status, func.count())
            .group_by(NotificationOutboxRecord.status)
        )
        counts.update({status: count for status, count in rows})
        return counts

    def list(
        self,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationOutboxItem], int]:
        statement = select(NotificationOutboxRecord)
        count_statement = select(func.count()).select_from(NotificationOutboxRecord)
        if status:
            statement = statement.where(NotificationOutboxRecord.status == status)
            count_statement = count_statement.where(NotificationOutboxRecord.status == status)
        rows = self._session.scalars(
            statement.order_by(
                NotificationOutboxRecord.created_at.desc(),
                NotificationOutboxRecord.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        total = int(self._session.scalar(count_statement) or 0)
        items = [
            NotificationOutboxItem(
                id=row.id,
                status=row.status,
                provider=row.provider,
                notification_type=(row.message_payload.get("metadata") or {}).get("notification_type"),
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                test_run_id=row.test_run_id,
                attempts=row.attempts,
                created_at=row.created_at,
                updated_at=row.updated_at,
                available_at=row.available_at,
                last_error_code=row.last_error_code,
            )
            for row in rows
        ]
        return items, total

    def reconcile(
        self,
        *,
        outbox_id: str,
        resolution: str,
        evidence_reference: str,
        operator_user_id: str,
    ) -> str:
        row = self._session.scalar(
            select(NotificationOutboxRecord)
            .where(NotificationOutboxRecord.id == outbox_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(outbox_id)
        if row.status != "RECONCILE_REQUIRED":
            raise ValueError("Only notifications awaiting reconciliation can be resolved")
        if resolution not in {"ACCEPTED", "RETRY_NOT_SENT"}:
            raise ValueError("Unsupported reconciliation resolution")

        now = datetime.now(UTC)
        metadata = row.message_payload.get("metadata") or {}
        message = _deserialize_message(dict(row.message_payload))
        if resolution == "ACCEPTED":
            row.status = "ACCEPTED"
            row.last_error_code = None
            session_id = metadata.get("conversation_session_id")
            if session_id:
                message_key = f"{row.idempotency_key}:outbound"
                existing = self._session.scalar(
                    select(MessageRecord).where(MessageRecord.idempotency_key == message_key)
                )
                if existing is None:
                    self._session.add(
                        MessageRecord(
                            id=f"msg_{uuid4().hex}",
                            conversation_session_id=str(session_id),
                            provider=row.provider,
                            direction="outbound",
                            sender_type="Agent",
                            message_type=message.message_type,
                            test_run_id=row.test_run_id,
                            idempotency_key=message_key,
                            raw_content=message.body,
                            normalized_content=message.body,
                            sent_at=now,
                            correlation_id=message.correlation_id,
                            related_entity_ids={
                                key: str(value)
                                for key, value in {
                                    "testRunId": row.test_run_id,
                                    "qaRole": metadata.get("qa_role"),
                                }.items()
                                if value
                            },
                    )
                    )
            notification_type = str(metadata.get("notification_type", ""))
            if metadata.get("carrier_id"):
                event_type = "CARRIER_NOTIFICATION_SENT"
                entity_type = str(metadata.get("entity_type") or "Notification")
                entity_id = str(metadata.get("entity_id") or row.id)
                related = {"carrierId": str(metadata["carrier_id"]), "outboxId": row.id}
            elif metadata.get("producer_phone_number"):
                event_type = "PRODUCER_NOTIFICATION_SENT"
                entity_type = str(metadata.get("entity_type") or "Notification")
                entity_id = str(metadata.get("entity_id") or row.id)
                related = {"outboxId": row.id}
            elif metadata.get("entity_type") == "ConversationSession":
                event_type = "CONVERSATION_REPLY_SENT"
                entity_type = "ConversationSession"
                entity_id = str(metadata.get("entity_id") or row.id)
                related = {"outboxId": row.id}
            else:
                event_type = "NOTIFICATION_OUTBOX_ACCEPTED_MANUALLY"
                entity_type = str(metadata.get("entity_type") or "Notification")
                entity_id = str(metadata.get("entity_id") or row.id)
                related = {"outboxId": row.id}
            SqlEventLogService(self._session).record(
                event_type=event_type,
                actor_type="OPERATOR",
                actor_id=operator_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                summary="Operador confirmo aceptacion del envio en conciliacion",
                related_entity_ids=related,
                payload={
                    "notification_type": notification_type,
                    "outbox_id": row.id,
                    **NotificationOutboxDispatcher._response_routing_metadata(metadata, message),
                },
                source="backoffice_notification_outbox",
                correlation_id=row.idempotency_key,
                idempotency_key=f"{row.idempotency_key}:manual_provider_accepted",
                test_run_id=row.test_run_id,
                occurred_at=now,
            )
        else:
            row.status = "RETRY"
            row.available_at = now
            row.last_error_code = None

        outcome = "ACCEPTED" if resolution == "ACCEPTED" else "RETRY_AUTHORIZED"
        SqlEventLogService(self._session).record(
            event_type=f"NOTIFICATION_OUTBOX_MANUALLY_{outcome}",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type=row.entity_type or "Notification",
            entity_id=row.entity_id or row.id,
            summary=(
                "Operador concilio aceptacion del proveedor"
                if resolution == "ACCEPTED"
                else "Operador autorizo reintento tras verificar que no hubo envio"
            ),
            related_entity_ids={"outboxId": row.id},
            payload={
                "evidence_reference": evidence_reference,
                "resolution": resolution,
                "attempts": row.attempts,
            },
            source="backoffice_notification_outbox",
            correlation_id=row.idempotency_key,
            idempotency_key=f"{row.idempotency_key}:manual_reconciliation:{uuid4().hex}",
            test_run_id=row.test_run_id,
            occurred_at=now,
        )
        return row.status
