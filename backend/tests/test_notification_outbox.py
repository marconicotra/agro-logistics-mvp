from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.adapters.whatsapp import (
    MockWhatsAppProvider,
    OutboundAction,
    OutboundMessage,
    OutboundResult,
    ProviderCapabilities,
)
from app.infrastructure.db.base import Base
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.models import (
    ConversationSessionRecord,
    EventLogRecord,
    MessageRecord,
    NotificationOutboxRecord,
)
from app.infrastructure.db.notification_outbox import (
    NotificationOutboxDispatcher,
    SqlNotificationOutboxProvider,
    cancel_unstarted_test_run_notifications,
)
from app.infrastructure.db.notification_outbox_admin import SqlNotificationOutboxReadRepository


@pytest.fixture()
def outbox_runtime(tmp_path) -> Iterator[tuple[sessionmaker[Session], object]]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'outbox.db'}"
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    yield factory, engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_sql_provider_queues_idempotently_without_sending(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = MockWhatsAppProvider()
    message = OutboundMessage(
        conversation_id="+5491112345678",
        body="Aviso sintetico",
        correlation_id="shipment:one:carrier:one:NEW_LOAD_ALERT",
        metadata={"entity_type": "ShipmentRequest", "entity_id": "shipment-one"},
    )

    with factory() as session, session.begin():
        queue = SqlNotificationOutboxProvider(provider=provider, session=session)
        first = queue.send_message(message)
        second = queue.send_message(message)
        assert first.payload["outbox_id"] == second.payload["outbox_id"]

    assert provider.sent_messages == []
    with factory() as session:
        rows = session.scalars(select(NotificationOutboxRecord)).all()
    assert len(rows) == 1
    assert rows[0].status == "PENDING"
    assert rows[0].message_payload["body"] == "Aviso sintetico"


def test_outbox_key_is_independent_from_business_correlation(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = MockWhatsAppProvider()
    first = OutboundMessage(
        conversation_id="+5491112345678",
        body="Primer aviso",
        correlation_id="shipment:shared-correlation",
        metadata={"outbox_idempotency_key": "shipment:first:notice"},
    )
    second = OutboundMessage(
        conversation_id="+5491112345678",
        body="Segundo aviso",
        correlation_id="shipment:shared-correlation",
        metadata={"outbox_idempotency_key": "shipment:second:notice"},
    )
    with factory() as session, session.begin():
        queue = SqlNotificationOutboxProvider(provider=provider, session=session)
        queue.send_message(first)
        queue.send_message(second)

    with factory() as session:
        rows = session.scalars(select(NotificationOutboxRecord).order_by(NotificationOutboxRecord.id)).all()
    assert len(rows) == 2
    assert {row.idempotency_key for row in rows} == {
        "shipment:first:notice",
        "shipment:second:notice",
    }


def test_reusing_outbox_key_with_changed_payload_is_rejected(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = MockWhatsAppProvider()
    with factory() as session, session.begin():
        queue = SqlNotificationOutboxProvider(provider=provider, session=session)
        queue.send_message(
            OutboundMessage(
                conversation_id="+5491112345678",
                body="Original",
                correlation_id="same-business-correlation",
                metadata={"outbox_idempotency_key": "one-message-key"},
            )
        )
    with factory() as session, session.begin():
        queue = SqlNotificationOutboxProvider(provider=provider, session=session)
        with pytest.raises(ValueError, match="different message payload"):
            queue.send_message(
                OutboundMessage(
                    conversation_id="+5491112345678",
                    body="Altered",
                    correlation_id="same-business-correlation",
                    metadata={"outbox_idempotency_key": "one-message-key"},
                )
            )


def test_dispatcher_marks_accepted_and_audits(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = MockWhatsAppProvider()
    message = OutboundMessage(
        conversation_id="+5491112345678",
        body="Aviso sintetico",
        correlation_id="shipment:two:carrier:one:NEW_LOAD_ALERT",
        metadata={"entity_type": "ShipmentRequest", "entity_id": "shipment-two"},
    )
    with factory() as session, session.begin():
        session.add(
            ConversationSessionRecord(
                id="cs_outbox",
                channel="whatsapp",
                normalized_phone_number="+5491112345678",
                participant_phone="+5491112345678",
                status="OPEN",
            )
        )
        SqlNotificationOutboxProvider(provider=provider, session=session).send_message(message)

    dispatcher = NotificationOutboxDispatcher(session_factory=factory, provider=provider)
    assert dispatcher.dispatch_one() == "ACCEPTED"
    assert dispatcher.dispatch_one() is None
    with factory() as session:
        row = session.scalar(select(NotificationOutboxRecord))
        events = SqlEventLogService(session).list()
        messages = session.scalars(select(MessageRecord)).all()
    assert row is not None
    assert row.status == "ACCEPTED"
    assert row.provider_message_id is not None
    assert any(event.event_type == "NOTIFICATION_OUTBOX_ACCEPTED" for event in events)
    assert len(messages) == 1
    assert messages[0].sender_type == "Agent"
    assert messages[0].raw_content == "Aviso sintetico"
    assert len(provider.sent_messages) == 1


def test_dispatcher_uses_enqueued_qa_context_and_preserves_response_routing(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = MockWhatsAppProvider()
    with factory() as session, session.begin():
        session.add_all(
            [
                ConversationSessionRecord(
                    id="cs_qa_one",
                    channel="whatsapp",
                    normalized_phone_number="+5491112345678",
                    participant_phone="+5491112345678",
                    role_override="Producer",
                    active_test_run_id="qa_one",
                    status="OPEN",
                ),
                ConversationSessionRecord(
                    id="cs_qa_two",
                    channel="whatsapp",
                    normalized_phone_number="+5491112345678",
                    participant_phone="+5491112345678",
                    role_override="Carrier",
                    active_test_run_id="qa_two",
                    status="OPEN",
                ),
            ]
        )
        SqlNotificationOutboxProvider(provider=provider, session=session).send_message(
            OutboundMessage(
                conversation_id="+5491112345678",
                body="Nueva carga sintetica",
                correlation_id="shipment:qa_one:carrier:c1:alert",
                actions=(OutboundAction(id="interested", label="Me interesa", value="INTERESTED"),),
                metadata={
                    "outbox_idempotency_key": "shipment:qa_one:carrier:c1:alert:message",
                    "qa_test_run_id": "qa_one",
                    "carrier_id": "c1",
                    "entity_type": "ShipmentRequest",
                    "entity_id": "shipment_qa_one",
                    "notification_type": "NEW_LOAD_ALERT",
                },
            )
        )
        selected = session.get(ConversationSessionRecord, "cs_qa_one")
        assert selected is not None
        selected.role_override = "Carrier"
        selected.status = "CLOSED"

    dispatcher = NotificationOutboxDispatcher(session_factory=factory, provider=provider)
    assert dispatcher.dispatch_one() == "ACCEPTED"
    with factory() as session:
        outbound = session.scalar(select(MessageRecord))
        events = SqlEventLogService(session).list()
    assert outbound is not None
    assert outbound.conversation_session_id == "cs_qa_one"
    assert outbound.test_run_id == "qa_one"
    assert outbound.related_entity_ids == {"testRunId": "qa_one", "qaRole": "Producer"}
    accepted = next(event for event in events if event.event_type == "CARRIER_NOTIFICATION_SENT")
    assert accepted.payload["shipment_request_id"] == "shipment_qa_one"
    assert accepted.payload["interactive_actions"][0]["id"] == "interested"


class RaisingProvider:
    provider_name = "fake"
    capabilities = ProviderCapabilities()

    def __init__(self) -> None:
        self.calls = 0

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        del message
        self.calls += 1
        raise TimeoutError("provider response lost")


def test_ambiguous_provider_error_is_quarantined_without_retry(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    enqueue_provider = RaisingProvider()
    message = OutboundMessage(
        conversation_id="+5491112345678",
        body="Aviso sintetico",
        correlation_id="shipment:three:carrier:one:NEW_LOAD_ALERT",
    )
    with factory() as session, session.begin():
        SqlNotificationOutboxProvider(provider=enqueue_provider, session=session).send_message(message)

    dispatcher = NotificationOutboxDispatcher(session_factory=factory, provider=enqueue_provider)
    assert dispatcher.dispatch_one() == "RECONCILE_REQUIRED"
    assert dispatcher.dispatch_one() is None
    assert enqueue_provider.calls == 1
    with factory() as session:
        row = session.scalar(select(NotificationOutboxRecord))
        events = session.scalars(select(EventLogRecord)).all()
    assert row is not None
    assert row.status == "RECONCILE_REQUIRED"
    assert row.last_error_code == "TimeoutError"
    assert any(event.event_type == "NOTIFICATION_OUTBOX_RECONCILE_REQUIRED" for event in events)


def test_transaction_rollback_removes_queued_intention(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = MockWhatsAppProvider()
    with pytest.raises(RuntimeError):
        with factory() as session, session.begin():
            SqlNotificationOutboxProvider(provider=provider, session=session).send_message(
                OutboundMessage(
                    conversation_id="+5491112345678",
                    body="Aviso sintetico",
                    correlation_id="shipment:rollback:carrier:one:NEW_LOAD_ALERT",
                )
            )
            raise RuntimeError("force rollback")

    assert provider.sent_messages == []
    with factory() as session:
        assert session.scalar(select(NotificationOutboxRecord)) is None


class ScopedProvider:
    provider_name = "kapso"
    capabilities = ProviderCapabilities()

    def __init__(self, outbound_scope: str) -> None:
        self.outbound_scope = outbound_scope
        self.calls = 0

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        del message
        self.calls += 1
        return OutboundResult(provider=self.provider_name, accepted=True)


def test_dispatcher_stops_if_kapso_phone_number_scope_changed(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    queue_provider = ScopedProvider("sandbox-phone-id")
    with factory() as session, session.begin():
        SqlNotificationOutboxProvider(provider=queue_provider, session=session).send_message(
            OutboundMessage(
                conversation_id="+5491112345678",
                body="Aviso sintetico",
                correlation_id="scope-protection-key",
            )
        )

    changed_provider = ScopedProvider("production-phone-id")
    dispatcher = NotificationOutboxDispatcher(session_factory=factory, provider=changed_provider)
    assert dispatcher.dispatch_one() == "CONFIGURATION_MISMATCH"
    assert changed_provider.calls == 0
    with factory() as session:
        row = session.scalar(select(NotificationOutboxRecord))
    assert row is not None
    assert row.status == "CONFIGURATION_MISMATCH"


class RejectingProvider:
    provider_name = "mock_whatsapp"
    capabilities = ProviderCapabilities()

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        del message
        return OutboundResult(provider=self.provider_name, accepted=False)


def test_explicit_rejections_retry_with_limit(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    provider = RejectingProvider()
    with factory() as session, session.begin():
        SqlNotificationOutboxProvider(provider=provider, session=session).send_message(
            OutboundMessage(
                conversation_id="+5491112345678",
                body="Aviso sintetico",
                correlation_id="retry-limit-key",
            )
        )

    dispatcher = NotificationOutboxDispatcher(
        session_factory=factory,
        provider=provider,
        max_attempts=3,
    )
    outcomes = []
    for _ in range(3):
        outcomes.append(dispatcher.dispatch_one())
        with factory() as session, session.begin():
            row = session.scalar(select(NotificationOutboxRecord))
            assert row is not None
            row.available_at = datetime.now(UTC) - timedelta(seconds=1)

    assert outcomes == ["RETRY", "RETRY", "FAILED"]
    with factory() as session:
        row = session.scalar(select(NotificationOutboxRecord))
    assert row is not None
    assert row.status == "FAILED"
    assert row.attempts == 3


def test_admin_reconciliation_retries_only_after_recording_evidence(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    with factory() as session, session.begin():
        session.add(
            NotificationOutboxRecord(
                id="outbox_reconcile_retry",
                idempotency_key="reconcile-retry-key",
                provider="kapso",
                provider_scope="sandbox-account",
                message_payload={"conversation_id": "+5491112345678", "body": "fake", "metadata": {}},
                status="RECONCILE_REQUIRED",
                attempts=1,
                available_at=datetime.now(UTC),
            )
        )
        session.flush()
        repository = SqlNotificationOutboxReadRepository(session)
        result = repository.reconcile(
            outbox_id="outbox_reconcile_retry",
            resolution="RETRY_NOT_SENT",
            evidence_reference="kapso-log-123",
            operator_user_id="operator-1",
        )
        assert result == "RETRY"

    with factory() as session:
        row = session.get(NotificationOutboxRecord, "outbox_reconcile_retry")
        events = SqlEventLogService(session).list()
    assert row is not None and row.status == "RETRY"
    event = next(item for item in events if item.event_type == "NOTIFICATION_OUTBOX_MANUALLY_RETRY_AUTHORIZED")
    assert event.actor_id == "operator-1"
    assert event.payload["evidence_reference"] == "kapso-log-123"


def test_admin_reconciliation_acceptance_is_audited_and_not_repeatable(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    with factory() as session, session.begin():
        session.add(
            NotificationOutboxRecord(
                id="outbox_reconcile_accept",
                idempotency_key="reconcile-accept-key",
                provider="kapso",
                provider_scope="sandbox-account",
                message_payload={"conversation_id": "+5491112345678", "body": "fake", "metadata": {}},
                status="RECONCILE_REQUIRED",
                attempts=1,
                available_at=datetime.now(UTC),
            )
        )
        session.flush()
        repository = SqlNotificationOutboxReadRepository(session)
        result = repository.reconcile(
            outbox_id="outbox_reconcile_accept",
            resolution="ACCEPTED",
            evidence_reference="provider-event-123",
            operator_user_id="admin-1",
        )
        assert result == "ACCEPTED"
        with pytest.raises(ValueError, match="awaiting reconciliation"):
            repository.reconcile(
                outbox_id="outbox_reconcile_accept",
                resolution="RETRY_NOT_SENT",
                evidence_reference="provider-event-123",
                operator_user_id="admin-1",
            )

    with factory() as session:
        events = SqlEventLogService(session).list()
    assert any(event.event_type == "NOTIFICATION_OUTBOX_MANUALLY_ACCEPTED" for event in events)


def test_closing_qa_scenario_cancels_only_unstarted_notifications(outbox_runtime) -> None:
    factory, _ = outbox_runtime
    with factory() as session, session.begin():
        session.add_all(
            [
                NotificationOutboxRecord(
                    id=f"outbox_{status.lower()}",
                    idempotency_key=f"qa-close-{status.lower()}",
                    provider="kapso",
                    provider_scope="sandbox-account",
                    message_payload={"conversation_id": "+5491112345678", "body": "synthetic", "metadata": {}},
                    test_run_id="qa_close_test",
                    status=status,
                    attempts=0,
                    available_at=datetime.now(UTC),
                )
                for status in ("PENDING", "RETRY", "PROCESSING", "ACCEPTED")
            ]
        )
        changed = cancel_unstarted_test_run_notifications(session, "qa_close_test")
        assert changed == 2

    with factory() as session:
        rows = {
            row.id: row.status
            for row in session.scalars(select(NotificationOutboxRecord)).all()
        }
        events = SqlEventLogService(session).list()
    assert rows == {
        "outbox_pending": "CANCELLED",
        "outbox_retry": "CANCELLED",
        "outbox_processing": "PROCESSING",
        "outbox_accepted": "ACCEPTED",
    }
    cancelled_events = [event for event in events if event.event_type == "NOTIFICATION_OUTBOX_CANCELLED"]
    assert len(cancelled_events) == 2
    assert all(event.test_run_id == "qa_close_test" for event in cancelled_events)
