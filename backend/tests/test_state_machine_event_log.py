import pytest

from app.domain.events import EventLogService
from app.domain.state_machine import (
    InvalidStateTransitionError,
    StateTransitionService,
    TransitionContext,
    validate_state_transition,
)


def test_valid_shipment_request_transition() -> None:
    transition = validate_state_transition(
        entity_type="ShipmentRequest",
        from_state="DRAFT",
        event_type="LOAD_INCOMPLETE",
        to_state="INCOMPLETE",
        actor_type="Bot",
    )

    assert transition.entity_type == "ShipmentRequest"
    assert transition.to_state == "INCOMPLETE"


def test_invalid_shipment_request_publish_from_incomplete_fails() -> None:
    with pytest.raises(InvalidStateTransitionError, match="Invalid transition"):
        validate_state_transition(
            entity_type="ShipmentRequest",
            from_state="INCOMPLETE",
            event_type="LOAD_PUBLISHED",
            to_state="PUBLISHED",
            actor_type="System",
        )


def test_operator_can_validate_draft_shipment_created_from_chat() -> None:
    transition = validate_state_transition(
        entity_type="ShipmentRequest",
        from_state="DRAFT",
        event_type="LOAD_VALIDATED",
        to_state="VALIDATED",
        actor_type="Operator",
    )

    assert transition.to_state == "VALIDATED"


def test_assignment_confirmed_requires_operator() -> None:
    with pytest.raises(InvalidStateTransitionError, match="cannot perform"):
        validate_state_transition(
            entity_type="Assignment",
            from_state="PENDING_CONFIRMATION",
            event_type="ASSIGNMENT_CONFIRMED",
            to_state="CONFIRMED",
            actor_type="System",
        )

    transition = validate_state_transition(
        entity_type="Assignment",
        from_state="PENDING_CONFIRMATION",
        event_type="ASSIGNMENT_CONFIRMED",
        to_state="CONFIRMED",
        actor_type="Operator",
    )

    assert transition.to_state == "CONFIRMED"


def test_carrier_short_positive_response_can_be_marked_interested() -> None:
    transition = validate_state_transition(
        entity_type="TripOffer",
        from_state="RECEIVED",
        event_type="OFFER_UPDATED",
        to_state="INTERESTED",
        actor_type="Carrier",
    )

    assert transition.entity_type == "TripOffer"
    assert transition.to_state == "INTERESTED"


def test_ambiguous_carrier_response_needs_clarification() -> None:
    event_log_service = EventLogService()
    service = StateTransitionService(event_log_service)

    event = service.transition(
        entity_type="TripOffer",
        entity_id="off_puede_ser",
        from_state="RECEIVED",
        event_type="MISSING_DATA_DETECTED",
        to_state="NEEDS_CLARIFICATION",
        actor_type="AI Agent",
        summary='carrier replied "puede ser"',
        payload={"raw_response": "puede ser", "reason": "ambiguous carrier availability"},
        idempotency_key="offer-ambiguous-off_puede_ser",
    )

    assert event.event_type == "MISSING_DATA_DETECTED"
    assert event.new_state == "NEEDS_CLARIFICATION"
    assert event.payload["raw_response"] == "puede ser"


def test_ai_agent_cannot_shortlist_offer() -> None:
    with pytest.raises(InvalidStateTransitionError, match="cannot perform"):
        validate_state_transition(
            entity_type="TripOffer",
            from_state="INTERESTED",
            event_type="OFFER_SHORTLISTED",
            to_state="SHORTLISTED",
            actor_type="AI Agent",
        )


def test_trip_created_requires_confirmed_assignment_context() -> None:
    with pytest.raises(InvalidStateTransitionError, match="Assignment.CONFIRMED"):
        validate_state_transition(
            entity_type="Trip",
            from_state=None,
            event_type="TRIP_CREATED",
            to_state="PLANNED",
            actor_type="Operator",
        )

    transition = validate_state_transition(
        entity_type="Trip",
        from_state=None,
        event_type="TRIP_CREATED",
        to_state="PLANNED",
        actor_type="Operator",
        context=TransitionContext(assignment_confirmed=True),
    )

    assert transition.to_state == "PLANNED"


def test_state_transition_service_records_event_log() -> None:
    event_log_service = EventLogService()
    service = StateTransitionService(event_log_service)

    event = service.transition(
        entity_type="Assignment",
        entity_id="asg_1",
        from_state="PENDING_CONFIRMATION",
        event_type="ASSIGNMENT_CONFIRMED",
        to_state="CONFIRMED",
        actor_type="Operator",
        actor_id="user_1",
        summary="operator confirmed assignment",
        idempotency_key="assignment-confirmed-asg_1",
    )

    assert event.event_type == "ASSIGNMENT_CONFIRMED"
    assert event.previous_state == "PENDING_CONFIRMATION"
    assert event.new_state == "CONFIRMED"
    assert event.actor_type == "OPERATOR"
    assert len(event_log_service.events) == 1


def test_event_log_idempotency_returns_existing_event() -> None:
    event_log_service = EventLogService()
    service = StateTransitionService(event_log_service)

    first = service.transition(
        entity_type="ShipmentRequest",
        entity_id="sr_1",
        from_state="VALIDATED",
        event_type="LOAD_PUBLISHED",
        to_state="PUBLISHED",
        actor_type="Operator",
        summary="load published",
        idempotency_key="publish-sr_1",
    )
    second = service.transition(
        entity_type="ShipmentRequest",
        entity_id="sr_1",
        from_state="VALIDATED",
        event_type="LOAD_PUBLISHED",
        to_state="PUBLISHED",
        actor_type="Operator",
        summary="load published duplicate",
        idempotency_key="publish-sr_1",
    )

    assert first is second
    assert len(event_log_service.events) == 1
