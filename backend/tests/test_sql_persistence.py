from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import Assignment, Carrier, ConversationSession, Message, ShipmentRequest, TripOffer
from app.infrastructure.db.base import Base
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.models import AssignmentRecord, CarrierRecord, EventLogRecord, ShipmentRequestRecord, TripRecord
from app.infrastructure.db.repositories import (
    SqlAssignmentRepository,
    SqlCarrierRepository,
    SqlConversationSessionRepository,
    SqlMessageRepository,
    SqlShipmentRequestRepository,
    SqlTripOfferRepository,
)
from app.infrastructure.db.unit_of_work import SqlUnitOfWork, build_sql_admin_ops_service


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    yield factory
    Base.metadata.drop_all(engine)


def test_sql_repositories_persist_core_entities(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        conversations = SqlConversationSessionRepository(session)
        messages = SqlMessageRepository(session)
        shipments = SqlShipmentRequestRepository(session)
        offers = SqlTripOfferRepository(session)
        assignments = SqlAssignmentRepository(session)
        event_log = SqlEventLogService(session)

        conversation = conversations.add(ConversationSession(channel="kapso", role_override="Producer"))
        message = messages.add(
            Message(
                conversation_session_id=conversation.id,
                provider="kapso",
                direction="inbound",
                sender_type="Producer",
                raw_content="35 novillos de Azul a Cañuelas",
                idempotency_key="msg_1",
            )
        )
        shipment = shipments.add(
            ShipmentRequest(
                status="MATCHING",
                source_message_id=message.id,
                missing_critical_fields=[],
                requires_human_review=False,
            )
        )
        offer = offers.add(
            TripOffer(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                response_type="INTERESTED",
            )
        )
        assignment = assignments.add(
            Assignment(
                shipment_request_id=shipment.id,
                trip_offer_id=offer.id,
                carrier_id="car_1",
                selected_by_user_id="user_operator",
            )
        )
        event = event_log.record(
            event_type="MESSAGE_RECEIVED",
            actor_type="Producer",
            entity_type="Message",
            entity_id=message.id,
            summary="Mensaje recibido",
            idempotency_key="event_1",
        )
        session.commit()

    with session_factory() as session:
        stored_conversation = SqlConversationSessionRepository(session).get(conversation.id)
        assert stored_conversation is not None
        assert stored_conversation.role_override == "Producer"
        assert SqlMessageRepository(session).get(message.id).raw_content == "35 novillos de Azul a Cañuelas"  # type: ignore[union-attr]
        assert SqlShipmentRequestRepository(session).get(shipment.id).status == "MATCHING"  # type: ignore[union-attr]
        assert SqlTripOfferRepository(session).get(offer.id).carrier_id == "car_1"  # type: ignore[union-attr]
        assert SqlAssignmentRepository(session).get(assignment.id).trip_offer_id == offer.id  # type: ignore[union-attr]
        assert SqlEventLogService(session).events[0].event_id == event.event_id


def test_sql_persists_contact_provider_mapping(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        carrier = SqlCarrierRepository(session).add(
            Carrier(
                name="Carrier Test",
                contact_phone="11 15 1234 5678",
                normalized_phone_number="+5491112345678",
                provider_name="kapso",
                provider_contact_id="contact_1",
                provider_conversation_id="conv_1",
            )
        )
        session.commit()

    with session_factory() as session:
        record = session.get(CarrierRecord, carrier.id)

    assert record is not None
    assert record.normalized_phone_number == "+5491112345678"
    assert record.provider_name == "kapso"
    assert record.provider_contact_id == "contact_1"
    assert record.provider_conversation_id == "conv_1"


def test_sql_event_log_idempotency_returns_existing_event(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        event_log = SqlEventLogService(session)
        first = event_log.record(
            event_type="LOAD_CREATED",
            actor_type="System",
            entity_type="ShipmentRequest",
            entity_id="sr_1",
            summary="Carga creada",
            idempotency_key="load_created_1",
        )
        second = event_log.record(
            event_type="LOAD_CREATED",
            actor_type="System",
            entity_type="ShipmentRequest",
            entity_id="sr_1",
            summary="Carga creada duplicada",
            idempotency_key="load_created_1",
        )

        assert second.event_id == first.event_id
        assert len(event_log.events) == 1


def test_sql_confirm_assignment_creates_trip_and_events_transactionally(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(status="MATCHING", missing_critical_fields=[], requires_human_review=False)
        )
        assignment = SqlAssignmentRepository(session).add(
            Assignment(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                selected_by_user_id="user_operator",
            )
        )
        session.commit()

    with session_factory() as session:
        result = SqlUnitOfWork(session).confirm_assignment(
            assignment_id=assignment.id,
            operator_user_id="user_operator",
            confirmation_notes="partes confirmadas",
            idempotency_key="confirm_sql_1",
        )

        assert result.assignment.status == "CONFIRMED"
        assert result.trip.status == "PLANNED"

    with session_factory() as session:
        stored_assignment = session.get(AssignmentRecord, assignment.id)
        stored_shipment = session.get(ShipmentRequestRecord, shipment.id)
        trips = session.scalars(select(TripRecord)).all()
        events = session.scalars(select(EventLogRecord)).all()

        assert stored_assignment is not None
        assert stored_assignment.status == "CONFIRMED"
        assert stored_shipment is not None
        assert stored_shipment.status == "ASSIGNED"
        assert len(trips) == 1
        assert {event.event_type for event in events} == {
            "ASSIGNMENT_CREATED",
            "ASSIGNMENT_CONFIRMED",
            "TRIP_CREATED",
        }


def test_sql_transaction_rolls_back_assignment_trip_and_event_logs(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        shipment = SqlShipmentRequestRepository(session).add(
            ShipmentRequest(status="MATCHING", missing_critical_fields=[], requires_human_review=False)
        )
        assignment = SqlAssignmentRepository(session).add(
            Assignment(
                shipment_request_id=shipment.id,
                carrier_id="car_1",
                selected_by_user_id="user_operator",
            )
        )
        session.commit()

    with pytest.raises(RuntimeError):
        with session_factory() as session:
            with SqlUnitOfWork(session).transaction() as service:
                service.confirm_assignment(
                    assignment_id=assignment.id,
                    operator_user_id="user_operator",
                    idempotency_key="confirm_sql_rollback",
                )
                raise RuntimeError("simulate failure after critical writes")

    with session_factory() as session:
        stored_assignment = session.get(AssignmentRecord, assignment.id)
        stored_shipment = session.get(ShipmentRequestRecord, shipment.id)
        trips = session.scalars(select(TripRecord)).all()
        events = session.scalars(select(EventLogRecord)).all()

        assert stored_assignment is not None
        assert stored_assignment.status == "PROPOSED"
        assert stored_shipment is not None
        assert stored_shipment.status == "MATCHING"
        assert trips == []
        assert events == []


def test_sql_admin_ops_service_uses_sql_repositories(legacy_broadcast, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = build_sql_admin_ops_service(session)
        shipment = SqlShipmentRequestRepository(session).add(ShipmentRequest(status="VALIDATED"))
        session.commit()

    with session_factory() as session:
        service = build_sql_admin_ops_service(session)
        result = service.publish_shipment(
            shipment_request_id=shipment.id,
            operator_user_id="user_operator",
            carrier_ids=["car_1"],
            idempotency_key="publish_sql_1",
        )
        session.commit()

        assert result.shipment.status == "PUBLISHED"
        assert [event.event_type for event in result.events] == [
            "LOAD_PUBLISHED",
            "BROADCAST_SENT",
            "CARRIER_NOTIFIED",
        ]
