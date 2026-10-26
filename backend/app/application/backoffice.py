from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Generic, Protocol, TypeVar

from app.domain.cargo import normalize_cargo_category, normalize_quantity_unit
from app.domain.events import EventLog
from app.domain.models import (
    Assignment,
    Carrier,
    CarrierOnboarding,
    ConversationSession,
    Document,
    Location,
    Message,
    ShipmentRequest,
    Trip,
    TripOffer,
    Vehicle,
    utc_now,
)


T = TypeVar("T")


class ReadRepository(Protocol, Generic[T]):
    def get(self, entity_id: str) -> T | None:
        pass

    def list(self, *, include_deleted: bool = False) -> list[T]:
        pass


class MutationRepository(ReadRepository[T], Protocol, Generic[T]):
    def add(self, entity: T) -> T:
        pass

    def save(self, entity: T) -> T:
        pass

    def soft_delete(self, entity_id: str) -> T:
        pass


class EventLogRepository(ReadRepository[EventLog], Protocol):
    def record(
        self,
        *,
        event_type: str,
        actor_type: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        actor_id: str | None = None,
        related_entity_ids: dict[str, str] | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "system",
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> EventLog:
        pass


@dataclass(frozen=True)
class ShipmentMutationInput:
    status: str | None = None
    producer_phone_number: str | None = None
    origin: str | None = None
    destination: str | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    weight_per_head_kg: Decimal | None = None
    operational_notes: str | None = None
    date_window_start: datetime | None = None
    date_window_end: datetime | None = None
    requires_human_review: bool | None = None
    has_ambiguous_location: bool | None = None
    has_estimated_values: bool | None = None


@dataclass(frozen=True)
class TripMutationInput:
    status: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    incident_notes: str | None = None
    closure_notes: str | None = None
    requires_human_review: bool | None = None


@dataclass(frozen=True)
class BackofficeOverview:
    open_conversations: int
    open_conversations_requiring_operator: int
    ambiguous_conversations: int
    failed_notifications: int
    total_shipments: int
    published_shipments: int
    shipments_in_matching: int
    assigned_shipments: int
    unassigned_published_shipments: int
    avg_unassigned_age_hours: float
    total_trips: int
    planned_trips: int
    in_progress_trips: int
    completed_trips: int
    cancelled_trips: int
    failed_trips: int
    total_carriers: int
    validated_carriers: int
    pending_validation_carriers: int
    carrier_onboarding_pending_review: int
    carrier_documents_pending_review: int
    total_documents: int
    pending_documents: int
    approved_documents: int
    rejected_documents: int


@dataclass(frozen=True)
class OpenConversationSummary:
    id: str
    participant_phone: str | None
    channel: str
    last_message_preview: str | None
    last_activity_at: datetime | None
    status: str
    needs_operator: bool
    related_entity_type: str | None
    related_entity_id: str | None


@dataclass(frozen=True)
class OpenConversationPage:
    items: list[OpenConversationSummary]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class UnassignedShipmentSummary:
    id: str
    origin: str | None
    destination: str | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    weight_per_head_kg: Decimal | None
    status: str
    created_at: datetime
    age_hours: float
    offers_count: int
    interested_carriers_count: int


@dataclass(frozen=True)
class ShipmentDetailSummary:
    id: str
    test_run_id: str | None
    status: str
    producer_phone_number: str | None
    origin: str | None
    destination: str | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_unit: str | None
    livestock_type: str | None
    quantity_estimate: Decimal | None
    weight_per_head_kg: Decimal | None
    operational_notes: str | None
    date_window_start: datetime | None
    date_window_end: datetime | None
    source_message_id: str | None
    source_message_preview: str | None
    requires_human_review: bool
    has_ambiguous_location: bool
    has_estimated_values: bool
    missing_critical_fields: list[str]
    field_confidence: dict[str, str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ShipmentOfferDetailSummary:
    id: str
    carrier_id: str
    carrier_name: str | None
    carrier_phone: str | None
    vehicle_id: str | None
    vehicle_plate: str | None
    response_type: str
    status: str
    price_estimate: Decimal | None
    availability_window_start: datetime | None
    availability_window_end: datetime | None
    confidence: str
    requires_human_review: bool
    source_message_id: str | None
    source_message_preview: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ShipmentAssignmentDetailSummary:
    id: str
    shipment_request_id: str
    carrier_id: str
    carrier_name: str | None
    carrier_phone: str | None
    vehicle_id: str | None
    vehicle_plate: str | None
    trip_offer_id: str | None
    status: str
    selected_by_user_id: str
    confirmed_by_user_id: str | None
    confirmed_at: datetime | None
    confirmation_notes: str | None
    requires_human_review: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ShipmentTripDetailSummary:
    id: str
    shipment_request_id: str
    assignment_id: str
    carrier_id: str
    carrier_name: str | None
    carrier_phone: str | None
    driver_id: str | None
    vehicle_id: str | None
    vehicle_plate: str | None
    status: str
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    incident_notes: str | None
    closure_notes: str | None
    requires_human_review: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ShipmentEventTimelineItem:
    event_id: str
    event_type: str
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    entity_type: str
    entity_id: str
    summary: str
    previous_state: str | None
    new_state: str | None
    related_entity_ids: dict[str, str]
    source: str


@dataclass(frozen=True)
class ShipmentDetail:
    shipment: ShipmentDetailSummary
    offers: list[ShipmentOfferDetailSummary]
    active_assignment: ShipmentAssignmentDetailSummary | None
    assignments: list[ShipmentAssignmentDetailSummary]
    active_trip: ShipmentTripDetailSummary | None
    trips: list[ShipmentTripDetailSummary]
    events: list[ShipmentEventTimelineItem]


@dataclass(frozen=True)
class TripSummary:
    id: str
    status: str
    shipment_request_id: str
    carrier_id: str
    driver_id: str | None
    vehicle_id: str | None
    carrier_name: str | None
    origin: str | None
    destination: str | None
    planned_start_at: datetime | None
    updated_at: datetime
    test_run_id: str | None = None


@dataclass(frozen=True)
class PendingCarrierSummary:
    id: str
    name: str
    contact_phone: str | None
    phone: str | None
    email: str | None
    company_name: str | None
    cuit: str | None
    truck_count: int
    vehicles_count: int
    documents_count: int
    pending_documents_count: int
    created_at: datetime


@dataclass(frozen=True)
class CarrierDocumentSummary:
    id: str
    document_type: str
    has_file: bool
    provider: str | None
    provider_media_id: str | None
    mime_type: str | None
    file_name: str | None
    uploaded_by_phone: str | None
    status: str
    notes: str | None
    created_at: datetime
    uploaded_at: datetime


class BackofficeService:
    ACTIVE_ASSIGNMENT_STATES = {"PROPOSED", "PENDING_CONFIRMATION", "CONFIRMED"}
    ACTIVE_ASSIGNMENT_STATUS_PRIORITY = {
        "CONFIRMED": 3,
        "PENDING_CONFIRMATION": 2,
        "PROPOSED": 1,
    }
    UNASSIGNED_SHIPMENT_STATES = {"PUBLISHED", "MATCHING"}
    IN_PROGRESS_TRIP_STATES = {"LOADING_PENDING", "LOADING", "IN_TRANSIT"}
    COMPLETED_TRIP_STATES = {"COMPLETED", "DELIVERED"}
    CANCELLED_TRIP_STATES = {"CANCELLED"}
    FAILED_TRIP_STATES = {"FAILED"}
    ACTIVE_TRIP_STATUS_PRIORITY = {
        "IN_TRANSIT": 5,
        "LOADING": 4,
        "LOADING_PENDING": 3,
        "REMINDER_SENT": 2,
        "PLANNED": 1,
    }

    def __init__(
        self,
        *,
        conversation_sessions: ReadRepository[ConversationSession],
        messages: ReadRepository[Message],
        shipment_requests: MutationRepository[ShipmentRequest],
        trip_offers: MutationRepository[TripOffer],
        assignments: MutationRepository[Assignment],
        trips: MutationRepository[Trip],
        carriers: ReadRepository[Carrier],
        carrier_onboardings: ReadRepository[CarrierOnboarding],
        vehicles: ReadRepository[Vehicle],
        documents: ReadRepository[Document],
        locations: MutationRepository[Location],
        event_logs: EventLogRepository,
    ) -> None:
        self._conversation_sessions = conversation_sessions
        self._messages = messages
        self._shipment_requests = shipment_requests
        self._trip_offers = trip_offers
        self._assignments = assignments
        self._trips = trips
        self._carriers = carriers
        self._carrier_onboardings = carrier_onboardings
        self._vehicles = vehicles
        self._documents = documents
        self._locations = locations
        self._event_logs = event_logs

    def overview(self) -> BackofficeOverview:
        conversations = self._conversation_sessions.list()
        open_conversations = [item for item in conversations if item.status == "OPEN"]
        operator_conversation_ids = self._operator_conversation_ids()
        ambiguous_conversation_ids = self._ambiguous_conversation_ids()
        failed_notifications = sum(
            1 for event in self._event_logs.list() if event.event_type == "CARRIER_NOTIFICATION_FAILED"
        )

        shipments = self._shipment_requests.list()
        unassigned_shipments = self._unassigned_shipments()
        trips = self._trips.list()
        carriers = self._carriers.list()
        onboardings = self._carrier_onboardings.list()
        documents = self._documents.list()

        return BackofficeOverview(
            open_conversations=len(open_conversations),
            open_conversations_requiring_operator=sum(
                1 for item in open_conversations if item.id in operator_conversation_ids
            ),
            ambiguous_conversations=len(ambiguous_conversation_ids),
            failed_notifications=failed_notifications,
            total_shipments=len(shipments),
            published_shipments=sum(1 for item in shipments if item.status == "PUBLISHED"),
            shipments_in_matching=sum(1 for item in shipments if item.status == "MATCHING"),
            assigned_shipments=sum(1 for item in shipments if item.status == "ASSIGNED"),
            unassigned_published_shipments=len(unassigned_shipments),
            avg_unassigned_age_hours=self._average_age_hours(unassigned_shipments),
            total_trips=len(trips),
            planned_trips=sum(1 for item in trips if item.status == "PLANNED"),
            in_progress_trips=sum(1 for item in trips if item.status in self.IN_PROGRESS_TRIP_STATES),
            completed_trips=sum(1 for item in trips if item.status in self.COMPLETED_TRIP_STATES),
            cancelled_trips=sum(1 for item in trips if item.status in self.CANCELLED_TRIP_STATES),
            # TODO: the current Trip state machine has INCIDENT_REPORTED and CANCELLED,
            # but no explicit FAILED terminal state. Keep this to exact FAILED for now.
            failed_trips=sum(1 for item in trips if item.status in self.FAILED_TRIP_STATES),
            total_carriers=len(carriers),
            validated_carriers=sum(
                1 for item in carriers if self._effective_carrier_validation_status(item) == "APPROVED"
            ),
            pending_validation_carriers=sum(
                1 for item in carriers
                if self._effective_carrier_validation_status(item) not in {"APPROVED", "REJECTED", "SUSPENDED"}
            ),
            carrier_onboarding_pending_review=sum(
                1 for item in onboardings if item.status == "PENDING_REVIEW"
            ),
            carrier_documents_pending_review=sum(
                1
                for item in documents
                if item.entity_type.lower() == "carrier" and item.status == "PENDING"
            ),
            total_documents=len(documents),
            pending_documents=sum(1 for item in documents if item.status == "PENDING"),
            approved_documents=sum(1 for item in documents if item.status == "APPROVED"),
            rejected_documents=sum(1 for item in documents if item.status == "REJECTED"),
        )

    def list_open_conversations(
        self, *, limit: int = 20, offset: int = 0, needs_operator: bool | None = None,
        ambiguous_only: bool = False,
    ) -> list[OpenConversationSummary]:
        messages_by_conversation = self._messages_by_conversation()
        operator_conversation_ids = self._operator_conversation_ids()
        conversations = [item for item in self._conversation_sessions.list() if item.status == "OPEN"]
        if ambiguous_only:
            ambiguous_ids = self._ambiguous_conversation_ids()
            conversations = [item for item in conversations if item.id in ambiguous_ids]
        if needs_operator is not None:
            conversations = [item for item in conversations if (item.id in operator_conversation_ids) is needs_operator]
        conversations.sort(
            key=lambda item: self._conversation_last_activity(item, messages_by_conversation),
            reverse=True,
        )

        rows: list[OpenConversationSummary] = []
        for conversation in conversations[max(offset, 0) : max(offset, 0) + self._normalized_limit(limit)]:
            latest_message = self._latest_message(messages_by_conversation.get(conversation.id, []))
            related_entity_type, related_entity_id = self._related_entity_from_message(latest_message)
            rows.append(
                OpenConversationSummary(
                    id=conversation.id,
                    participant_phone=conversation.participant_phone
                    or conversation.normalized_phone_number,
                    channel=conversation.channel,
                    last_message_preview=self._preview(latest_message.raw_content if latest_message else None),
                    last_activity_at=self._conversation_last_activity(conversation, messages_by_conversation),
                    status=conversation.status,
                    needs_operator=conversation.id in operator_conversation_ids,
                    related_entity_type=related_entity_type,
                    related_entity_id=related_entity_id,
                )
            )
        return rows

    def list_open_conversation_page(
        self, *, limit: int = 25, offset: int = 0, needs_operator: bool | None = None,
        ambiguous_only: bool = False,
    ) -> OpenConversationPage:
        # Keep the existing list contract available while returning explicit paging
        # metadata to the backoffice UI.
        normalized_limit = self._normalized_limit(limit)
        normalized_offset = max(offset, 0)
        all_rows: list[OpenConversationSummary] = []
        batch_offset = 0
        while True:
            batch = self.list_open_conversations(
                limit=100, offset=batch_offset, needs_operator=needs_operator,
                ambiguous_only=ambiguous_only,
            )
            all_rows.extend(batch)
            if len(batch) < 100:
                break
            batch_offset += len(batch)
        return OpenConversationPage(
            items=all_rows[normalized_offset : normalized_offset + normalized_limit],
            total=len(all_rows),
            limit=normalized_limit,
            offset=normalized_offset,
        )

    def list_conversation_reply_failures(self, conversation_session_id: str) -> list[EventLog]:
        if self._conversation_sessions.get(conversation_session_id) is None:
            raise KeyError(conversation_session_id)
        return [
            event
            for event in self._event_logs.list()
            if event.entity_type == "ConversationSession"
            and event.entity_id == conversation_session_id
            and event.event_type == "CONVERSATION_REPLY_FAILED"
        ]

    def list_unassigned_shipments(self) -> list[UnassignedShipmentSummary]:
        locations = {item.id: item for item in self._locations.list()}
        offers_by_shipment = self._offers_by_shipment()
        rows: list[UnassignedShipmentSummary] = []
        for shipment in sorted(self._unassigned_shipments(), key=lambda item: item.created_at, reverse=True):
            offers = offers_by_shipment.get(shipment.id, [])
            rows.append(
                UnassignedShipmentSummary(
                    id=shipment.id,
                    origin=self._location_label(locations.get(shipment.origin_location_id or "")),
                    destination=self._location_label(locations.get(shipment.destination_location_id or "")),
                    cargo_category=shipment.cargo_category,
                    cargo_type=shipment.cargo_type,
                    quantity_unit=shipment.quantity_unit,
                    livestock_type=shipment.livestock_type,
                    quantity_estimate=shipment.quantity_estimate,
                    weight_per_head_kg=shipment.weight_per_head_kg,
                    status=shipment.status,
                    created_at=shipment.created_at,
                    age_hours=self._age_hours(shipment.created_at),
                    offers_count=len(offers),
                    interested_carriers_count=len(
                        {offer.carrier_id for offer in offers if offer.response_type == "INTERESTED"}
                    ),
                )
            )
        return rows

    def list_trips(self, *, status: str | None = None) -> list[TripSummary]:
        carriers = {item.id: item for item in self._carriers.list()}
        shipments = {item.id: item for item in self._shipment_requests.list()}
        locations = {item.id: item for item in self._locations.list()}
        normalized_status = status.upper() if status else None
        trips = [
            trip
            for trip in self._trips.list()
            if normalized_status is None or trip.status == normalized_status
        ]
        trips.sort(key=lambda item: item.updated_at, reverse=True)
        rows: list[TripSummary] = []
        for trip in trips:
            carrier = carriers.get(trip.carrier_id)
            shipment = shipments.get(trip.shipment_request_id)
            rows.append(
                TripSummary(
                    id=trip.id,
                    test_run_id=trip.test_run_id,
                    status=trip.status,
                    shipment_request_id=trip.shipment_request_id,
                    carrier_id=trip.carrier_id,
                    driver_id=trip.driver_id,
                    vehicle_id=trip.vehicle_id,
                    carrier_name=carrier.name if carrier else None,
                    origin=self._location_label(
                        locations.get(shipment.origin_location_id or "") if shipment else None
                    ),
                    destination=self._location_label(
                        locations.get(shipment.destination_location_id or "") if shipment else None
                    ),
                    planned_start_at=trip.planned_start_at,
                    updated_at=trip.updated_at,
                )
            )
        return rows

    def get_shipment_detail(self, shipment_id: str) -> ShipmentDetail:
        shipment = self._shipment_requests.get(shipment_id)
        if shipment is None:
            raise KeyError(shipment_id)

        locations = {item.id: item for item in self._locations.list()}
        carriers = {item.id: item for item in self._carriers.list()}
        vehicles = {item.id: item for item in self._vehicles.list()}
        messages = {item.id: item for item in self._messages.list()}

        offers = [
            offer for offer in self._trip_offers.list() if offer.shipment_request_id == shipment_id
        ]
        offers.sort(key=lambda item: (item.created_at, item.updated_at), reverse=True)

        assignments = [
            assignment
            for assignment in self._assignments.list()
            if assignment.shipment_request_id == shipment_id
        ]
        assignments.sort(key=self._assignment_sort_key, reverse=True)

        trips = [trip for trip in self._trips.list() if trip.shipment_request_id == shipment_id]
        trips.sort(key=self._trip_sort_key, reverse=True)

        active_assignment = next(
            (assignment for assignment in assignments if assignment.status in self.ACTIVE_ASSIGNMENT_STATES),
            assignments[0] if assignments else None,
        )
        active_trip = next(
            (
                trip
                for trip in trips
                if trip.status in self.ACTIVE_TRIP_STATUS_PRIORITY or trip.status in {"PLANNED", "REMINDER_SENT"}
            ),
            trips[0] if trips else None,
        )

        return ShipmentDetail(
            shipment=ShipmentDetailSummary(
                id=shipment.id,
                test_run_id=shipment.test_run_id,
                status=shipment.status,
                producer_phone_number=shipment.producer_phone_number,
                origin=self._location_label(locations.get(shipment.origin_location_id or "")),
                destination=self._location_label(locations.get(shipment.destination_location_id or "")),
                cargo_category=shipment.cargo_category,
                cargo_type=shipment.cargo_type,
                quantity_unit=shipment.quantity_unit,
                livestock_type=shipment.livestock_type,
                quantity_estimate=shipment.quantity_estimate,
                weight_per_head_kg=shipment.weight_per_head_kg,
                operational_notes=shipment.operational_notes,
                date_window_start=shipment.date_window_start,
                date_window_end=shipment.date_window_end,
                source_message_id=shipment.source_message_id,
                source_message_preview=self._message_preview(messages.get(shipment.source_message_id or "")),
                requires_human_review=shipment.requires_human_review,
                has_ambiguous_location=shipment.has_ambiguous_location,
                has_estimated_values=shipment.has_estimated_values,
                missing_critical_fields=list(shipment.missing_critical_fields),
                field_confidence=dict(shipment.field_confidence),
                created_at=shipment.created_at,
                updated_at=shipment.updated_at,
            ),
            offers=[
                ShipmentOfferDetailSummary(
                    id=offer.id,
                    carrier_id=offer.carrier_id,
                    carrier_name=carriers.get(offer.carrier_id).name if carriers.get(offer.carrier_id) else None,
                    carrier_phone=self._carrier_phone(carriers.get(offer.carrier_id)),
                    vehicle_id=offer.vehicle_id,
                    vehicle_plate=self._vehicle_plate(vehicles.get(offer.vehicle_id or "")),
                    response_type=offer.response_type,
                    status=offer.status,
                    price_estimate=offer.price_estimate,
                    availability_window_start=offer.availability_window_start,
                    availability_window_end=offer.availability_window_end,
                    confidence=offer.confidence,
                    requires_human_review=offer.requires_human_review,
                    source_message_id=offer.source_message_id,
                    source_message_preview=self._message_preview(messages.get(offer.source_message_id or "")),
                    created_at=offer.created_at,
                    updated_at=offer.updated_at,
                )
                for offer in offers
            ],
            active_assignment=self._assignment_detail(active_assignment, carriers, vehicles),
            assignments=[
                self._assignment_detail(assignment, carriers, vehicles)
                for assignment in assignments
            ],
            active_trip=self._trip_detail(active_trip, carriers, vehicles),
            trips=[self._trip_detail(trip, carriers, vehicles) for trip in trips],
            events=self._shipment_timeline_events(
                shipment_id=shipment.id,
                offer_ids={offer.id for offer in offers},
                assignment_ids={assignment.id for assignment in assignments},
                trip_ids={trip.id for trip in trips},
            ),
        )

    def update_shipment(
        self,
        shipment_id: str,
        data: ShipmentMutationInput,
        *,
        operator_user_id: str,
    ) -> ShipmentDetail:
        shipment = self._shipment_requests.get(shipment_id)
        if shipment is None:
            raise KeyError(shipment_id)

        cargo_category = None
        if data.cargo_category is not None:
            cargo_category = normalize_cargo_category(data.cargo_category)
            if data.cargo_category.strip() and cargo_category is None:
                raise ValueError("cargo_category must be LIVESTOCK or GRAIN")
        quantity_unit = None
        if data.quantity_unit is not None:
            quantity_unit = normalize_quantity_unit(data.quantity_unit)
            if data.quantity_unit.strip() and quantity_unit is None:
                raise ValueError("quantity_unit must be HEAD, TON, KG, or TRUCKLOAD")

        previous = self._shipment_payload(shipment)
        previous_status = shipment.status
        if data.status is not None:
            shipment.status = data.status.strip().upper()
        if data.producer_phone_number is not None:
            shipment.producer_phone_number = self._blank_to_none(data.producer_phone_number)
        if data.origin is not None:
            shipment.origin_location_id = self._operator_location_id(data.origin)
        if data.destination is not None:
            shipment.destination_location_id = self._operator_location_id(data.destination)
        if data.cargo_category is not None:
            shipment.cargo_category = cargo_category
        if data.cargo_type is not None:
            shipment.cargo_type = self._blank_to_none(data.cargo_type)
        if data.quantity_unit is not None:
            shipment.quantity_unit = quantity_unit
        if data.livestock_type is not None:
            shipment.livestock_type = self._blank_to_none(data.livestock_type)
        if data.quantity_estimate is not None:
            shipment.quantity_estimate = data.quantity_estimate
        if data.weight_per_head_kg is not None:
            shipment.weight_per_head_kg = data.weight_per_head_kg
        if data.operational_notes is not None:
            shipment.operational_notes = self._blank_to_none(data.operational_notes)
        if data.date_window_start is not None:
            shipment.date_window_start = data.date_window_start
        if data.date_window_end is not None:
            shipment.date_window_end = data.date_window_end
        if data.requires_human_review is not None:
            shipment.requires_human_review = data.requires_human_review
        if data.has_ambiguous_location is not None:
            shipment.has_ambiguous_location = data.has_ambiguous_location
        if data.has_estimated_values is not None:
            shipment.has_estimated_values = data.has_estimated_values

        self._shipment_requests.save(shipment)
        self._event_logs.record(
            event_type="LOAD_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            previous_state=previous_status,
            new_state=shipment.status,
            summary="Carga editada desde backoffice",
            related_entity_ids={"loadId": shipment.id},
            payload={"previous": previous, "current": self._shipment_payload(shipment)},
            source="backoffice",
        )
        return self.get_shipment_detail(shipment.id)

    def delete_shipment(self, shipment_id: str, *, operator_user_id: str) -> None:
        shipment = self._shipment_requests.get(shipment_id)
        if shipment is None:
            raise KeyError(shipment_id)

        related = self._operation_related_entities(shipment.id)
        self._soft_delete_operation(related)
        if shipment.deleted_at is None:
            self._shipment_requests.soft_delete(shipment.id)
        self._event_logs.record(
            event_type="LOAD_ADMIN_DELETED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            previous_state=shipment.status,
            new_state="DELETED",
            summary="Carga dada de baja administrativa desde backoffice",
            related_entity_ids={"loadId": shipment.id},
            payload={
                "soft_deleted": True,
                "operation_deleted": True,
                "trip_ids": [trip.id for trip in related["trips"]],
                "assignment_ids": [assignment.id for assignment in related["assignments"]],
                "trip_offer_ids": [offer.id for offer in related["offers"]],
            },
            source="backoffice",
        )

    def update_trip(
        self,
        trip_id: str,
        data: TripMutationInput,
        *,
        operator_user_id: str,
    ) -> TripSummary:
        trip = self._trips.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)

        previous = self._trip_payload(trip)
        previous_status = trip.status
        if data.status is not None:
            requested_status = data.status.strip().upper()
            if requested_status != trip.status:
                raise ValueError("Use the dedicated trip action endpoint to change status")
        if data.planned_start_at is not None:
            trip.planned_start_at = data.planned_start_at
        if data.planned_end_at is not None:
            trip.planned_end_at = data.planned_end_at
        if data.started_at is not None:
            trip.started_at = data.started_at
        if data.completed_at is not None:
            trip.completed_at = data.completed_at
        if data.cancelled_at is not None:
            trip.cancelled_at = data.cancelled_at
        if data.incident_notes is not None:
            trip.incident_notes = self._blank_to_none(data.incident_notes)
        if data.closure_notes is not None:
            trip.closure_notes = self._blank_to_none(data.closure_notes)
        if data.requires_human_review is not None:
            trip.requires_human_review = data.requires_human_review

        self._trips.save(trip)
        self._event_logs.record(
            event_type="TRIP_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Trip",
            entity_id=trip.id,
            previous_state=previous_status,
            new_state=trip.status,
            summary="Viaje editado desde backoffice",
            related_entity_ids={
                "loadId": trip.shipment_request_id,
                "assignmentId": trip.assignment_id,
                "tripId": trip.id,
            },
            payload={"previous": previous, "current": self._trip_payload(trip)},
            source="backoffice",
        )
        return next(item for item in self.list_trips() if item.id == trip.id)

    def delete_trip(self, trip_id: str, *, operator_user_id: str) -> None:
        trip = self._trips.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)

        shipment = self._shipment_requests.get(trip.shipment_request_id)
        if shipment is None:
            raise KeyError(trip.shipment_request_id)

        related = self._operation_related_entities(shipment.id)
        self._soft_delete_operation(related)
        if shipment.deleted_at is None:
            self._shipment_requests.soft_delete(shipment.id)
        self._event_logs.record(
            event_type="TRIP_ADMIN_DELETED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Trip",
            entity_id=trip.id,
            previous_state=trip.status,
            new_state="DELETED",
            summary="Viaje dado de baja administrativa desde backoffice",
            related_entity_ids={
                "loadId": trip.shipment_request_id,
                "assignmentId": trip.assignment_id,
                "tripId": trip.id,
            },
            payload={
                "soft_deleted": True,
                "operation_deleted": True,
                "previous": self._trip_payload(trip),
                "shipment_request_id": shipment.id,
                "trip_ids": [related_trip.id for related_trip in related["trips"]],
                "assignment_ids": [assignment.id for assignment in related["assignments"]],
                "trip_offer_ids": [offer.id for offer in related["offers"]],
            },
            source="backoffice",
        )
        self._event_logs.record(
            event_type="LOAD_ADMIN_DELETED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            previous_state=shipment.status,
            new_state="DELETED",
            summary="Carga dada de baja administrativa por borrado de viaje desde backoffice",
            related_entity_ids={
                "loadId": shipment.id,
                "assignmentId": trip.assignment_id,
                "tripId": trip.id,
            },
            payload={
                "soft_deleted": True,
                "operation_deleted": True,
                "trigger": "trip_deleted",
                "trip_ids": [related_trip.id for related_trip in related["trips"]],
                "assignment_ids": [assignment.id for assignment in related["assignments"]],
                "trip_offer_ids": [offer.id for offer in related["offers"]],
            },
            source="backoffice",
        )

    def list_pending_carriers(self) -> list[PendingCarrierSummary]:
        vehicles_by_carrier = self._vehicles_by_carrier()
        documents_by_carrier = self._documents_by_carrier()
        carriers = [carrier for carrier in self._carriers.list() if not carrier.is_validated]
        carriers.sort(key=lambda item: item.created_at, reverse=True)
        return [
            PendingCarrierSummary(
                id=carrier.id,
                name=carrier.name,
                contact_phone=carrier.contact_phone,
                phone=carrier.normalized_phone_number or carrier.contact_phone,
                email=carrier.email,
                company_name=carrier.company_name,
                cuit=carrier.cuit,
                truck_count=carrier.truck_count or len(vehicles_by_carrier.get(carrier.id, [])),
                vehicles_count=len(vehicles_by_carrier.get(carrier.id, [])),
                documents_count=len(documents_by_carrier.get(carrier.id, [])),
                pending_documents_count=sum(
                    1
                    for document in documents_by_carrier.get(carrier.id, [])
                    if document.status == "PENDING"
                ),
                created_at=carrier.created_at,
            )
            for carrier in carriers
        ]

    def list_carrier_documents(self, carrier_id: str) -> list[CarrierDocumentSummary]:
        if self._carriers.get(carrier_id) is None:
            raise KeyError(carrier_id)
        documents = [
            document
            for document in self._documents.list()
            if self._is_carrier_document(document, carrier_id)
        ]
        documents.sort(key=lambda item: item.created_at, reverse=True)
        return [
            CarrierDocumentSummary(
                id=document.id,
                document_type=document.document_type,
                has_file=bool(document.storage_uri),
                provider=document.provider,
                provider_media_id=document.provider_media_id,
                mime_type=document.mime_type,
                file_name=document.file_name,
                uploaded_by_phone=document.uploaded_by_phone,
                status=document.status,
                notes=document.notes,
                created_at=document.created_at,
                uploaded_at=document.created_at,
            )
            for document in documents
        ]

    def _unassigned_shipments(self) -> list[ShipmentRequest]:
        active_assignment_shipment_ids = {
            assignment.shipment_request_id
            for assignment in self._assignments.list()
            if assignment.status in self.ACTIVE_ASSIGNMENT_STATES
        }
        return [
            shipment
            for shipment in self._shipment_requests.list()
            if shipment.status in self.UNASSIGNED_SHIPMENT_STATES
            and shipment.id not in active_assignment_shipment_ids
        ]

    def _operator_conversation_ids(self) -> set[str]:
        conversation_ids: set[str] = set()
        for event in self._event_logs.list():
            if event.event_type not in {"HUMAN_REVIEW_REQUESTED", "CARRIER_RESPONSE_AMBIGUOUS"}:
                continue
            conversation_id = event.related_entity_ids.get("conversationSessionId")
            if conversation_id:
                conversation_ids.add(conversation_id)
        return conversation_ids

    def _ambiguous_conversation_ids(self) -> set[str]:
        conversation_ids: set[str] = set()
        for event in self._event_logs.list():
            if event.event_type != "CARRIER_RESPONSE_AMBIGUOUS":
                continue
            conversation_id = event.related_entity_ids.get("conversationSessionId")
            if conversation_id:
                conversation_ids.add(conversation_id)
        return conversation_ids

    def _messages_by_conversation(self) -> dict[str, list[Message]]:
        rows: dict[str, list[Message]] = {}
        for message in self._messages.list():
            rows.setdefault(message.conversation_session_id, []).append(message)
        return rows

    def _offers_by_shipment(self) -> dict[str, list[TripOffer]]:
        rows: dict[str, list[TripOffer]] = {}
        for offer in self._trip_offers.list():
            rows.setdefault(offer.shipment_request_id, []).append(offer)
        return rows

    def _vehicles_by_carrier(self) -> dict[str, list[Vehicle]]:
        rows: dict[str, list[Vehicle]] = {}
        for vehicle in self._vehicles.list():
            rows.setdefault(vehicle.carrier_id, []).append(vehicle)
        return rows

    def _documents_by_carrier(self) -> dict[str, list[Document]]:
        rows: dict[str, list[Document]] = {}
        for document in self._documents.list():
            if document.entity_type.lower() != "carrier":
                continue
            rows.setdefault(document.entity_id, []).append(document)
        return rows

    def _operation_related_entities(self, shipment_id: str) -> dict[str, list[Trip] | list[Assignment] | list[TripOffer]]:
        assignments = [
            assignment
            for assignment in self._assignments.list(include_deleted=True)
            if assignment.shipment_request_id == shipment_id
        ]
        trips = [
            trip
            for trip in self._trips.list(include_deleted=True)
            if trip.shipment_request_id == shipment_id
        ]
        offers = [
            offer
            for offer in self._trip_offers.list(include_deleted=True)
            if offer.shipment_request_id == shipment_id
        ]
        return {"assignments": assignments, "trips": trips, "offers": offers}

    def _soft_delete_operation(
        self,
        related: dict[str, list[Trip] | list[Assignment] | list[TripOffer]],
    ) -> None:
        for trip in related["trips"]:
            if trip.deleted_at is None:
                self._trips.soft_delete(trip.id)
        for assignment in related["assignments"]:
            if assignment.deleted_at is None:
                self._assignments.soft_delete(assignment.id)
        for offer in related["offers"]:
            if offer.deleted_at is None:
                self._trip_offers.soft_delete(offer.id)

    def _operator_location_id(self, value: str) -> str | None:
        clean = self._blank_to_none(value)
        if clean is None:
            return None
        location = Location(
            original_text=clean,
            normalized_name=clean,
            confidence="operator_verified",
            is_validated=True,
        )
        self._locations.add(location)
        return location.id

    @staticmethod
    def _blank_to_none(value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None

    def _shipment_payload(self, shipment: ShipmentRequest) -> dict[str, object]:
        locations = {item.id: item for item in self._locations.list()}
        return {
            "status": shipment.status,
            "producer_phone_number": shipment.producer_phone_number,
            "origin": self._location_label(locations.get(shipment.origin_location_id or "")),
            "destination": self._location_label(locations.get(shipment.destination_location_id or "")),
            "cargo_category": shipment.cargo_category,
            "cargo_type": shipment.cargo_type,
            "quantity_unit": shipment.quantity_unit,
            "livestock_type": shipment.livestock_type,
            "quantity_estimate": str(shipment.quantity_estimate) if shipment.quantity_estimate is not None else None,
            "weight_per_head_kg": str(shipment.weight_per_head_kg)
            if shipment.weight_per_head_kg is not None
            else None,
            "operational_notes": shipment.operational_notes,
            "date_window_start": shipment.date_window_start.isoformat() if shipment.date_window_start else None,
            "date_window_end": shipment.date_window_end.isoformat() if shipment.date_window_end else None,
            "requires_human_review": shipment.requires_human_review,
            "has_ambiguous_location": shipment.has_ambiguous_location,
            "has_estimated_values": shipment.has_estimated_values,
        }

    @staticmethod
    def _trip_payload(trip: Trip) -> dict[str, object]:
        return {
            "status": trip.status,
            "planned_start_at": trip.planned_start_at.isoformat() if trip.planned_start_at else None,
            "planned_end_at": trip.planned_end_at.isoformat() if trip.planned_end_at else None,
            "started_at": trip.started_at.isoformat() if trip.started_at else None,
            "completed_at": trip.completed_at.isoformat() if trip.completed_at else None,
            "cancelled_at": trip.cancelled_at.isoformat() if trip.cancelled_at else None,
            "incident_notes": trip.incident_notes,
            "closure_notes": trip.closure_notes,
            "requires_human_review": trip.requires_human_review,
        }

    def _conversation_last_activity(
        self,
        conversation: ConversationSession,
        messages_by_conversation: dict[str, list[Message]],
    ) -> datetime:
        candidates = [
            conversation.last_message_at,
            conversation.last_inbound_at,
            conversation.last_outbound_at,
            conversation.updated_at,
            conversation.created_at,
        ]
        latest_message = self._latest_message(messages_by_conversation.get(conversation.id, []))
        if latest_message is not None:
            candidates.extend(
                [
                    latest_message.received_at,
                    latest_message.sent_at,
                    latest_message.updated_at,
                    latest_message.created_at,
                ]
            )
        return max(item for item in candidates if item is not None)

    def _latest_message(self, messages: list[Message]) -> Message | None:
        if not messages:
            return None
        return max(
            messages,
            key=lambda item: item.received_at or item.sent_at or item.updated_at or item.created_at,
        )

    def _related_entity_from_message(self, message: Message | None) -> tuple[str | None, str | None]:
        if message is None:
            return None, None
        for entity_type, key in (
            ("ShipmentRequest", "loadId"),
            ("ShipmentRequest", "shipmentRequestId"),
            ("TripOffer", "tripOfferId"),
            ("Assignment", "assignmentId"),
            ("Trip", "tripId"),
            ("Carrier", "carrierId"),
        ):
            if key in message.related_entity_ids:
                return entity_type, message.related_entity_ids[key]
        return None, None

    def _is_carrier_document(self, document: Document, carrier_id: str) -> bool:
        return document.entity_type.lower() == "carrier" and document.entity_id == carrier_id

    def _assignment_detail(
        self,
        assignment: Assignment | None,
        carriers: dict[str, Carrier],
        vehicles: dict[str, Vehicle],
    ) -> ShipmentAssignmentDetailSummary | None:
        if assignment is None:
            return None
        carrier = carriers.get(assignment.carrier_id)
        vehicle = vehicles.get(assignment.vehicle_id or "")
        return ShipmentAssignmentDetailSummary(
            id=assignment.id,
            shipment_request_id=assignment.shipment_request_id,
            carrier_id=assignment.carrier_id,
            carrier_name=carrier.name if carrier else None,
            carrier_phone=self._carrier_phone(carrier),
            vehicle_id=assignment.vehicle_id,
            vehicle_plate=self._vehicle_plate(vehicle),
            trip_offer_id=assignment.trip_offer_id,
            status=assignment.status,
            selected_by_user_id=assignment.selected_by_user_id,
            confirmed_by_user_id=assignment.confirmed_by_user_id,
            confirmed_at=assignment.confirmed_at,
            confirmation_notes=assignment.confirmation_notes,
            requires_human_review=assignment.requires_human_review,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )

    def _trip_detail(
        self,
        trip: Trip | None,
        carriers: dict[str, Carrier],
        vehicles: dict[str, Vehicle],
    ) -> ShipmentTripDetailSummary | None:
        if trip is None:
            return None
        carrier = carriers.get(trip.carrier_id)
        vehicle = vehicles.get(trip.vehicle_id or "")
        return ShipmentTripDetailSummary(
            id=trip.id,
            shipment_request_id=trip.shipment_request_id,
            assignment_id=trip.assignment_id,
            carrier_id=trip.carrier_id,
            carrier_name=carrier.name if carrier else None,
            carrier_phone=self._carrier_phone(carrier),
            driver_id=trip.driver_id,
            vehicle_id=trip.vehicle_id,
            vehicle_plate=self._vehicle_plate(vehicle),
            status=trip.status,
            planned_start_at=trip.planned_start_at,
            planned_end_at=trip.planned_end_at,
            started_at=trip.started_at,
            completed_at=trip.completed_at,
            cancelled_at=trip.cancelled_at,
            incident_notes=trip.incident_notes,
            closure_notes=trip.closure_notes,
            requires_human_review=trip.requires_human_review,
            created_at=trip.created_at,
            updated_at=trip.updated_at,
        )

    def _shipment_timeline_events(
        self,
        *,
        shipment_id: str,
        offer_ids: set[str],
        assignment_ids: set[str],
        trip_ids: set[str],
    ) -> list[ShipmentEventTimelineItem]:
        rows: dict[str, ShipmentEventTimelineItem] = {}
        for event in self._event_logs.list():
            if not self._event_belongs_to_shipment(
                event,
                shipment_id=shipment_id,
                offer_ids=offer_ids,
                assignment_ids=assignment_ids,
                trip_ids=trip_ids,
            ):
                continue
            rows[event.event_id] = ShipmentEventTimelineItem(
                event_id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                summary=event.summary,
                previous_state=event.previous_state,
                new_state=event.new_state,
                related_entity_ids=dict(event.related_entity_ids),
                source=event.source,
            )
        return sorted(rows.values(), key=lambda item: item.occurred_at, reverse=True)

    def _event_belongs_to_shipment(
        self,
        event: EventLog,
        *,
        shipment_id: str,
        offer_ids: set[str],
        assignment_ids: set[str],
        trip_ids: set[str],
    ) -> bool:
        if event.entity_type == "ShipmentRequest" and event.entity_id == shipment_id:
            return True
        if event.entity_type == "TripOffer" and event.entity_id in offer_ids:
            return True
        if event.entity_type == "Assignment" and event.entity_id in assignment_ids:
            return True
        if event.entity_type == "Trip" and event.entity_id in trip_ids:
            return True
        related_ids = event.related_entity_ids
        if related_ids.get("loadId") == shipment_id or related_ids.get("shipmentRequestId") == shipment_id:
            return True
        if related_ids.get("tripOfferId") in offer_ids:
            return True
        if related_ids.get("assignmentId") in assignment_ids:
            return True
        if related_ids.get("tripId") in trip_ids:
            return True
        return False

    def _assignment_sort_key(self, assignment: Assignment) -> tuple[int, datetime, datetime]:
        return (
            self.ACTIVE_ASSIGNMENT_STATUS_PRIORITY.get(assignment.status, 0),
            assignment.updated_at,
            assignment.created_at,
        )

    def _trip_sort_key(self, trip: Trip) -> tuple[int, datetime, datetime]:
        return (
            self.ACTIVE_TRIP_STATUS_PRIORITY.get(trip.status, 0),
            trip.updated_at,
            trip.created_at,
        )

    def _carrier_phone(self, carrier: Carrier | None) -> str | None:
        if carrier is None:
            return None
        return carrier.normalized_phone_number or carrier.contact_phone

    def _vehicle_plate(self, vehicle: Vehicle | None) -> str | None:
        if vehicle is None:
            return None
        return vehicle.plate

    def _message_preview(self, message: Message | None) -> str | None:
        if message is None:
            return None
        return self._preview(message.raw_content or message.normalized_content)

    def _average_age_hours(self, shipments: list[ShipmentRequest]) -> float:
        if not shipments:
            return 0.0
        total_age = sum(self._age_hours(shipment.created_at) for shipment in shipments)
        return round(total_age / len(shipments), 2)

    def _age_hours(self, created_at: datetime) -> float:
        return round((utc_now() - self._as_utc(created_at)).total_seconds() / 3600, 2)

    def _as_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _location_label(self, location: Location | None) -> str | None:
        if location is None:
            return None
        return (
            location.normalized_name
            or location.locality
            or location.rural_reference
            or location.original_text
        )

    def _preview(self, raw_content: str | None) -> str | None:
        if not raw_content:
            return None
        text = " ".join(raw_content.split())
        return text if len(text) <= 120 else f"{text[:117]}..."

    def _normalized_limit(self, limit: int) -> int:
        return max(1, min(limit, 100))

    def _effective_carrier_validation_status(self, carrier: Carrier) -> str:
        if carrier.is_validated:
            return "APPROVED"
        return carrier.validation_status or "DRAFT"
