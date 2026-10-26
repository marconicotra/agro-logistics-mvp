from dataclasses import dataclass

from app.domain.events import EventLog, EventLogService


class InvalidStateTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    entity_type: str
    from_state: str | None
    event_type: str
    to_state: str
    allowed_actors: frozenset[str]


@dataclass(frozen=True)
class TransitionContext:
    assignment_confirmed: bool = False
    assignment_selected: bool = False
    producer_accepted_offer: bool = False


ENTITY_ALIASES = {
    "LivestockLoad": "ShipmentRequest",
    "ShipmentRequest": "ShipmentRequest",
    "Offer": "TripOffer",
    "TripOffer": "TripOffer",
    "Assignment": "Assignment",
    "Trip": "Trip",
}

ACTOR_ALIASES = {
    "AI Agent": "AI_AGENT",
    "AI_AGENT": "AI_AGENT",
    "Producer": "PRODUCER",
    "PRODUCER": "PRODUCER",
    "Carrier": "CARRIER",
    "CARRIER": "CARRIER",
    "Operator": "OPERATOR",
    "OPERATOR": "OPERATOR",
    "Bot": "BOT",
    "BOT": "BOT",
    "System": "SYSTEM",
    "SYSTEM": "SYSTEM",
}


def _actors(*actors: str) -> frozenset[str]:
    return frozenset(ACTOR_ALIASES[actor] for actor in actors)


