from functools import wraps
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Callable

from app.application.chat_shipment_parser import parse_chat_shipment_text
from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.domain.events import EventLog, EventLogService, current_test_run_id
from app.domain.models import (
    Assignment,
    Carrier,
    ConversationSession,
    Location,
    Message,
    ShipmentRequest,
    Trip,
    TripOffer,
    utc_now,
)
from app.domain.state_machine import StateTransitionService, TransitionContext
from app.application.notifications import NotificationResult, NotificationService, ProducerNotificationResult
from app.infrastructure.repositories.memory import InMemoryRepository


class AdminOpsError(ValueError):
    pass


@dataclass(frozen=True)
class AssignmentConfirmationResult:
    assignment: Assignment
    trip: Trip
    events: tuple[EventLog, ...]


@dataclass(frozen=True)
class ShipmentPublishResult:
    shipment: ShipmentRequest
    events: tuple[EventLog, ...]
    notification_results: tuple[NotificationResult, ...] = ()


@dataclass(frozen=True)
class ShipmentDraftFromChatResult:
    shipment: ShipmentRequest
    event: EventLog


@dataclass(frozen=True)
class OfferSelectionResult:
    assignment: Assignment
    trip: Trip
    events: tuple[EventLog, ...]


@dataclass(frozen=True)
class ProducerOfferAcceptanceResult:
    assignment: Assignment
    trip: Trip
    shipment: ShipmentRequest
    events: tuple[EventLog, ...]
    already_active_assignment: bool = False
    carrier_notification: NotificationResult | None = None
    producer_notification: ProducerNotificationResult | None = None


@dataclass(frozen=True)
class ManualInterestResult:
    shipment: ShipmentRequest
    trip_offer: TripOffer
    events: tuple[EventLog, ...]
    carrier_notification: NotificationResult | None = None
    producer_notification: ProducerNotificationResult | None = None


@dataclass(frozen=True)
class ManualAssignmentResult:
    shipment: ShipmentRequest
    trip_offer: TripOffer
    assignment: Assignment
    trip: Trip
    events: tuple[EventLog, ...]
    carrier_notification: NotificationResult | None = None
    producer_notification: ProducerNotificationResult | None = None


@dataclass(frozen=True)
class TripStatusUpdateResult:
    shipment: ShipmentRequest | None
    trip: Trip
    events: tuple[EventLog, ...]
    carrier_notification: NotificationResult | None = None
    producer_notification: ProducerNotificationResult | None = None


@dataclass(frozen=True)
class ShipmentOfferSummary:
    trip_offer_id: str
    carrier_id: str
    response_type: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ShipmentWithOffers:
    shipment_id: str
    status: str
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    offers: tuple[ShipmentOfferSummary, ...]


@dataclass(frozen=True)
class ChatDraftShipmentSummary:
    shipment_id: str
    status: str
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    operational_notes: str | None
    created_at: datetime
    source_phone_number: str | None


@dataclass(frozen=True)
class ProducerShipmentSummary:
    shipment_id: str
    status: str
    origin: str | None
    destination: str | None
    date_window_start: datetime | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    operational_notes: str | None
    created_at: datetime
    interested_offers_count: int


@dataclass(frozen=True)
class ProducerInterestedOfferSummary:
    index: int
    shipment_id: str
    shipment_status: str
    trip_offer_id: str
    carrier_id: str
    response_type: str
    offer_status: str
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    created_at: datetime


@dataclass(frozen=True)
class JourneyStatusSummary:
    shipment_id: str
    shipment_status: str
    trip_id: str | None
    trip_status: str | None
    assignment_id: str | None
    assignment_status: str | None
    origin: str | None
    destination: str | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    operational_notes: str | None
    interested_offers_count: int
    counterparty_id: str | None
    counterparty_name: str | None
    counterparty_phone: str | None
    planned_start_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ProducerDashboardSummary:
    phone_number: str
    total_shipments: int
    active_shipments: int
    active_trips: int
    completed_trips: int
    pending_interested_offers: int
    current_operations: tuple[JourneyStatusSummary, ...]
    past_operations: tuple[JourneyStatusSummary, ...]


@dataclass(frozen=True)
class CarrierDashboardSummary:
    carrier_id: str
    carrier_name: str
    carrier_phone: str | None
    total_offers: int
    open_offers: int
    active_trips: int
    completed_trips: int
    cancelled_trips: int
    current_operations: tuple[JourneyStatusSummary, ...]
    past_operations: tuple[JourneyStatusSummary, ...]


@dataclass(frozen=True)
class PendingAssignmentSummary:
    assignment_id: str
    assignment_status: str
    shipment_id: str
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    carrier_id: str
    trip_offer_id: str | None
    trip_id: str | None
    trip_status: str | None
    created_at: datetime


@dataclass(frozen=True)
class OperationSummary:
    shipment_id: str
    shipment_status: str
    assignment_id: str
    assignment_status: str
    trip_id: str | None
    trip_status: str | None
    carrier_id: str
    trip_offer_id: str | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    operational_notes: str | None
    created_at: datetime


def routing_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        routing = getattr(self, "_routing", None)
        if routing is None:
            return method(self, *args, **kwargs)
        shipment_id = kwargs.get("shipment_request_id")
        if shipment_id is None and kwargs.get("assignment_id"):
            assignment = self._assignments.get(kwargs["assignment_id"])
            shipment_id = assignment.shipment_request_id if assignment else kwargs["assignment_id"]
        with routing.store.lock("shipment:" + str(shipment_id)):
            return method(self, *args, **kwargs)
    return wrapped


