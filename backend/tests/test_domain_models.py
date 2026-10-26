from decimal import Decimal

import pytest

from app.domain.models import (
    Assignment,
    Carrier,
    ConversationSession,
    Location,
    Message,
    PaymentTerms,
    Producer,
    RiskFlag,
    ShipmentRequest,
    Trip,
    TripOffer,
    User,
    Vehicle,
)
from app.domain.schemas import (
    AssignmentRead,
    ShipmentRequestRead,
    TripOfferRead,
    TripRead,
)
from app.infrastructure.repositories.memory import InMemoryRepository


def test_core_actor_models_validate_required_fields() -> None:
    user = User(display_name="Operator", role="OPERATOR")
    producer = Producer(name="Estancia La Esperanza")
    carrier = Carrier(name="Transportes Norte")
    vehicle = Vehicle(carrier_id=carrier.id, capacity_estimate=Decimal("35"))

    assert user.id.startswith("user_")
    assert producer.id.startswith("prod_")
    assert carrier.id.startswith("car_")
    assert vehicle.carrier_id == carrier.id

    with pytest.raises(ValueError, match="name is required"):
        Producer(name="")


def test_shipment_request_trip_offer_assignment_and_trip_are_separate_models() -> None:
    shipment_request = ShipmentRequest(
        producer_id="prod_1",
        livestock_type="novillos",
        quantity_estimate=Decimal("35"),
        missing_critical_fields=["contact"],
        requires_human_review=True,
    )
    offer = TripOffer(
        shipment_request_id=shipment_request.id,
        carrier_id="car_1",
        response_type="PRICE_PROVIDED",
        price_estimate=Decimal("1000"),
    )
    assignment = Assignment(
        shipment_request_id=shipment_request.id,
        trip_offer_id=offer.id,
        carrier_id=offer.carrier_id,
        selected_by_user_id="user_operator",
    )
    trip = Trip(
        shipment_request_id=shipment_request.id,
        assignment_id=assignment.id,
        carrier_id=assignment.carrier_id,
    )

    assert shipment_request.status == "DRAFT"
    assert offer.status == "RECEIVED"
    assert assignment.status == "PROPOSED"
    assert trip.status == "PLANNED"
    assert offer.id != assignment.id
    assert trip.assignment_id == assignment.id


def test_message_and_conversation_session_do_not_require_business_entities() -> None:
    session = ConversationSession(channel="whatsapp", participant_phone="+549...")
    message = Message(
        conversation_session_id=session.id,
        provider="kapso",
        direction="inbound",
        sender_type="Producer",
        message_type="text",
        raw_content="Necesito camion para el martes",
    )

    assert session.id.startswith("cs_")
    assert message.conversation_session_id == session.id
    assert message.raw_content is not None


def test_supporting_models_keep_uncertainty_and_operational_context() -> None:
    location = Location(original_text="campo cerca de Rauch", confidence="medium")
    payment_terms = PaymentTerms(shipment_request_id="sr_1", amount_estimate=Decimal("1000"))
    risk_flag = RiskFlag(
        entity_type="TripOffer",
        entity_id="off_1",
        risk_type="ambiguous_response",
        severity="medium",
        reason="carrier said puede ser",
        created_by="AI_AGENT",
    )

    assert location.original_text == "campo cerca de Rauch"
    assert payment_terms.currency == "ARS"
    assert risk_flag.status == "OPEN"


def test_in_memory_repository_add_get_list_save_and_soft_delete() -> None:
    repository: InMemoryRepository[ShipmentRequest] = InMemoryRepository()
    shipment_request = repository.add(ShipmentRequest(producer_id="prod_1"))

    assert repository.get(shipment_request.id) is shipment_request
    assert repository.list() == [shipment_request]

    shipment_request.status = "INCOMPLETE"
    repository.save(shipment_request)
    assert repository.get(shipment_request.id).status == "INCOMPLETE"  # type: ignore[union-attr]

    repository.soft_delete(shipment_request.id)
    assert repository.list() == []
    assert repository.list(include_deleted=True) == [shipment_request]


def test_read_schemas_from_domain_models() -> None:
    shipment_request = ShipmentRequest(
        missing_critical_fields=["origin"],
        requires_human_review=True,
    )
    offer = TripOffer(
        shipment_request_id=shipment_request.id,
        carrier_id="car_1",
        response_type="INTERESTED",
    )
    assignment = Assignment(
        shipment_request_id=shipment_request.id,
        carrier_id="car_1",
        selected_by_user_id="user_operator",
    )
    trip = Trip(
        shipment_request_id=shipment_request.id,
        assignment_id=assignment.id,
        carrier_id="car_1",
    )

    assert ShipmentRequestRead.model_validate(shipment_request).id == shipment_request.id
    assert TripOfferRead.model_validate(offer).id == offer.id
    assert AssignmentRead.model_validate(assignment).id == assignment.id
    assert TripRead.model_validate(trip).id == trip.id