VALID_TRANSITIONS: frozenset[Transition] = frozenset(
    [
        # ShipmentRequest / LivestockLoad
        Transition("ShipmentRequest", "DRAFT", "LOAD_INCOMPLETE", "INCOMPLETE", _actors("BOT", "AI_AGENT")),
        Transition("ShipmentRequest", "DRAFT", "LOAD_VALIDATED", "VALIDATED", _actors("OPERATOR")),
        Transition("ShipmentRequest", "DRAFT", "LOAD_SELF_PUBLISHED", "PUBLISHED", _actors("PRODUCER", "SYSTEM")),
        Transition(
            "ShipmentRequest",
            "DRAFT",
            "HUMAN_REVIEW_REQUESTED",
            "PENDING_OPERATOR_REVIEW",
            _actors("BOT", "AI_AGENT", "SYSTEM"),
        ),
        Transition(
            "ShipmentRequest",
            "INCOMPLETE",
            "LOAD_UPDATED",
            "PENDING_OPERATOR_REVIEW",
            _actors("PRODUCER", "BOT", "OPERATOR"),
        ),
        Transition(
            "ShipmentRequest",
            "PENDING_OPERATOR_REVIEW",
            "LOAD_VALIDATED",
            "VALIDATED",
            _actors("OPERATOR"),
        ),
        Transition(
            "ShipmentRequest",
            "PENDING_OPERATOR_REVIEW",
            "LOAD_INCOMPLETE",
            "INCOMPLETE",
            _actors("OPERATOR"),
        ),
        Transition("ShipmentRequest", "VALIDATED", "LOAD_PUBLISHED", "PUBLISHED", _actors("OPERATOR", "SYSTEM")),
        Transition("ShipmentRequest", "PUBLISHED", "OFFER_RECEIVED", "MATCHING", _actors("CARRIER", "SYSTEM")),
        Transition(
            "ShipmentRequest",
            "PUBLISHED",
            "LOAD_MATCHING_STARTED",
            "MATCHING",
            _actors("CARRIER", "SYSTEM"),
        ),
        Transition(
            "ShipmentRequest",
            "PUBLISHED",
            "LOAD_REOPENED",
            "PENDING_OPERATOR_REVIEW",
            _actors("OPERATOR"),
        ),
        Transition(
            "ShipmentRequest",
            "MATCHING",
            "ASSIGNMENT_CONFIRMED",
            "ASSIGNED",
            _actors("OPERATOR", "PRODUCER", "SYSTEM"),
        ),
        Transition(
            "ShipmentRequest",
            "MATCHING",
            "LOAD_REOPENED",
            "PENDING_OPERATOR_REVIEW",
            _actors("OPERATOR"),
        ),
        Transition("ShipmentRequest", "ASSIGNED", "TRIP_COMPLETED", "CLOSED", _actors("OPERATOR", "SYSTEM")),
        Transition("ShipmentRequest", "DRAFT", "LOAD_CANCELLED", "CANCELLED", _actors("PRODUCER", "OPERATOR")),
        Transition("ShipmentRequest", "INCOMPLETE", "LOAD_CANCELLED", "CANCELLED", _actors("PRODUCER", "OPERATOR")),
        Transition(
            "ShipmentRequest",
            "PENDING_OPERATOR_REVIEW",
            "LOAD_CANCELLED",
            "CANCELLED",
            _actors("PRODUCER", "OPERATOR"),
        ),
        Transition("ShipmentRequest", "VALIDATED", "LOAD_CANCELLED", "CANCELLED", _actors("PRODUCER", "OPERATOR")),
        Transition("ShipmentRequest", "PUBLISHED", "LOAD_CANCELLED", "CANCELLED", _actors("PRODUCER", "OPERATOR")),
        Transition("ShipmentRequest", "MATCHING", "LOAD_CANCELLED", "CANCELLED", _actors("PRODUCER", "OPERATOR")),
        Transition("ShipmentRequest", "ASSIGNED", "LOAD_CANCELLED", "CANCELLED", _actors("OPERATOR")),
        # TripOffer / Offer
        Transition(
            "TripOffer",
            "RECEIVED",
            "MISSING_DATA_DETECTED",
            "NEEDS_CLARIFICATION",
            _actors("AI_AGENT", "OPERATOR"),
        ),
        Transition("TripOffer", "RECEIVED", "OFFER_UPDATED", "INTERESTED", _actors("CARRIER", "OPERATOR")),
        Transition("TripOffer", "RECEIVED", "OFFER_UPDATED", "NOT_AVAILABLE", _actors("CARRIER", "OPERATOR")),
        Transition("TripOffer", "RECEIVED", "OFFER_UPDATED", "PRICE_PROVIDED", _actors("CARRIER", "OPERATOR")),
        Transition(
            "TripOffer",
            "NEEDS_CLARIFICATION",
            "OFFER_UPDATED",
            "INTERESTED",
            _actors("CARRIER", "OPERATOR"),
        ),
        Transition(
            "TripOffer",
            "NEEDS_CLARIFICATION",
            "OFFER_UPDATED",
            "PRICE_PROVIDED",
            _actors("CARRIER", "OPERATOR"),
        ),
        Transition(
            "TripOffer",
            "NEEDS_CLARIFICATION",
            "OFFER_REJECTED",
            "REJECTED",
            _actors("OPERATOR"),
        ),
        Transition("TripOffer", "INTERESTED", "OFFER_UPDATED", "PRICE_PROVIDED", _actors("CARRIER", "OPERATOR")),
        Transition("TripOffer", "INTERESTED", "OFFER_SHORTLISTED", "SHORTLISTED", _actors("OPERATOR")),
        Transition("TripOffer", "PRICE_PROVIDED", "OFFER_SHORTLISTED", "SHORTLISTED", _actors("OPERATOR")),
        Transition("TripOffer", "INTERESTED", "OFFER_REJECTED", "REJECTED", _actors("OPERATOR")),
        Transition("TripOffer", "PRICE_PROVIDED", "OFFER_REJECTED", "REJECTED", _actors("OPERATOR")),
        Transition("TripOffer", "SHORTLISTED", "OFFER_REJECTED", "REJECTED", _actors("OPERATOR")),
        Transition("TripOffer", "RECEIVED", "OFFER_EXPIRED", "EXPIRED", _actors("SYSTEM", "OPERATOR")),
        Transition("TripOffer", "NEEDS_CLARIFICATION", "OFFER_EXPIRED", "EXPIRED", _actors("SYSTEM", "OPERATOR")),
        Transition("TripOffer", "INTERESTED", "OFFER_EXPIRED", "EXPIRED", _actors("SYSTEM", "OPERATOR")),
        Transition("TripOffer", "PRICE_PROVIDED", "OFFER_EXPIRED", "EXPIRED", _actors("SYSTEM", "OPERATOR")),
        Transition("TripOffer", "INTERESTED", "OFFER_CANCELLED", "CANCELLED", _actors("CARRIER", "OPERATOR")),
        Transition("TripOffer", "PRICE_PROVIDED", "OFFER_CANCELLED", "CANCELLED", _actors("CARRIER", "OPERATOR")),
        Transition("TripOffer", "SHORTLISTED", "OFFER_CANCELLED", "CANCELLED", _actors("CARRIER", "OPERATOR")),
        # Assignment
        Transition("Assignment", "PROPOSED", "MATCH_PROPOSED", "PROPOSED", _actors("AI_AGENT", "SYSTEM", "OPERATOR")),
        Transition("Assignment", "PROPOSED", "ASSIGNMENT_CREATED", "PENDING_CONFIRMATION", _actors("OPERATOR")),
        Transition("Assignment", "PROPOSED", "ASSIGNMENT_CANCELLED", "CANCELLED", _actors("OPERATOR")),
        Transition("Assignment", "PROPOSED", "OFFER_REJECTED", "REJECTED", _actors("OPERATOR")),
        Transition(
            "Assignment",
            "PENDING_CONFIRMATION",
            "ASSIGNMENT_CONFIRMED",
            "CONFIRMED",
            _actors("OPERATOR"),
        ),
        Transition(
            "Assignment",
            "PENDING_CONFIRMATION",
            "ASSIGNMENT_CANCELLED",
            "CANCELLED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition("Assignment", "PENDING_CONFIRMATION", "OFFER_REJECTED", "REJECTED", _actors("OPERATOR")),
        Transition(
            "Assignment",
            "CONFIRMED",
            "ASSIGNMENT_CANCELLED",
            "CANCELLED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition("Assignment", "CANCELLED", "ASSIGNMENT_REPLACED", "REPLACED", _actors("OPERATOR")),
        # Trip
        Transition("Trip", None, "TRIP_CREATED", "PLANNED", _actors("OPERATOR", "SYSTEM", "PRODUCER")),
        Transition("Trip", "PLANNED", "TRIP_REMINDER_SENT", "REMINDER_SENT", _actors("SYSTEM", "BOT")),
        Transition("Trip", "PLANNED", "TRIP_STARTED", "LOADING_PENDING", _actors("OPERATOR", "CARRIER")),
        Transition("Trip", "REMINDER_SENT", "TRIP_STARTED", "LOADING_PENDING", _actors("OPERATOR", "CARRIER")),
        Transition(
            "Trip",
            "LOADING_PENDING",
            "TRIP_LOADING",
            "LOADING",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition("Trip", "LOADING", "TRIP_IN_TRANSIT", "IN_TRANSIT", _actors("OPERATOR", "CARRIER")),
        Transition(
            "Trip",
            "IN_TRANSIT",
            "TRIP_DELIVERED",
            "DELIVERED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition("Trip", "DELIVERED", "TRIP_COMPLETED", "COMPLETED", _actors("OPERATOR")),
        Transition(
            "Trip",
            "PLANNED",
            "TRIP_INCIDENT_REPORTED",
            "INCIDENT_REPORTED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition(
            "Trip",
            "REMINDER_SENT",
            "TRIP_INCIDENT_REPORTED",
            "INCIDENT_REPORTED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition(
            "Trip",
            "LOADING_PENDING",
            "TRIP_INCIDENT_REPORTED",
            "INCIDENT_REPORTED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition(
            "Trip",
            "LOADING",
            "TRIP_INCIDENT_REPORTED",
            "INCIDENT_REPORTED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition(
            "Trip",
            "IN_TRANSIT",
            "TRIP_INCIDENT_REPORTED",
            "INCIDENT_REPORTED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition("Trip", "INCIDENT_REPORTED", "TRIP_UPDATED", "LOADING_PENDING", _actors("OPERATOR")),
        Transition("Trip", "INCIDENT_REPORTED", "TRIP_UPDATED", "LOADING", _actors("OPERATOR")),
        Transition("Trip", "INCIDENT_REPORTED", "TRIP_UPDATED", "IN_TRANSIT", _actors("OPERATOR")),
        Transition("Trip", "INCIDENT_REPORTED", "TRIP_COMPLETED", "COMPLETED", _actors("OPERATOR")),
        Transition("Trip", "PLANNED", "TRIP_CANCELLED", "CANCELLED", _actors("OPERATOR", "CARRIER", "PRODUCER")),
        Transition("Trip", "REMINDER_SENT", "TRIP_CANCELLED", "CANCELLED", _actors("OPERATOR", "CARRIER", "PRODUCER")),
        Transition(
            "Trip",
            "LOADING_PENDING",
            "TRIP_CANCELLED",
            "CANCELLED",
            _actors("OPERATOR", "CARRIER", "PRODUCER"),
        ),
        Transition("Trip", "LOADING", "TRIP_CANCELLED", "CANCELLED", _actors("OPERATOR", "CARRIER", "PRODUCER")),
        Transition("Trip", "IN_TRANSIT", "TRIP_CANCELLED", "CANCELLED", _actors("OPERATOR")),
        Transition("Trip", "INCIDENT_REPORTED", "TRIP_CANCELLED", "CANCELLED", _actors("OPERATOR")),
    ]
)


def normalize_entity_type(entity_type: str) -> str:
    try:
        return ENTITY_ALIASES[entity_type]
    except KeyError as exc:
        raise InvalidStateTransitionError(f"Unknown entity type: {entity_type}") from exc


def normalize_actor_type(actor_type: str) -> str:
    try:
        return ACTOR_ALIASES[actor_type]
    except KeyError as exc:
        raise InvalidStateTransitionError(f"Unknown actor type: {actor_type}") from exc


def validate_state_transition(
    *,
    entity_type: str,
    from_state: str | None,
    event_type: str,
    to_state: str,
    actor_type: str,
    context: TransitionContext | None = None,
) -> Transition:
    normalized_entity = normalize_entity_type(entity_type)
    normalized_actor = normalize_actor_type(actor_type)
    context = context or TransitionContext()

    if (
        normalized_entity == "Trip"
        and from_state is None
        and event_type == "TRIP_CREATED"
        and not (context.assignment_confirmed or context.assignment_selected or context.producer_accepted_offer)
    ):
        raise InvalidStateTransitionError(
            "Trip cannot be created without Assignment.CONFIRMED, an operator-selected assignment, or producer acceptance"
        )

    for transition in VALID_TRANSITIONS:
        if (
            transition.entity_type == normalized_entity
            and transition.from_state == from_state
            and transition.event_type == event_type
            and transition.to_state == to_state
        ):
            if normalized_actor not in transition.allowed_actors:
                raise InvalidStateTransitionError(
                    f"Actor {actor_type} cannot perform {event_type} on {entity_type}"
                )
            return transition

    raise InvalidStateTransitionError(
        f"Invalid transition for {entity_type}: {from_state} --{event_type}--> {to_state}"
    )


class StateTransitionService:
    def __init__(self, event_log_service: EventLogService) -> None:
        self._event_log_service = event_log_service

    def transition(
        self,
        *,
        entity_type: str,
        entity_id: str,
        from_state: str | None,
        event_type: str,
        to_state: str,
        actor_type: str,
        summary: str,
        context: TransitionContext | None = None,
        actor_id: str | None = None,
        related_entity_ids: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
        source: str = "system",
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> EventLog:
        validate_state_transition(
            entity_type=entity_type,
            from_state=from_state,
            event_type=event_type,
            to_state=to_state,
            actor_type=actor_type,
            context=context,
        )
        return self._event_log_service.record(
            event_type=event_type,
            actor_type=normalize_actor_type(actor_type),
            actor_id=actor_id,
            entity_type=normalize_entity_type(entity_type),
            entity_id=entity_id,
            related_entity_ids=related_entity_ids,
            previous_state=from_state,
            new_state=to_state,
            summary=summary,
            payload=payload,
            source=source,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