class AdminOpsService:
    """Admin operation boundary.

    This in-memory implementation is dev-only. Critical multi-entity actions
    are kept in one service method so the same boundary can become one DB
    transaction when repository persistence is introduced.
    """

    CONFIRMABLE_SHIPMENT_STATES = {"MATCHING"}
    ACTIVE_ASSIGNMENT_STATES = {"PROPOSED", "PENDING_CONFIRMATION", "CONFIRMED"}
    ACTIVE_ASSIGNMENT_STATUS_PRIORITY = {
        "CONFIRMED": 3,
        "PENDING_CONFIRMATION": 2,
        "PROPOSED": 1,
    }
    ACTIVE_TRIP_STATES = {"PLANNED", "REMINDER_SENT", "LOADING_PENDING", "LOADING", "IN_TRANSIT", "DELIVERED"}
    FINAL_TRIP_STATES = {"COMPLETED", "CANCELLED"}

    def __init__(
        self,
        *,
        shipment_requests: InMemoryRepository[ShipmentRequest],
        trip_offers: InMemoryRepository[TripOffer],
        assignments: InMemoryRepository[Assignment],
        trips: InMemoryRepository[Trip],
        carriers: InMemoryRepository[Carrier] | None = None,
        locations: InMemoryRepository[Location] | None = None,
        conversation_sessions: InMemoryRepository[ConversationSession],
        messages: InMemoryRepository[Message],
        event_log: EventLogService,
        notification_service: NotificationService | None = None,
        enable_test_role_switching: bool = False,
        trip_readiness_guard: Callable[[str], None] | None = None,
    ) -> None:
        self._shipment_requests = shipment_requests
        self._trip_offers = trip_offers
        self._assignments = assignments
        self._trips = trips
        self._carriers = carriers
        self._locations = locations
        self._conversation_sessions = conversation_sessions
        self._messages = messages
        self._event_log = event_log
        self._notification_service = notification_service
        self._enable_test_role_switching = enable_test_role_switching
        self._trip_readiness_guard = trip_readiness_guard
        self._routing = None
        self._transitions = StateTransitionService(event_log)

    def list_pending_shipments(self) -> list[ShipmentRequest]:
        return [
            shipment
            for shipment in self._shipment_requests.list()
            if shipment.status in {"PENDING_OPERATOR_REVIEW", "VALIDATED", "PUBLISHED", "MATCHING"}
        ]

    def list_incomplete_shipments(self) -> list[ShipmentRequest]:
        return [
            shipment
            for shipment in self._shipment_requests.list()
            if shipment.status == "INCOMPLETE" or shipment.missing_critical_fields
        ]

    def list_draft_shipments(self, *, limit: int = 20) -> list[ChatDraftShipmentSummary]:
        normalized_limit = max(1, min(limit, 50))
        source_phone_by_shipment_id = self._chat_draft_source_phones()
        shipments = [
            shipment
            for shipment in self._shipment_requests.list()
            if shipment.status == "DRAFT"
        ]
        shipments.sort(key=lambda shipment: shipment.created_at, reverse=True)
        return [
            ChatDraftShipmentSummary(
                shipment_id=shipment.id,
                status=shipment.status,
                cargo_category=shipment.cargo_category,
                cargo_type=shipment.cargo_type,
                quantity_unit=shipment.quantity_unit,
                livestock_type=shipment.livestock_type,
                quantity_estimate=shipment.quantity_estimate,
                operational_notes=shipment.operational_notes,
                created_at=shipment.created_at,
                source_phone_number=source_phone_by_shipment_id.get(shipment.id),
            )
            for shipment in shipments[:normalized_limit]
        ]

    def list_shipments_with_offers(self) -> list[ShipmentWithOffers]:
        offers_by_shipment: dict[str, list[TripOffer]] = {}
        for offer in self._trip_offers.list():
            offers_by_shipment.setdefault(offer.shipment_request_id, []).append(offer)
        active_assignment_shipment_ids = self._active_assignment_shipment_ids()

        shipments = [
            shipment
            for shipment in self._shipment_requests.list()
            if shipment.status in {"PUBLISHED", "MATCHING"}
        ]
        shipments.sort(key=lambda shipment: shipment.created_at, reverse=True)

        return [
            ShipmentWithOffers(
                shipment_id=shipment.id,
                status=shipment.status,
                cargo_category=shipment.cargo_category,
                cargo_type=shipment.cargo_type,
                quantity_unit=shipment.quantity_unit,
                livestock_type=shipment.livestock_type,
                quantity_estimate=shipment.quantity_estimate,
                offers=tuple(
                    ShipmentOfferSummary(
                        trip_offer_id=offer.id,
                        carrier_id=offer.carrier_id,
                        response_type=offer.response_type,
                        status=offer.status,
                        created_at=offer.created_at,
                    )
                    for offer in sorted(
                        [] if shipment.id in active_assignment_shipment_ids else offers_by_shipment.get(shipment.id, []),
                        key=lambda item: item.created_at,
                        reverse=True,
                    )
                ),
            )
            for shipment in shipments
        ]

    def list_pending_assignments(self, *, limit: int = 20) -> list[PendingAssignmentSummary]:
        normalized_limit = max(1, min(limit, 50))
        assignments = [
            assignment
            for assignment in self._canonical_active_assignments()
            if assignment.status in {"PROPOSED", "PENDING_CONFIRMATION"}
        ]
        assignments.sort(key=lambda assignment: assignment.created_at, reverse=True)

        summaries: list[PendingAssignmentSummary] = []
        for assignment in assignments[:normalized_limit]:
            shipment = self._shipment_requests.get(assignment.shipment_request_id)
            if shipment is None:
                continue
            trip = self._find_trip_by_assignment(assignment.id)
            summaries.append(
                PendingAssignmentSummary(
                    assignment_id=assignment.id,
                    assignment_status=assignment.status,
                    shipment_id=shipment.id,
                    cargo_category=shipment.cargo_category,
                    cargo_type=shipment.cargo_type,
                    quantity_unit=shipment.quantity_unit,
                    livestock_type=shipment.livestock_type,
                    quantity_estimate=shipment.quantity_estimate,
                    carrier_id=assignment.carrier_id,
                    trip_offer_id=assignment.trip_offer_id,
                    trip_id=trip.id if trip else None,
                    trip_status=trip.status if trip else None,
                    created_at=assignment.created_at,
                )
            )
        return summaries

    def list_active_assignments(self, *, limit: int = 20) -> list[OperationSummary]:
        normalized_limit = max(1, min(limit, 50))
        assignments = self._canonical_active_assignments()
        assignments.sort(key=lambda assignment: assignment.created_at, reverse=True)
        return [
            summary
            for assignment in assignments[:normalized_limit]
            if (summary := self._operation_summary_for_assignment(assignment)) is not None
        ]

    def lookup_operation(self, entity_id: str) -> OperationSummary:
        assignment: Assignment | None = None
        if entity_id.startswith("trip_"):
            trip = self._trips.get(entity_id)
            if trip is not None:
                assignment = self._find_active_assignment_by_shipment(trip.shipment_request_id)
        elif entity_id.startswith("asg_"):
            requested_assignment = self._assignments.get(entity_id)
            if requested_assignment is not None:
                assignment = self._find_active_assignment_by_shipment(requested_assignment.shipment_request_id)
        elif entity_id.startswith("sr_"):
            assignment = self._find_active_assignment_by_shipment(entity_id)
        else:
            requested_assignment = self._assignments.get(entity_id)
            if requested_assignment is not None:
                assignment = self._find_active_assignment_by_shipment(requested_assignment.shipment_request_id)
            if assignment is None:
                trip = self._trips.get(entity_id)
                if trip is not None:
                    assignment = self._find_active_assignment_by_shipment(trip.shipment_request_id)
            if assignment is None:
                assignment = self._find_active_assignment_by_shipment(entity_id)

        if assignment is None or assignment.status not in self.ACTIVE_ASSIGNMENT_STATES:
            raise KeyError(entity_id)
        summary = self._operation_summary_for_assignment(assignment)
        if summary is None:
            raise KeyError(entity_id)
        return summary

    def list_recent_chat_drafts(
        self,
        *,
        phone_number: str | None = None,
        limit: int = 5,
    ) -> list[ChatDraftShipmentSummary]:
        normalized_limit = max(1, min(limit, 20))
        phone_keys = self._phone_lookup_keys(phone_number)
        filtered = self._recent_chat_draft_summaries(limit=normalized_limit, phone_keys=phone_keys)
        if filtered or not phone_keys:
            return filtered
        return self._recent_chat_draft_summaries(limit=normalized_limit, phone_keys=set())

    def list_producer_shipments(
        self,
        *,
        phone_number: str,
        limit: int = 10,
    ) -> list[ProducerShipmentSummary]:
        normalized_phone = self._normalize_required_phone_number(phone_number)
        normalized_limit = max(1, min(limit, 50))
        test_run_id = self._producer_test_run_id(normalized_phone)
        shipments = [
            shipment
            for shipment in self._shipment_requests.list()
            if self._producer_owns_shipment(shipment, normalized_phone)
            and shipment.test_run_id == test_run_id
        ]
        shipments.sort(key=lambda shipment: shipment.created_at, reverse=True)
        interested_counts = self._interested_offer_counts_by_shipment()
        return [
            ProducerShipmentSummary(
                shipment_id=shipment.id,
                status=shipment.status,
                origin=self._location_label(shipment.origin_location_id),
                destination=self._location_label(shipment.destination_location_id),
                date_window_start=shipment.date_window_start,
                cargo_category=shipment.cargo_category,
                cargo_type=shipment.cargo_type,
                quantity_unit=shipment.quantity_unit,
                livestock_type=shipment.livestock_type,
                quantity_estimate=shipment.quantity_estimate,
                operational_notes=shipment.operational_notes,
                created_at=shipment.created_at,
                interested_offers_count=interested_counts.get(shipment.id, 0),
            )
            for shipment in shipments[:normalized_limit]
        ]

    def list_producer_interested_offers(
        self,
        *,
        phone_number: str,
        limit: int = 10,
        shipment_request_id: str | None = None,
    ) -> list[ProducerInterestedOfferSummary]:
        normalized_phone = self._normalize_required_phone_number(phone_number)
        normalized_limit = max(1, min(limit, 50))
        test_run_id = self._producer_test_run_id(normalized_phone)
        producer_shipments = {
            shipment.id: shipment
            for shipment in self._shipment_requests.list()
            if self._producer_owns_shipment(shipment, normalized_phone)
            and shipment.test_run_id == test_run_id
            and shipment.status == "MATCHING"
            and self._find_active_assignment_by_shipment(shipment.id) is None
            and (shipment_request_id is None or shipment.id == shipment_request_id)
        }
        rows: list[ProducerInterestedOfferSummary] = []
        offers = [
            offer
            for offer in self._trip_offers.list()
            if offer.response_type == "INTERESTED"
            and offer.shipment_request_id in producer_shipments
            and offer.test_run_id == test_run_id
        ]
        offers.sort(key=lambda offer: offer.created_at, reverse=True)
        for offer in offers[:normalized_limit]:
            shipment = producer_shipments[offer.shipment_request_id]
            rows.append(
                ProducerInterestedOfferSummary(
                    index=len(rows) + 1,
                    shipment_id=shipment.id,
                    shipment_status=shipment.status,
                    trip_offer_id=offer.id,
                    carrier_id=offer.carrier_id,
                    response_type=offer.response_type,
                    offer_status=offer.status,
                    cargo_category=shipment.cargo_category,
                    cargo_type=shipment.cargo_type,
                    quantity_unit=shipment.quantity_unit,
                    livestock_type=shipment.livestock_type,
                    quantity_estimate=shipment.quantity_estimate,
                    created_at=offer.created_at,
                )
            )
        return rows

    def get_producer_dashboard(
        self,
        *,
        phone_number: str,
        limit: int = 12,
    ) -> ProducerDashboardSummary:
        normalized_phone = self._normalize_required_phone_number(phone_number)
        normalized_limit = max(1, min(limit, 24))
        test_run_id = self._producer_test_run_id(normalized_phone)
        shipments = [
            shipment
            for shipment in self._shipment_requests.list()
            if self._producer_owns_shipment(shipment, normalized_phone)
            and shipment.test_run_id == test_run_id
        ]
        shipments.sort(key=lambda shipment: shipment.created_at, reverse=True)
        interested_counts = self._interested_offer_counts_by_shipment()
        current_rows: list[JourneyStatusSummary] = []
        past_rows: list[JourneyStatusSummary] = []
        active_trips = 0
        completed_trips = 0
        pending_interested_offers = 0

        for shipment in shipments:
            assignment = self._find_active_assignment_by_shipment(shipment.id)
            trip = self._find_trip_by_assignment(assignment.id) if assignment else None
            if trip and trip.status in self.ACTIVE_TRIP_STATES:
                active_trips += 1
            if trip and trip.status == "COMPLETED":
                completed_trips += 1
            if shipment.status == "MATCHING" and assignment is None:
                pending_interested_offers += interested_counts.get(shipment.id, 0)
            row = self._journey_summary(
                shipment=shipment,
                assignment=assignment,
                trip=trip,
                interested_offers_count=interested_counts.get(shipment.id, 0),
            )
            if trip and trip.status in self.FINAL_TRIP_STATES or shipment.status in {"CLOSED", "CANCELLED"}:
                past_rows.append(row)
            else:
                current_rows.append(row)

        return ProducerDashboardSummary(
            phone_number=normalized_phone,
            total_shipments=len(shipments),
            active_shipments=sum(1 for shipment in shipments if shipment.status not in {"CLOSED", "CANCELLED"}),
            active_trips=active_trips,
            completed_trips=completed_trips,
            pending_interested_offers=pending_interested_offers,
            current_operations=tuple(current_rows[:normalized_limit]),
            past_operations=tuple(past_rows[:normalized_limit]),
        )

    def get_carrier_dashboard(
        self,
        *,
        carrier_id: str,
        limit: int = 12,
    ) -> CarrierDashboardSummary:
        carrier = self._require_carrier(carrier_id)
        normalized_limit = max(1, min(limit, 24))
        trips = [trip for trip in self._trips.list() if trip.carrier_id == carrier_id]
        trips.sort(key=lambda trip: trip.updated_at, reverse=True)
        offers = [offer for offer in self._trip_offers.list() if offer.carrier_id == carrier_id]
        interested_counts = self._interested_offer_counts_by_shipment()
        current_rows: list[JourneyStatusSummary] = []
        past_rows: list[JourneyStatusSummary] = []

        for trip in trips:
            shipment = self._shipment_requests.get(trip.shipment_request_id)
            if shipment is None:
                continue
            assignment = self._assignments.get(trip.assignment_id)
            row = self._journey_summary(
                shipment=shipment,
                assignment=assignment,
                trip=trip,
                interested_offers_count=interested_counts.get(shipment.id, 0),
                counterparty_name=shipment.producer_phone_number,
                counterparty_phone=shipment.producer_phone_number,
            )
            if trip.status in self.FINAL_TRIP_STATES:
                past_rows.append(row)
            else:
                current_rows.append(row)

        return CarrierDashboardSummary(
            carrier_id=carrier.id,
            carrier_name=carrier.name,
            carrier_phone=carrier.normalized_phone_number or carrier.contact_phone,
            total_offers=len(offers),
            open_offers=sum(1 for offer in offers if offer.status not in {"REJECTED", "CANCELLED", "EXPIRED"}),
            active_trips=sum(1 for trip in trips if trip.status in self.ACTIVE_TRIP_STATES),
            completed_trips=sum(1 for trip in trips if trip.status == "COMPLETED"),
            cancelled_trips=sum(1 for trip in trips if trip.status == "CANCELLED"),
            current_operations=tuple(current_rows[:normalized_limit]),
            past_operations=tuple(past_rows[:normalized_limit]),
        )

    def accept_offer_by_producer(
        self,
        *,
        shipment_request_id: str,
        trip_offer_id: str,
        producer_phone_number: str,
        idempotency_key: str | None = None,
    ) -> ProducerOfferAcceptanceResult:
        normalized_phone = self._normalize_required_phone_number(producer_phone_number)
        test_run_id = self._producer_test_run_id(normalized_phone)
        token = current_test_run_id.set(test_run_id)
        try:
            scoped_idempotency_key = None
            if idempotency_key:
                scope = f"qa:{test_run_id}:" if test_run_id else "producer:"
                scoped_idempotency_key = f"{scope}{sha256(idempotency_key.encode()).hexdigest()[:32]}"
            return self._accept_offer_by_producer(
                shipment_request_id=shipment_request_id,
                trip_offer_id=trip_offer_id,
                producer_phone_number=normalized_phone,
                idempotency_key=scoped_idempotency_key,
                test_run_id=test_run_id,
            )
        finally:
            current_test_run_id.reset(token)

    @routing_locked
    def _accept_offer_by_producer(
        self,
        *,
        shipment_request_id: str,
        trip_offer_id: str,
        producer_phone_number: str,
        idempotency_key: str | None,
        test_run_id: str | None,
    ) -> ProducerOfferAcceptanceResult:
        if idempotency_key and self._has_event(idempotency_key):
            existing = self._producer_offer_acceptance_result_for_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        normalized_phone = self._normalize_required_phone_number(producer_phone_number)
        if self._producer_test_run_id(normalized_phone) != test_run_id:
            raise AdminOpsError("Producer test scenario changed; retry in the active scenario")
        shipment = self._require_shipment(shipment_request_id)
        offer = self._require_offer(trip_offer_id)
        if not self._producer_owns_shipment(shipment, normalized_phone):
            raise AdminOpsError("Shipment request does not belong to producer phone number")
        if shipment.test_run_id != test_run_id or offer.test_run_id != test_run_id:
            raise AdminOpsError("Offer is outside the producer's active test scenario")
        if offer.shipment_request_id != shipment.id:
            raise AdminOpsError("Trip offer does not belong to shipment request")
        if offer.response_type != "INTERESTED":
            raise AdminOpsError("Only INTERESTED trip offers can be accepted")

        active_assignment = self._find_active_assignment_by_shipment(shipment.id)
        if active_assignment is not None:
            trip = self._find_trip_by_assignment(active_assignment.id)
            if trip is None:
                trip = self._create_planned_trip_from_assignment(
                    assignment=active_assignment,
                    operator_user_id=f"producer:{normalized_phone}",
                    idempotency_key=idempotency_key,
                )
            return ProducerOfferAcceptanceResult(
                assignment=active_assignment,
                trip=trip,
                shipment=shipment,
                events=(),
                already_active_assignment=True,
            )
        if shipment.status != "MATCHING":
            raise AdminOpsError(
                f"Shipment request must be in MATCHING status to accept offer; got {shipment.status}"
            )

        if self._routing is not None:
            try:
                self._routing.commit_availability(shipment, offer.carrier_id)
            except ValueError as exc:
                raise AdminOpsError(str(exc)) from exc
        producer_actor_id = f"producer:{normalized_phone}"
        assignment = self._assignments.add(
            Assignment(
                shipment_request_id=shipment.id,
                test_run_id=shipment.test_run_id,
                trip_offer_id=offer.id,
                carrier_id=offer.carrier_id,
                selected_by_user_id=producer_actor_id,
                status="CONFIRMED",
                confirmed_by_user_id=producer_actor_id,
                confirmed_at=utc_now(),
                confirmation_notes="Aceptado por productor via WhatsApp",
            )
        )
        related_entity_ids = self._assignment_related_ids(assignment)
        events: list[EventLog] = []
        events.append(
            self._event_log.record(
                event_type="PRODUCER_OFFER_ACCEPTED",
                actor_type="PRODUCER",
                actor_id=producer_actor_id,
                entity_type="TripOffer",
                entity_id=offer.id,
                summary="Productor acepto oferta de transportista",
                related_entity_ids=related_entity_ids,
                payload={
                    "shipment_request_id": shipment.id,
                    "trip_offer_id": offer.id,
                    "carrier_id": offer.carrier_id,
                    "producer_phone_number": self._mask_phone(normalized_phone),
                },
                source="whatsapp",
                idempotency_key=idempotency_key,
            )
        )
        events.append(
            self._event_log.record(
                event_type="ASSIGNMENT_CREATED",
                actor_type="PRODUCER",
                actor_id=producer_actor_id,
                entity_type="Assignment",
                entity_id=assignment.id,
                summary="Assignment confirmado por aceptacion del productor",
                related_entity_ids=related_entity_ids,
                previous_state=None,
                new_state=assignment.status,
                payload={"trip_offer_id": offer.id, "carrier_id": offer.carrier_id},
                source="whatsapp",
                idempotency_key=f"{idempotency_key}:assignment_created" if idempotency_key else None,
            )
        )

        trip = Trip(
            shipment_request_id=shipment.id,
            test_run_id=shipment.test_run_id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            vehicle_id=assignment.vehicle_id,
            status="PLANNED",
        )
        trip_event = self._transitions.transition(
            entity_type="Trip",
            entity_id=trip.id,
            from_state=None,
            event_type="TRIP_CREATED",
            to_state="PLANNED",
            actor_type="Producer",
            actor_id=producer_actor_id,
            summary="Viaje planificado por match confirmado en marketplace",
            context=TransitionContext(producer_accepted_offer=True),
            related_entity_ids={
                **related_entity_ids,
                "tripId": trip.id,
            },
            source="whatsapp",
            idempotency_key=f"{idempotency_key}:trip_created" if idempotency_key else None,
        )
        events.append(trip_event)
        trip.status = trip_event.new_state or trip.status
        self._trips.add(trip)
        events.append(
            self._event_log.record(
                event_type="MARKETPLACE_MATCH_CONFIRMED",
                actor_type="SYSTEM",
                entity_type="ShipmentRequest",
                entity_id=shipment.id,
                summary="Match confirmado por doble aceptacion",
                related_entity_ids={
                    **related_entity_ids,
                    "tripId": trip.id,
                },
                payload={
                    "trigger": "producer_accepted_interested_offer",
                    "trip_offer_id": offer.id,
                    "carrier_id": offer.carrier_id,
                },
                source="marketplace",
                idempotency_key=f"{idempotency_key}:marketplace_match_confirmed" if idempotency_key else None,
            )
        )
        self._mark_shipment_assigned(
            shipment,
            assignment,
            producer_actor_id,
            idempotency_key,
            events,
            actor_type="Producer",
            source="whatsapp",
        )
        carrier_notification: NotificationResult | None = None
        producer_notification: ProducerNotificationResult | None = None
        if self._notification_service is not None:
            notification_key = idempotency_key or f"producer_acceptance:{trip.id}"
            carrier_notification = self._notification_service.send_manual_message(
                carrier_id=assignment.carrier_id,
                body=(
                    "El productor aceptó tu interés por la carga. "
                    "El viaje quedó confirmado y planificado. Te avisaremos los próximos pasos."
                ),
                entity_type="Trip",
                entity_id=trip.id,
                operator_user_id=producer_actor_id,
                idempotency_key=f"{notification_key}:notify-carrier-trip-planned",
                notification_type="TRIP_PLANNED",
            )
            events.extend(carrier_notification.events)
            producer_notification = self._notification_service.send_producer_message(
                phone_number=normalized_phone,
                body=(
                    f"Tu oferta fue aceptada. El viaje {trip.id} quedó planificado. "
                    "Podés consultar ‘ver mi viaje’ para ver su estado."
                ),
                entity_type="Trip",
                entity_id=trip.id,
                operator_user_id=producer_actor_id,
                idempotency_key=f"{notification_key}:notify-producer-trip-planned",
                notification_type="TRIP_PLANNED",
            )
            events.extend(producer_notification.events)
        return ProducerOfferAcceptanceResult(
            assignment=assignment,
            trip=trip,
            shipment=shipment,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def _recent_chat_draft_summaries(
        self,
        *,
        limit: int,
        phone_keys: set[str],
    ) -> list[ChatDraftShipmentSummary]:
        summaries: list[tuple[EventLog, ChatDraftShipmentSummary]] = []
        seen_shipment_ids: set[str] = set()

        for event in sorted(self._event_log.events, key=lambda item: item.occurred_at, reverse=True):
            if event.event_type != "SHIPMENT_DRAFT_CREATED_FROM_CHAT":
                continue
            if event.entity_id in seen_shipment_ids:
                continue
            source_phone_number = self._payload_string(event, "phone_number")
            if phone_keys and not self._phone_lookup_keys(source_phone_number).intersection(phone_keys):
                continue
            shipment = self._shipment_requests.get(event.entity_id)
            if shipment is None:
                continue
            seen_shipment_ids.add(shipment.id)
            summaries.append(
                (
                    event,
                    ChatDraftShipmentSummary(
                        shipment_id=shipment.id,
                        status=shipment.status,
                        cargo_category=shipment.cargo_category,
                        cargo_type=shipment.cargo_type,
                        quantity_unit=shipment.quantity_unit,
                        livestock_type=shipment.livestock_type,
                        quantity_estimate=shipment.quantity_estimate,
                        operational_notes=shipment.operational_notes,
                        created_at=shipment.created_at,
                        source_phone_number=source_phone_number,
                    ),
                )
            )
            if len(summaries) >= limit:
                break

        return [summary for _, summary in summaries]

    def _chat_draft_source_phones(self) -> dict[str, str | None]:
        phones: dict[str, str | None] = {}
        for event in sorted(self._event_log.events, key=lambda item: item.occurred_at, reverse=True):
            if event.event_type != "SHIPMENT_DRAFT_CREATED_FROM_CHAT":
                continue
            phones.setdefault(event.entity_id, self._payload_string(event, "phone_number"))
        return phones

    def list_offers_for_shipment(self, shipment_request_id: str) -> list[TripOffer]:
        self._require_shipment(shipment_request_id)
        return [
            offer for offer in self._trip_offers.list() if offer.shipment_request_id == shipment_request_id
        ]

    def list_messages_for_conversation(self, conversation_session_id: str) -> list[Message]:
        self._require_conversation(conversation_session_id)
        return [
            message
            for message in self._messages.list()
            if message.conversation_session_id == conversation_session_id
        ]

    def create_shipment_draft_from_chat(
        self,
        *,
        text: str,
        phone_number: str | None,
        operator_user_id: str,
        idempotency_key: str | None = None,
    ) -> ShipmentDraftFromChatResult:
        if not text.strip():
            raise AdminOpsError("text is required")

        if idempotency_key:
            existing = self._draft_result_for_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        parsed = parse_chat_shipment_text(text)
        normalized_phone = None
        if phone_number:
            try:
                normalized_phone = normalize_phone_number(phone_number)
            except PhoneNormalizationError:
                normalized_phone = None
        shipment = self._shipment_requests.add(
            ShipmentRequest(
                status="INCOMPLETE" if parsed.quantity_estimate is not None and parsed.quantity_unit is None else "DRAFT",
                producer_phone_number=normalized_phone,
                cargo_category=parsed.cargo_category,
                cargo_type=parsed.cargo_type,
                quantity_unit=parsed.quantity_unit,
                livestock_type=parsed.livestock_type,
                quantity_estimate=parsed.quantity_estimate,
                operational_notes=text,
                missing_critical_fields=["quantity_unit"]
                if parsed.quantity_estimate is not None and parsed.quantity_unit is None
                else [],
                requires_human_review=parsed.quantity_estimate is not None and parsed.quantity_unit is None,
            )
        )
        event = self._event_log.record(
            event_type="SHIPMENT_DRAFT_CREATED_FROM_CHAT",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            summary="Borrador de carga creado desde chat",
            related_entity_ids={"loadId": shipment.id},
            previous_state=None,
            new_state=shipment.status,
            payload={
                "text": text,
                "phone_number": phone_number,
                "source": "kapso",
                "cargo_category": shipment.cargo_category,
                "cargo_type": shipment.cargo_type,
                "quantity_unit": shipment.quantity_unit,
            },
            source="kapso",
            idempotency_key=idempotency_key,
        )
        return ShipmentDraftFromChatResult(shipment=shipment, event=event)

    def validate_shipment(
        self,
        *,
        shipment_request_id: str,
        operator_user_id: str,
        notes: str | None = None,
        allow_missing_override: bool = False,
        idempotency_key: str | None = None,
    ) -> ShipmentRequest:
        shipment = self._require_shipment(shipment_request_id)
        if shipment.status == "VALIDATED" and self._has_event(idempotency_key):
            return shipment
        if shipment.quantity_estimate is not None and not shipment.quantity_unit:
            raise AdminOpsError("Cannot validate shipment without a confirmed quantity unit")
        if shipment.missing_critical_fields and not allow_missing_override:
            raise AdminOpsError("Cannot validate shipment with missing critical fields without override")

        event = self._transitions.transition(
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            from_state=shipment.status,
            event_type="LOAD_VALIDATED",
            to_state="VALIDATED",
            actor_type="Operator",
            actor_id=operator_user_id,
            summary="Carga validada por operador",
            payload={"notes": notes, "allow_missing_override": allow_missing_override},
            source="operator_console",
            idempotency_key=idempotency_key,
        )
        shipment.status = event.new_state or shipment.status
        shipment.requires_human_review = False
        # The dev operator header is an auth boundary, not yet a persisted User.
        # EventLog.actor_id keeps the audit trail without requiring a users row.
        shipment.validated_by_user_id = None
        shipment.validated_at = event.occurred_at
        self._shipment_requests.save(shipment)
        return shipment

    def publish_shipment(
        self,
        *,
        shipment_request_id: str,
        operator_user_id: str,
        carrier_ids: list[str],
        idempotency_key: str | None = None,
    ) -> ShipmentPublishResult:
        shipment = self._require_shipment(shipment_request_id)
        if shipment.quantity_estimate is not None and not shipment.quantity_unit:
            raise AdminOpsError("Cannot publish shipment without a confirmed quantity unit")
        if not carrier_ids and self._routing is None:
            raise AdminOpsError("Cannot publish shipment without carriers; manual fallback required")
        if shipment.status == "PUBLISHED" and self._has_event(idempotency_key):
            return ShipmentPublishResult(
                shipment=shipment,
                events=self._events_for_idempotency_prefix(idempotency_key),
            )
        if self._routing is not None:
            carrier_ids = []
        events: list[EventLog] = []
        event = self._transitions.transition(
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            from_state=shipment.status,
            event_type="LOAD_PUBLISHED",
            to_state="PUBLISHED",
            actor_type="Operator",
            actor_id=operator_user_id,
            summary="Carga publicada a transportistas",
            payload={"carrier_ids": carrier_ids},
            source="operator_console",
            idempotency_key=idempotency_key,
        )
        events.append(event)
        shipment.status = event.new_state or shipment.status
        self._shipment_requests.save(shipment)
        if self._routing is not None:
            carrier_ids = self._routing.publish(shipment)

        events.append(
            self._event_log.record(
                event_type="BROADCAST_SENT",
                actor_type="OPERATOR",
                actor_id=operator_user_id,
                entity_type="ShipmentRequest",
                entity_id=shipment.id,
                summary="Broadcast operativo registrado",
                related_entity_ids={"loadId": shipment.id},
                payload={"carrier_count": len(carrier_ids), "carrier_ids": carrier_ids},
                source="operator_console",
                idempotency_key=f"{idempotency_key}:broadcast" if idempotency_key else None,
            )
        )
        for carrier_id in ([] if self._routing is not None else carrier_ids):
            events.append(
                self._event_log.record(
                    event_type="CARRIER_NOTIFIED",
                    actor_type="SYSTEM",
                    entity_type="ShipmentRequest",
                    entity_id=shipment.id,
                    summary="Transportista marcado para notificacion",
                    related_entity_ids={"loadId": shipment.id},
                    payload={"carrier_id": carrier_id},
                    source="system",
                    idempotency_key=f"{idempotency_key}:carrier:{carrier_id}" if idempotency_key else None,
                )
            )
        notification_results: tuple[NotificationResult, ...] = tuple(self._routing.last_dispatch_results) if self._routing is not None else ()
        if self._notification_service is not None and self._routing is None:
            notification_results = self._notification_service.send_new_load_alerts(
                shipment=shipment,
                carrier_ids=carrier_ids,
                operator_user_id=operator_user_id,
            )
            for notification_result in notification_results:
                events.extend(notification_result.events)
        return ShipmentPublishResult(
            shipment=shipment,
            events=tuple(events),
            notification_results=notification_results,
        )

    def register_manual_interest(
        self,
        *,
        shipment_request_id: str,
        carrier_id: str,
        operator_user_id: str,
        notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> ManualInterestResult:
        shipment = self._require_shipment(shipment_request_id)
        carrier = self._require_carrier(carrier_id)
        if shipment.status not in {"PUBLISHED", "MATCHING"}:
            raise AdminOpsError(
                f"Shipment request must be in PUBLISHED or MATCHING status to register interest; got {shipment.status}"
            )
        if self._find_active_assignment_by_shipment(shipment.id) is not None:
            raise AdminOpsError("Shipment request already has an active assignment")

        existing_offer = self._find_offer(
            shipment_request_id=shipment.id,
            carrier_id=carrier.id,
            response_type="INTERESTED",
        )
        events: list[EventLog] = []
        if existing_offer is None:
            offer = self._trip_offers.add(
                TripOffer(
                    shipment_request_id=shipment.id,
                    test_run_id=shipment.test_run_id,
                    carrier_id=carrier.id,
                    response_type="INTERESTED",
                    status="RECEIVED",
                    confidence="operator_override",
                    requires_human_review=False,
                )
            )
            events.append(
                self._event_log.record(
                    event_type="CARRIER_INTERESTED",
                    actor_type="OPERATOR",
                    actor_id=operator_user_id,
                    entity_type="Offer",
                    entity_id=offer.id,
                    summary="Interes de transportista registrado manualmente",
                    related_entity_ids={
                        "loadId": shipment.id,
                        "offerId": offer.id,
                        "carrierId": carrier.id,
                    },
                    payload={
                        "carrier_id": carrier.id,
                        "shipment_request_id": shipment.id,
                        "manual_override": True,
                        "notes": notes,
                    },
                    source="backoffice",
                    idempotency_key=f"{idempotency_key}:offer" if idempotency_key else None,
                )
            )
        else:
            offer = existing_offer

        if shipment.status == "PUBLISHED":
            events.append(
                self._mark_shipment_matching(
                    shipment=shipment,
                    operator_user_id=operator_user_id,
                    trip_offer_id=offer.id,
                    trigger="manual_interest",
                    idempotency_key=f"{idempotency_key}:matching" if idempotency_key else None,
                )
            )

        carrier_notification: NotificationResult | None = None
        producer_notification: ProducerNotificationResult | None = None
        if self._notification_service is not None:
            carrier_notification = self._notification_service.send_manual_message(
                carrier_id=carrier.id,
                body=(
                    f"Soporte te registró como interesado en la carga {shipment.id}. "
                    "Si el productor te elige, te avisamos."
                ),
                entity_type="ShipmentRequest",
                entity_id=shipment.id,
                operator_user_id=operator_user_id,
                idempotency_key=f"{idempotency_key}:notify-carrier-interest"
                if idempotency_key
                else f"manual_interest:{shipment.id}:{carrier.id}:carrier",
            )
            events.extend(carrier_notification.events)
            if shipment.producer_phone_number:
                producer_notification = self._notification_service.send_producer_message(
                    phone_number=shipment.producer_phone_number,
                    body=(
                        f"Soporte registró a {carrier.name} como interesado en tu carga {shipment.id}. "
                        "Escribí 'ver interesados' para verla."
                    ),
                    entity_type="ShipmentRequest",
                    entity_id=shipment.id,
                    operator_user_id=operator_user_id,
                    idempotency_key=f"{idempotency_key}:notify-producer-interest"
                    if idempotency_key
                    else f"manual_interest:{shipment.id}:{carrier.id}:producer",
                    notification_type="INTEREST_REGISTERED",
                )
                events.extend(producer_notification.events)

        return ManualInterestResult(
            shipment=shipment,
            trip_offer=offer,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def select_offer(
        self,
        *,
        shipment_request_id: str,
        trip_offer_id: str,
        operator_user_id: str,
        idempotency_key: str | None = None,
    ) -> OfferSelectionResult:
        if idempotency_key and self._has_event(idempotency_key):
            existing = self._offer_selection_result_for_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        shipment = self._require_shipment(shipment_request_id)
        offer = self._require_offer(trip_offer_id)
        if offer.shipment_request_id != shipment.id:
            raise AdminOpsError("Trip offer does not belong to shipment request")
        active_assignment = self._find_active_assignment_by_shipment(shipment.id)
        if active_assignment is not None:
            trip = self._find_trip_by_assignment(active_assignment.id)
            if trip is None:
                trip = self._create_planned_trip_from_assignment(
                    assignment=active_assignment,
                    operator_user_id=operator_user_id,
                    idempotency_key=idempotency_key,
                )
            return OfferSelectionResult(assignment=active_assignment, trip=trip, events=())
        if shipment.status != "MATCHING":
            raise AdminOpsError(
                f"Shipment request must be in MATCHING status to select offer; got {shipment.status}"
            )

        assignment = self._assignments.add(
            Assignment(
                shipment_request_id=shipment.id,
                test_run_id=shipment.test_run_id,
                trip_offer_id=offer.id,
                carrier_id=offer.carrier_id,
                selected_by_user_id=operator_user_id,
                status="PROPOSED",
            )
        )
        related_entity_ids = self._assignment_related_ids(assignment)
        events: list[EventLog] = []
        events.append(
            self._event_log.record(
                event_type="ASSIGNMENT_CREATED",
                actor_type="OPERATOR",
                actor_id=operator_user_id,
                entity_type="Assignment",
                entity_id=assignment.id,
                summary="Assignment creado desde oferta seleccionada",
                related_entity_ids=related_entity_ids,
                previous_state=None,
                new_state=assignment.status,
                payload={"trip_offer_id": offer.id, "carrier_id": offer.carrier_id},
                source="operator_console",
                idempotency_key=f"{idempotency_key}:assignment_created" if idempotency_key else None,
            )
        )
        events.append(
            self._event_log.record(
                event_type="ASSIGNMENT_SELECTED",
                actor_type="OPERATOR",
                actor_id=operator_user_id,
                entity_type="Assignment",
                entity_id=assignment.id,
                summary="Oferta seleccionada por operador para avanzar",
                related_entity_ids=related_entity_ids,
                previous_state=assignment.status,
                new_state=assignment.status,
                payload={"trip_offer_id": offer.id, "carrier_id": offer.carrier_id},
                source="operator_console",
                idempotency_key=f"{idempotency_key}:assignment_selected" if idempotency_key else None,
            )
        )

        trip = Trip(
            shipment_request_id=shipment.id,
            test_run_id=assignment.test_run_id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            vehicle_id=assignment.vehicle_id,
            status="PLANNED",
        )
        trip_event = self._transitions.transition(
            entity_type="Trip",
            entity_id=trip.id,
            from_state=None,
            event_type="TRIP_CREATED",
            to_state="PLANNED",
            actor_type="Operator",
            actor_id=operator_user_id,
            summary="Viaje planificado desde oferta seleccionada",
            context=TransitionContext(assignment_selected=True),
            related_entity_ids={
                **related_entity_ids,
                "tripId": trip.id,
            },
            source="operator_console",
            idempotency_key=f"{idempotency_key}:trip_created" if idempotency_key else None,
        )
        events.append(trip_event)
        trip.status = trip_event.new_state or trip.status
        self._trips.add(trip)
        return OfferSelectionResult(assignment=assignment, trip=trip, events=tuple(events))

    def assign_shipment_to_carrier_manually(
        self,
        *,
        shipment_request_id: str,
        carrier_id: str,
        operator_user_id: str,
        confirmation_notes: str | None = None,
        interest_notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> ManualAssignmentResult:
        if self._find_active_assignment_by_shipment(shipment_request_id) is not None:
            raise AdminOpsError("Shipment request already has an active assignment")

        manual_interest = self.register_manual_interest(
            shipment_request_id=shipment_request_id,
            carrier_id=carrier_id,
            operator_user_id=operator_user_id,
            notes=interest_notes,
            idempotency_key=f"{idempotency_key}:interest" if idempotency_key else None,
        )
        selection = self.select_offer(
            shipment_request_id=shipment_request_id,
            trip_offer_id=manual_interest.trip_offer.id,
            operator_user_id=operator_user_id,
            idempotency_key=f"{idempotency_key}:select" if idempotency_key else None,
        )
        confirmation = self.confirm_assignment(
            assignment_id=selection.assignment.id,
            operator_user_id=operator_user_id,
            confirmation_notes=confirmation_notes,
            idempotency_key=f"{idempotency_key}:confirm" if idempotency_key else None,
        )

        carrier = self._require_carrier(carrier_id)
        events = [
            *manual_interest.events,
            *selection.events,
            *confirmation.events,
        ]
        carrier_notification: NotificationResult | None = None
        producer_notification: ProducerNotificationResult | None = None
        if self._notification_service is not None:
            carrier_notification = self._notification_service.send_manual_message(
                carrier_id=carrier.id,
                body=(
                    f"Soporte te asignó la carga {shipment_request_id}. "
                    f"Viaje {confirmation.trip.id} planificado."
                ),
                entity_type="Trip",
                entity_id=confirmation.trip.id,
                operator_user_id=operator_user_id,
                idempotency_key=f"{idempotency_key}:notify-carrier-assignment"
                if idempotency_key
                else f"manual_assignment:{shipment_request_id}:{carrier.id}:carrier",
            )
            events.extend(carrier_notification.events)
            shipment = self._require_shipment(shipment_request_id)
            if shipment.producer_phone_number:
                producer_notification = self._notification_service.send_producer_message(
                    phone_number=shipment.producer_phone_number,
                    body=(
                        f"Tu carga {shipment.id} quedó asignada a {carrier.name}. "
                        f"Viaje {confirmation.trip.id} planificado."
                    ),
                    entity_type="Trip",
                    entity_id=confirmation.trip.id,
                    operator_user_id=operator_user_id,
                    idempotency_key=f"{idempotency_key}:notify-producer-assignment"
                    if idempotency_key
                    else f"manual_assignment:{shipment_request_id}:{carrier.id}:producer",
                    notification_type="ASSIGNMENT_CONFIRMED",
                )
                events.extend(producer_notification.events)

        return ManualAssignmentResult(
            shipment=self._require_shipment(shipment_request_id),
            trip_offer=manual_interest.trip_offer,
            assignment=confirmation.assignment,
            trip=confirmation.trip,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def _create_planned_trip_from_assignment(
        self,
        *,
        assignment: Assignment,
        operator_user_id: str,
        idempotency_key: str | None,
    ) -> Trip:
        trip = Trip(
            shipment_request_id=assignment.shipment_request_id,
            test_run_id=assignment.test_run_id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            vehicle_id=assignment.vehicle_id,
            status="PLANNED",
        )
        trip_event = self._transitions.transition(
            entity_type="Trip",
            entity_id=trip.id,
            from_state=None,
            event_type="TRIP_CREATED",
            to_state="PLANNED",
            actor_type="Operator",
            actor_id=operator_user_id,
            summary="Viaje planificado desde assignment activo",
            context=TransitionContext(assignment_selected=True),
            related_entity_ids={
                "loadId": assignment.shipment_request_id,
                "assignmentId": assignment.id,
                "tripId": trip.id,
            },
            source="operator_console",
            idempotency_key=f"{idempotency_key}:trip_created_existing_assignment" if idempotency_key else None,
        )
        trip.status = trip_event.new_state or trip.status
        self._trips.add(trip)
        return trip

    @routing_locked
    def confirm_assignment(
        self,
        *,
        assignment_id: str,
        operator_user_id: str,
        confirmation_notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> AssignmentConfirmationResult:
        assignment = self._require_assignment(assignment_id)
        shipment = self._require_shipment(assignment.shipment_request_id)
        if assignment.status == "CONFIRMED" and self._has_event(idempotency_key):
            trip = self._find_trip_by_assignment(assignment.id)
            if trip is None:
                raise AdminOpsError("Assignment is confirmed but trip was not found")
            return AssignmentConfirmationResult(
                assignment=assignment,
                trip=trip,
                events=self._events_for_idempotency_prefix(idempotency_key),
            )
        self._ensure_confirmable_shipment(shipment)
        if self._routing is not None:
            try:
                self._routing.commit_availability(shipment, assignment.carrier_id)
            except ValueError as exc:
                raise AdminOpsError(str(exc)) from exc
        events: list[EventLog] = []

        if assignment.status == "PROPOSED":
            event = self._transitions.transition(
                entity_type="Assignment",
                entity_id=assignment.id,
                from_state=assignment.status,
                event_type="ASSIGNMENT_CREATED",
                to_state="PENDING_CONFIRMATION",
                actor_type="Operator",
                actor_id=operator_user_id,
                summary="Assignment preparado para confirmacion",
                related_entity_ids=self._assignment_related_ids(assignment),
                source="operator_console",
                idempotency_key=f"{idempotency_key}:created" if idempotency_key else None,
            )
            events.append(event)
            assignment.status = event.new_state or assignment.status

        event = self._transitions.transition(
            entity_type="Assignment",
            entity_id=assignment.id,
            from_state=assignment.status,
            event_type="ASSIGNMENT_CONFIRMED",
            to_state="CONFIRMED",
            actor_type="Operator",
            actor_id=operator_user_id,
            summary="Assignment confirmado por operador",
            related_entity_ids=self._assignment_related_ids(assignment),
            payload={"confirmation_notes": confirmation_notes},
            source="operator_console",
            idempotency_key=f"{idempotency_key}:confirmed" if idempotency_key else None,
        )
        events.append(event)
        assignment.status = event.new_state or assignment.status
        assignment.confirmed_by_user_id = operator_user_id
        assignment.confirmed_at = event.occurred_at
        assignment.confirmation_notes = confirmation_notes
        self._assignments.save(assignment)

        trip = self._find_trip_by_assignment(assignment.id)
        if trip is None:
            trip = Trip(
                shipment_request_id=assignment.shipment_request_id,
                test_run_id=assignment.test_run_id,
                assignment_id=assignment.id,
                carrier_id=assignment.carrier_id,
                vehicle_id=assignment.vehicle_id,
            )
            trip_event = self._transitions.transition(
                entity_type="Trip",
                entity_id=trip.id,
                from_state=None,
                event_type="TRIP_CREATED",
                to_state="PLANNED",
                actor_type="Operator",
                actor_id=operator_user_id,
                summary="Viaje planificado desde assignment confirmado",
                context=TransitionContext(assignment_confirmed=True),
                related_entity_ids={
                    "loadId": assignment.shipment_request_id,
                    "assignmentId": assignment.id,
                    "tripId": trip.id,
                },
                source="operator_console",
                idempotency_key=f"{idempotency_key}:trip" if idempotency_key else None,
            )
            events.append(trip_event)
            trip.status = trip_event.new_state or trip.status
            self._trips.add(trip)
        self._mark_shipment_assigned(shipment, assignment, operator_user_id, idempotency_key, events)
        return AssignmentConfirmationResult(assignment=assignment, trip=trip, events=tuple(events))

    def cancel_trip(
        self,
        *,
        trip_id: str,
        operator_user_id: str,
        reason: str,
        notify_parties: bool = False,
        idempotency_key: str | None = None,
    ) -> TripStatusUpdateResult:
        trip = self._require_trip(trip_id)
        shipment = self._shipment_requests.get(trip.shipment_request_id)
        if trip.status == "CANCELLED" and self._has_event(idempotency_key):
            return TripStatusUpdateResult(
                shipment=shipment,
                trip=trip,
                events=self._events_for_idempotency_prefix(idempotency_key),
            )
        event = self._transitions.transition(
            entity_type="Trip",
            entity_id=trip.id,
            from_state=trip.status,
            event_type="TRIP_CANCELLED",
            to_state="CANCELLED",
            actor_type="Operator",
            actor_id=operator_user_id,
            summary="Viaje cancelado por operador",
            related_entity_ids={
                "loadId": trip.shipment_request_id,
                "assignmentId": trip.assignment_id,
                "tripId": trip.id,
            },
            payload={"reason": reason},
            source="operator_console",
            idempotency_key=idempotency_key,
        )
        events = [event]
        trip.status = event.new_state or trip.status
        trip.cancelled_at = event.occurred_at
        trip.closure_notes = reason
        trip.requires_human_review = True
        self._trips.save(trip)
        carrier_notification = None
        producer_notification = None
        if notify_parties and shipment is not None:
            carrier_notification, producer_notification = self._notify_trip_status_change(
                trip=trip,
                shipment=shipment,
                operator_user_id=operator_user_id,
                carrier_message=f"El viaje {trip.id} fue cancelado. Motivo: {reason}.",
                producer_message=f"El viaje {trip.id} de tu carga {shipment.id} fue cancelado. Motivo: {reason}.",
                entity_id=trip.id,
                notification_suffix="cancelled",
                notification_type="TRIP_CANCELLED",
                idempotency_key=idempotency_key,
            )
            events.extend(carrier_notification.events if carrier_notification else ())
            events.extend(producer_notification.events if producer_notification else ())
        return TripStatusUpdateResult(
            shipment=shipment,
            trip=trip,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def start_trip(
        self,
        *,
        trip_id: str,
        operator_user_id: str,
        notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> TripStatusUpdateResult:
        if self._trip_readiness_guard is not None:
            self._trip_readiness_guard(trip_id)
        trip = self._require_trip(trip_id)
        shipment = self._require_shipment(trip.shipment_request_id)
        if trip.status == "LOADING_PENDING" and self._has_event(idempotency_key):
            return TripStatusUpdateResult(
                shipment=shipment,
                trip=trip,
                events=self._events_for_idempotency_prefix(idempotency_key),
            )
        events = self._advance_trip_to_state(
            trip=trip,
            operator_user_id=operator_user_id,
            target_status="LOADING_PENDING",
            notes=notes,
            idempotency_key=idempotency_key,
        )
        carrier_notification, producer_notification = self._notify_trip_status_change(
            trip=trip,
            shipment=shipment,
            operator_user_id=operator_user_id,
            carrier_message=f"El viaje {trip.id} fue iniciado y está preparando la carga.",
            producer_message=f"El viaje {trip.id} de tu carga {shipment.id} fue iniciado.",
            entity_id=trip.id,
            notification_suffix="started",
            notification_type="TRIP_STARTED",
            idempotency_key=idempotency_key,
        )
        events.extend(carrier_notification.events if carrier_notification else ())
        events.extend(producer_notification.events if producer_notification else ())
        return TripStatusUpdateResult(
            shipment=shipment,
            trip=trip,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def mark_trip_in_transit(
        self,
        *,
        trip_id: str,
        operator_user_id: str,
        notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> TripStatusUpdateResult:
        if self._trip_readiness_guard is not None:
            self._trip_readiness_guard(trip_id)
        trip = self._require_trip(trip_id)
        shipment = self._require_shipment(trip.shipment_request_id)
        if trip.status == "IN_TRANSIT" and self._has_event(idempotency_key):
            return TripStatusUpdateResult(
                shipment=shipment,
                trip=trip,
                events=self._events_for_idempotency_prefix(idempotency_key),
            )
        events = self._advance_trip_to_state(
            trip=trip,
            operator_user_id=operator_user_id,
            target_status="IN_TRANSIT",
            notes=notes,
            idempotency_key=idempotency_key,
        )
        if self._routing is not None:
            self._routing.transit(trip)
        carrier_notification, producer_notification = self._notify_trip_status_change(
            trip=trip,
            shipment=shipment,
            operator_user_id=operator_user_id,
            carrier_message=f"El viaje {trip.id} quedó marcado en tránsito.",
            producer_message=f"El viaje {trip.id} de tu carga {shipment.id} ya está en tránsito.",
            entity_id=trip.id,
            notification_suffix="in_transit",
            notification_type="TRIP_IN_TRANSIT",
            idempotency_key=idempotency_key,
        )
        events.extend(carrier_notification.events if carrier_notification else ())
        events.extend(producer_notification.events if producer_notification else ())
        return TripStatusUpdateResult(
            shipment=shipment,
            trip=trip,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def complete_trip(
        self,
        *,
        trip_id: str,
        operator_user_id: str,
        notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> TripStatusUpdateResult:
        trip = self._require_trip(trip_id)
        shipment = self._require_shipment(trip.shipment_request_id)
        if trip.status == "COMPLETED" and self._has_event(idempotency_key):
            return TripStatusUpdateResult(
                shipment=shipment,
                trip=trip,
                events=self._events_for_idempotency_prefix(idempotency_key),
            )
        events = self._advance_trip_to_state(
            trip=trip,
            operator_user_id=operator_user_id,
            target_status="COMPLETED",
            notes=notes,
            idempotency_key=idempotency_key,
        )
        if shipment.status == "ASSIGNED":
            shipment_event = self._transitions.transition(
                entity_type="ShipmentRequest",
                entity_id=shipment.id,
                from_state=shipment.status,
                event_type="TRIP_COMPLETED",
                to_state="CLOSED",
                actor_type="Operator",
                actor_id=operator_user_id,
                summary="Carga cerrada por viaje completado",
                related_entity_ids={"loadId": shipment.id, "tripId": trip.id},
                payload={"notes": notes},
                source="backoffice",
                idempotency_key=f"{idempotency_key}:shipment_closed" if idempotency_key else None,
            )
            shipment.status = shipment_event.new_state or shipment.status
            self._shipment_requests.save(shipment)
            events.append(shipment_event)
        carrier_notification, producer_notification = self._notify_trip_status_change(
            trip=trip,
            shipment=shipment,
            operator_user_id=operator_user_id,
            carrier_message=f"El viaje {trip.id} fue marcado como completado.",
            producer_message=f"El viaje {trip.id} de tu carga {shipment.id} fue completado.",
            entity_id=trip.id,
            notification_suffix="completed",
            notification_type="TRIP_COMPLETED",
            idempotency_key=idempotency_key,
        )
        events.extend(carrier_notification.events if carrier_notification else ())
        events.extend(producer_notification.events if producer_notification else ())
        return TripStatusUpdateResult(
            shipment=shipment,
            trip=trip,
            events=tuple(events),
            carrier_notification=carrier_notification,
            producer_notification=producer_notification,
        )

    def request_manual_review(
        self,
        *,
        entity_type: str,
        entity_id: str,
        operator_user_id: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> EventLog:
        self._mark_requires_human_review(entity_type, entity_id)
        return self._event_log.record(
            event_type="HUMAN_REVIEW_REQUESTED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            summary="Fallback manual activado por operador",
            payload={"reason": reason},
            source="operator_console",
            idempotency_key=idempotency_key,
        )

    def _mark_shipment_assigned(
        self,
        shipment: ShipmentRequest,
        assignment: Assignment,
        actor_id: str,
        idempotency_key: str | None,
        events: list[EventLog],
        *,
        actor_type: str = "Operator",
        source: str = "operator_console",
    ) -> None:
        event = self._transitions.transition(
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            from_state=shipment.status,
            event_type="ASSIGNMENT_CONFIRMED",
            to_state="ASSIGNED",
            actor_type=actor_type,
            actor_id=actor_id,
            summary="Carga asignada por confirmacion de assignment",
            related_entity_ids={
                "loadId": shipment.id,
                "assignmentId": assignment.id,
            },
            source=source,
            idempotency_key=f"{idempotency_key}:shipment_assigned" if idempotency_key else None,
        )
        events.append(event)
        shipment.status = event.new_state or shipment.status
        self._shipment_requests.save(shipment)

    def _mark_shipment_matching(
        self,
        *,
        shipment: ShipmentRequest,
        operator_user_id: str,
        trip_offer_id: str,
        trigger: str,
        idempotency_key: str | None,
    ) -> EventLog:
        event = self._transitions.transition(
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            from_state=shipment.status,
            event_type="LOAD_MATCHING_STARTED",
            to_state="MATCHING",
            actor_type="SYSTEM",
            actor_id=operator_user_id,
            summary="Carga movida a matching por operador",
            payload={
                "shipment_request_id": shipment.id,
                "trigger": trigger,
                "trip_offer_id": trip_offer_id,
                "manual_override": True,
            },
            source="backoffice",
            idempotency_key=idempotency_key,
        )
        shipment.status = event.new_state or shipment.status
        self._shipment_requests.save(shipment)
        return event

    def _mark_requires_human_review(self, entity_type: str, entity_id: str) -> None:
        if entity_type in {"ShipmentRequest", "LivestockLoad"}:
            shipment = self._require_shipment(entity_id)
            shipment.requires_human_review = True
            self._shipment_requests.save(shipment)
        elif entity_type == "Trip":
            trip = self._require_trip(entity_id)
            trip.requires_human_review = True
            self._trips.save(trip)
        elif entity_type == "Assignment":
            assignment = self._require_assignment(entity_id)
            assignment.requires_human_review = True
            self._assignments.save(assignment)

    def _assignment_related_ids(self, assignment: Assignment) -> dict[str, str]:
        related = {
            "loadId": assignment.shipment_request_id,
            "assignmentId": assignment.id,
        }
        if assignment.trip_offer_id:
            related["offerId"] = assignment.trip_offer_id
        return related

    def _has_event(self, idempotency_key: str | None) -> bool:
        if not idempotency_key:
            return False
        return any(
            event.idempotency_key == idempotency_key
            or bool(event.idempotency_key and event.idempotency_key.startswith(f"{idempotency_key}:"))
            for event in self._event_log.events
        )

    def _events_for_idempotency_prefix(self, idempotency_key: str | None) -> tuple[EventLog, ...]:
        if not idempotency_key:
            return ()
        return tuple(
            event
            for event in self._event_log.events
            if event.idempotency_key == idempotency_key
            or bool(event.idempotency_key and event.idempotency_key.startswith(f"{idempotency_key}:"))
        )

    def _find_trip_by_assignment(self, assignment_id: str) -> Trip | None:
        for trip in self._trips.list():
            if trip.assignment_id == assignment_id:
                return trip
        return None

    def _advance_trip_to_state(
        self,
        *,
        trip: Trip,
        operator_user_id: str,
        target_status: str,
        notes: str | None,
        idempotency_key: str | None,
    ) -> list[EventLog]:
        state_steps: dict[str, tuple[tuple[str, str], ...]] = {
            "LOADING_PENDING": (("TRIP_STARTED", "LOADING_PENDING"),),
            "IN_TRANSIT": (
                ("TRIP_STARTED", "LOADING_PENDING"),
                ("TRIP_LOADING", "LOADING"),
                ("TRIP_IN_TRANSIT", "IN_TRANSIT"),
            ),
            "COMPLETED": (
                ("TRIP_STARTED", "LOADING_PENDING"),
                ("TRIP_LOADING", "LOADING"),
                ("TRIP_IN_TRANSIT", "IN_TRANSIT"),
                ("TRIP_DELIVERED", "DELIVERED"),
                ("TRIP_COMPLETED", "COMPLETED"),
            ),
        }
        if target_status not in state_steps:
            raise AdminOpsError(f"Unsupported trip target status: {target_status}")

        events: list[EventLog] = []
        path = state_steps[target_status]
        status_order = [status for _, status in path]
        current_index = status_order.index(trip.status) + 1 if trip.status in status_order else 0
        for index, (event_type, expected_status) in enumerate(path[current_index:], start=current_index + 1):
            if trip.status == expected_status:
                continue
            if trip.status == "COMPLETED":
                break
            event = self._transitions.transition(
                entity_type="Trip",
                entity_id=trip.id,
                from_state=trip.status,
                event_type=event_type,
                to_state=expected_status,
                actor_type="Operator",
                actor_id=operator_user_id,
                summary=self._trip_event_summary(event_type),
                related_entity_ids={
                    "loadId": trip.shipment_request_id,
                    "assignmentId": trip.assignment_id,
                    "tripId": trip.id,
                },
                payload={"notes": notes},
                source="backoffice",
                idempotency_key=f"{idempotency_key}:trip_step_{index}" if idempotency_key else None,
            )
            events.append(event)
            trip.status = event.new_state or trip.status
            if event_type == "TRIP_STARTED" and trip.started_at is None:
                trip.started_at = event.occurred_at
            if event_type == "TRIP_COMPLETED":
                trip.completed_at = event.occurred_at
                if notes:
                    trip.closure_notes = notes
            self._trips.save(trip)
        if self._routing is not None and trip.status in {"COMPLETED", "CANCELLED"}:
            self._routing.finish(trip)
        return events

    def _trip_event_summary(self, event_type: str) -> str:
        return {
            "TRIP_STARTED": "Viaje iniciado por operador",
            "TRIP_LOADING": "Carga en proceso",
            "TRIP_IN_TRANSIT": "Viaje marcado en transito",
            "TRIP_DELIVERED": "Viaje entregado",
            "TRIP_COMPLETED": "Viaje completado por operador",
        }.get(event_type, event_type)

    def _notify_trip_status_change(
        self,
        *,
        trip: Trip,
        shipment: ShipmentRequest,
        operator_user_id: str,
        carrier_message: str,
        producer_message: str,
        entity_id: str,
        notification_suffix: str,
        notification_type: str,
        idempotency_key: str | None,
    ) -> tuple[NotificationResult | None, ProducerNotificationResult | None]:
        if self._notification_service is None:
            return None, None
        carrier_notification = self._notification_service.send_manual_message(
            carrier_id=trip.carrier_id,
            body=carrier_message,
            entity_type="Trip",
            entity_id=entity_id,
            operator_user_id=operator_user_id,
            idempotency_key=f"{idempotency_key}:notify-carrier-{notification_suffix}"
            if idempotency_key
            else f"trip:{trip.id}:{notification_suffix}:carrier",
        )
        producer_notification: ProducerNotificationResult | None = None
        if shipment.producer_phone_number:
            producer_notification = self._notification_service.send_producer_message(
                phone_number=shipment.producer_phone_number,
                body=producer_message,
                entity_type="Trip",
                entity_id=entity_id,
                operator_user_id=operator_user_id,
                idempotency_key=f"{idempotency_key}:notify-producer-{notification_suffix}"
                if idempotency_key
                else f"trip:{trip.id}:{notification_suffix}:producer",
                notification_type=notification_type,
            )
        return carrier_notification, producer_notification

    def _journey_summary(
        self,
        *,
        shipment: ShipmentRequest,
        assignment: Assignment | None,
        trip: Trip | None,
        interested_offers_count: int,
        counterparty_name: str | None = None,
        counterparty_phone: str | None = None,
    ) -> JourneyStatusSummary:
        carrier = self._carriers.get(assignment.carrier_id) if assignment and self._carriers else None
        return JourneyStatusSummary(
            shipment_id=shipment.id,
            shipment_status=shipment.status,
            trip_id=trip.id if trip else None,
            trip_status=trip.status if trip else None,
            assignment_id=assignment.id if assignment else None,
            assignment_status=assignment.status if assignment else None,
            origin=self._location_label(shipment.origin_location_id),
            destination=self._location_label(shipment.destination_location_id),
            cargo_category=shipment.cargo_category,
            cargo_type=shipment.cargo_type,
            quantity_unit=shipment.quantity_unit,
            livestock_type=shipment.livestock_type,
            quantity_estimate=shipment.quantity_estimate,
            operational_notes=shipment.operational_notes,
            interested_offers_count=interested_offers_count,
            counterparty_id=carrier.id if carrier else None,
            counterparty_name=counterparty_name or (carrier.name if carrier else None),
            counterparty_phone=counterparty_phone
            or (carrier.normalized_phone_number or carrier.contact_phone if carrier else None),
            planned_start_at=trip.planned_start_at if trip else None,
            completed_at=trip.completed_at if trip else None,
            created_at=shipment.created_at,
        )

    def _location_label(self, location_id: str | None) -> str | None:
        if not location_id or self._locations is None:
            return None
        location = self._locations.get(location_id)
        if location is None:
            return None
        return location.normalized_name or location.locality or location.rural_reference or location.original_text

    def _find_active_assignment_by_shipment(self, shipment_request_id: str) -> Assignment | None:
        active_assignments = [
            assignment
            for assignment in self._assignments.list()
            if assignment.shipment_request_id == shipment_request_id
            and assignment.status in self.ACTIVE_ASSIGNMENT_STATES
        ]
        if not active_assignments:
            return None
        return self._canonical_assignment(active_assignments)

    def _active_assignment_shipment_ids(self) -> set[str]:
        return {
            assignment.shipment_request_id
            for assignment in self._assignments.list()
            if assignment.status in self.ACTIVE_ASSIGNMENT_STATES
        }

    def _canonical_active_assignments(self) -> list[Assignment]:
        assignments_by_shipment: dict[str, list[Assignment]] = {}
        for assignment in self._assignments.list():
            if assignment.status not in self.ACTIVE_ASSIGNMENT_STATES:
                continue
            assignments_by_shipment.setdefault(assignment.shipment_request_id, []).append(assignment)
        return [
            canonical
            for assignments in assignments_by_shipment.values()
            if (canonical := self._canonical_assignment(assignments)) is not None
        ]

    def _canonical_assignment(self, assignments: list[Assignment]) -> Assignment | None:
        if not assignments:
            return None
        return sorted(
            assignments,
            key=lambda assignment: (
                self.ACTIVE_ASSIGNMENT_STATUS_PRIORITY.get(assignment.status, 0),
                assignment.created_at,
            ),
            reverse=True,
        )[0]

    def _operation_summary_for_assignment(self, assignment: Assignment) -> OperationSummary | None:
        shipment = self._shipment_requests.get(assignment.shipment_request_id)
        if shipment is None:
            return None
        trip = self._find_trip_by_assignment(assignment.id)
        return OperationSummary(
            shipment_id=shipment.id,
            shipment_status=shipment.status,
            assignment_id=assignment.id,
            assignment_status=assignment.status,
            trip_id=trip.id if trip else None,
            trip_status=trip.status if trip else None,
            carrier_id=assignment.carrier_id,
            trip_offer_id=assignment.trip_offer_id,
            cargo_category=shipment.cargo_category,
            cargo_type=shipment.cargo_type,
            quantity_unit=shipment.quantity_unit,
            livestock_type=shipment.livestock_type,
            quantity_estimate=shipment.quantity_estimate,
            operational_notes=shipment.operational_notes,
            created_at=assignment.created_at,
        )

    def _interested_offer_counts_by_shipment(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for offer in self._trip_offers.list():
            if offer.response_type != "INTERESTED":
                continue
            counts[offer.shipment_request_id] = counts.get(offer.shipment_request_id, 0) + 1
        return counts

    def _producer_owns_shipment(self, shipment: ShipmentRequest, normalized_phone: str) -> bool:
        if not shipment.producer_phone_number:
            return False
        return bool(
            self._phone_lookup_keys(shipment.producer_phone_number).intersection(
                self._phone_lookup_keys(normalized_phone)
            )
        )

    def _producer_test_run_id(self, normalized_phone: str) -> str | None:
        if not self._enable_test_role_switching:
            return None
        phone_keys = self._phone_lookup_keys(normalized_phone)
        sessions = [
            session
            for session in self._conversation_sessions.list()
            if session.active_test_run_id
            and self._phone_lookup_keys(session.normalized_phone_number or session.participant_phone).intersection(
                phone_keys
            )
        ]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        if not sessions:
            return None
        session = sessions[0]
        if session.role_override != "Producer":
            raise AdminOpsError("Switch to Producer role before using producer actions in a test scenario")
        return session.active_test_run_id

    def _normalize_required_phone_number(self, phone_number: str | None) -> str:
        if not phone_number:
            raise AdminOpsError("producer phone number is required")
        try:
            return normalize_phone_number(phone_number)
        except PhoneNormalizationError as exc:
            raise AdminOpsError("producer phone number is invalid") from exc

    def _mask_phone(self, phone_number: str | None) -> str | None:
        if not phone_number:
            return None
        digits = "".join(character for character in phone_number if character.isdigit())
        if len(digits) <= 4:
            return "***"
        prefix = "+" if phone_number.strip().startswith("+") else ""
        return f"{prefix}{digits[:3]}***{digits[-3:]}"

    def _producer_offer_acceptance_result_for_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ProducerOfferAcceptanceResult | None:
        events = self._events_for_idempotency_prefix(idempotency_key)
        assignment_id = None
        trip_id = None
        shipment_id = None
        for event in events:
            if event.event_type == "ASSIGNMENT_CREATED":
                assignment_id = event.entity_id
            if event.event_type == "TRIP_CREATED":
                trip_id = event.entity_id
            if event.event_type == "MARKETPLACE_MATCH_CONFIRMED":
                shipment_id = event.entity_id
        if assignment_id is None or trip_id is None or shipment_id is None:
            return None
        assignment = self._assignments.get(assignment_id)
        trip = self._trips.get(trip_id)
        shipment = self._shipment_requests.get(shipment_id)
        if assignment is None or trip is None or shipment is None:
            return None
        return ProducerOfferAcceptanceResult(
            assignment=assignment,
            trip=trip,
            shipment=shipment,
            events=events,
        )

    def _offer_selection_result_for_idempotency_key(self, idempotency_key: str) -> OfferSelectionResult | None:
        events = self._events_for_idempotency_prefix(idempotency_key)
        assignment_id = None
        trip_id = None
        for event in events:
            if event.event_type in {"ASSIGNMENT_CREATED", "ASSIGNMENT_SELECTED"}:
                assignment_id = event.entity_id
            if event.event_type == "TRIP_CREATED":
                trip_id = event.entity_id
        if assignment_id is None or trip_id is None:
            return None
        assignment = self._assignments.get(assignment_id)
        trip = self._trips.get(trip_id)
        if assignment is None or trip is None:
            return None
        return OfferSelectionResult(assignment=assignment, trip=trip, events=events)

    def _draft_result_for_idempotency_key(self, idempotency_key: str) -> ShipmentDraftFromChatResult | None:
        for event in self._events_for_idempotency_prefix(idempotency_key):
            if event.event_type != "SHIPMENT_DRAFT_CREATED_FROM_CHAT":
                continue
            shipment = self._shipment_requests.get(event.entity_id)
            if shipment is None:
                return None
            return ShipmentDraftFromChatResult(shipment=shipment, event=event)
        return None

    def _ensure_confirmable_shipment(self, shipment: ShipmentRequest) -> None:
        if shipment.status not in self.CONFIRMABLE_SHIPMENT_STATES:
            raise AdminOpsError(
                f"Shipment request must be in MATCHING status to confirm assignment; got {shipment.status}"
            )
        if shipment.missing_critical_fields or shipment.requires_human_review:
            raise AdminOpsError("Shipment request is not operationally ready for assignment confirmation")

    def _require_shipment(self, shipment_request_id: str) -> ShipmentRequest:
        shipment = self._shipment_requests.get(shipment_request_id)
        if shipment is None:
            raise KeyError(shipment_request_id)
        return shipment

    def _require_assignment(self, assignment_id: str) -> Assignment:
        assignment = self._assignments.get(assignment_id)
        if assignment is None:
            raise KeyError(assignment_id)
        return assignment

    def _require_carrier(self, carrier_id: str) -> Carrier:
        if self._carriers is None:
            raise AdminOpsError("Carrier repository is not configured")
        carrier = self._carriers.get(carrier_id)
        if carrier is None:
            raise KeyError(carrier_id)
        return carrier

    def _find_offer(
        self,
        *,
        shipment_request_id: str,
        carrier_id: str,
        response_type: str,
    ) -> TripOffer | None:
        for offer in self._trip_offers.list():
            if (
                offer.shipment_request_id == shipment_request_id
                and offer.carrier_id == carrier_id
                and offer.response_type == response_type
            ):
                return offer
        return None

    def _require_offer(self, trip_offer_id: str) -> TripOffer:
        offer = self._trip_offers.get(trip_offer_id)
        if offer is None:
            raise KeyError(f"trip_offer:{trip_offer_id}")
        return offer

    def _require_trip(self, trip_id: str) -> Trip:
        trip = self._trips.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        return trip

    def _require_conversation(self, conversation_session_id: str) -> ConversationSession:
        conversation = self._conversation_sessions.get(conversation_session_id)
        if conversation is None:
            raise KeyError(conversation_session_id)
        return conversation

    def _payload_string(self, event: EventLog, key: str) -> str | None:
        value = event.payload.get(key)
        if value is None:
            return None
        return str(value)

    def _phone_lookup_keys(self, phone_number: str | None) -> set[str]:
        if not phone_number:
            return set()
        keys: set[str] = set()
        raw_digits = "".join(character for character in phone_number if character.isdigit())
        if raw_digits:
            keys.add(raw_digits)
        try:
            normalized = normalize_phone_number(phone_number)
        except PhoneNormalizationError:
            normalized = None
        if normalized:
            normalized_digits = normalized[1:] if normalized.startswith("+") else normalized
            keys.add(normalized_digits)
            if normalized_digits.startswith("549") and len(normalized_digits) >= 6:
                keys.add(f"54{normalized_digits[3:]}")
            if normalized_digits.startswith("54") and not normalized_digits.startswith("549"):
                national = normalized_digits[2:]
                if national.startswith("11") and len(national) == 10:
                    keys.add(f"549{national}")
        return keys
