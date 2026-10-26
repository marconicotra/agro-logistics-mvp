"""Read-only producer views for the operator backoffice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TypeVar

from app.domain.events import EventLog
from app.domain.models import (
    Assignment,
    ConversationSession,
    Location,
    Message,
    Producer,
    ShipmentRequest,
    Trip,
    TripOffer,
)


T = TypeVar("T")


class ReadRepository(Protocol[T]):
    def get(self, entity_id: str) -> T | None: ...

    def list(self, *, include_deleted: bool = False) -> list[T]: ...


@dataclass(frozen=True)
class ProducerListItem:
    id: str
    name: str
    phone: str | None
    is_validated: bool
    usual_location_id: str | None
    last_activity_at: datetime | None
    shipments_count: int
    active_shipments_count: int
    trips_count: int
    conversations_count: int


@dataclass(frozen=True)
class ProducerShipmentItem:
    id: str
    status: str
    origin: str | None
    destination: str | None
    cargo_category: str | None
    cargo_type: str | None
    quantity_estimate: Any
    weight_per_head_kg: Any
    quantity_unit: str | None
    date_window_start: datetime | None
    date_window_end: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ProducerOfferItem:
    id: str
    shipment_request_id: str
    carrier_id: str
    status: str
    response_type: str
    created_at: datetime


@dataclass(frozen=True)
class ProducerTripItem:
    id: str
    shipment_request_id: str
    carrier_id: str
    status: str
    planned_start_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ProducerEventItem:
    id: str
    event_type: str
    occurred_at: datetime
    actor_type: str
    summary: str
    entity_type: str
    entity_id: str


@dataclass(frozen=True)
class ProducerDetail:
    producer: ProducerListItem
    email: str | None
    trust_notes: str | None
    validated_at: datetime | None
    shipments: list[ProducerShipmentItem]
    offers: list[ProducerOfferItem]
    trips: list[ProducerTripItem]
    conversation_ids: list[str]
    events: list[ProducerEventItem]


class ProducerBackofficeService:
    """Aggregates persisted producer data without inferring a profile."""

    ACTIVE_SHIPMENT_STATES = {"PUBLISHED", "MATCHING"}
    def __init__(
        self,
        *,
        producers: ReadRepository[Producer],
        shipments: ReadRepository[ShipmentRequest],
        offers: ReadRepository[TripOffer],
        assignments: ReadRepository[Assignment],
        trips: ReadRepository[Trip],
        conversations: ReadRepository[ConversationSession],
        messages: ReadRepository[Message],
        locations: ReadRepository[Location],
        events: ReadRepository[EventLog],
    ) -> None:
        self._producers = producers
        self._shipments = shipments
        self._offers = offers
        self._assignments = assignments
        self._trips = trips
        self._conversations = conversations
        self._messages = messages
        self._locations = locations
        self._events = events

    def list_producers(self, *, search: str | None = None, limit: int = 50, offset: int = 0) -> list[ProducerListItem]:
        producers = self._producers.list()
        search_value = (search or "").strip().casefold()
        rows = [
            producer
            for producer in producers
            if not search_value
            or search_value
            in " ".join(
                value or ""
                for value in (
                    producer.name,
                    producer.contact_phone,
                    producer.normalized_phone_number,
                )
            ).casefold()
        ]
        rows.sort(key=lambda producer: producer.updated_at, reverse=True)
        return [
            self._list_item(producer)
            for producer in rows[offset : offset + limit]
        ]

    def get_producer(self, producer_id: str) -> ProducerDetail:
        producer = self._producers.get(producer_id)
        if producer is None:
            raise KeyError(producer_id)
        shipments = self._producer_shipments(producer)
        shipment_ids = {shipment.id for shipment in shipments}
        offers = [offer for offer in self._offers.list() if offer.shipment_request_id in shipment_ids]
        assignments = [
            assignment
            for assignment in self._assignments.list()
            if assignment.shipment_request_id in shipment_ids
        ]
        assignment_ids = {assignment.id for assignment in assignments}
        trips = [trip for trip in self._trips.list() if trip.assignment_id in assignment_ids]
        conversations = self._producer_conversations(producer)
        conversation_ids = {conversation.id for conversation in conversations}
        events = [
            event
            for event in self._events.list()
            if event.entity_id in shipment_ids
            or event.related_entity_ids.get("loadId") in shipment_ids
            or event.related_entity_ids.get("producerId") == producer.id
            or event.related_entity_ids.get("producer_id") == producer.id
        ]
        events.sort(key=lambda event: event.occurred_at, reverse=True)
        item = self._list_item(producer)
        return ProducerDetail(
            producer=item,
            email=None,
            trust_notes=producer.trust_notes,
            validated_at=producer.validated_at,
            shipments=[
                ProducerShipmentItem(
                    id=shipment.id,
                    status=shipment.status,
                    origin=self._location_text(shipment.origin_location_id),
                    destination=self._location_text(shipment.destination_location_id),
                    cargo_category=shipment.cargo_category,
                    cargo_type=shipment.cargo_type or shipment.livestock_type,
                    quantity_estimate=shipment.quantity_estimate,
                    weight_per_head_kg=shipment.weight_per_head_kg,
                    quantity_unit=shipment.quantity_unit,
                    date_window_start=shipment.date_window_start,
                    date_window_end=shipment.date_window_end,
                    created_at=shipment.created_at,
                )
                for shipment in sorted(shipments, key=lambda item: item.created_at, reverse=True)
            ],
            offers=[
                ProducerOfferItem(
                    id=offer.id,
                    shipment_request_id=offer.shipment_request_id,
                    carrier_id=offer.carrier_id,
                    status=offer.status,
                    response_type=offer.response_type,
                    created_at=offer.created_at,
                )
                for offer in sorted(offers, key=lambda item: item.created_at, reverse=True)
            ],
            trips=[
                ProducerTripItem(
                    id=trip.id,
                    shipment_request_id=trip.shipment_request_id,
                    carrier_id=trip.carrier_id,
                    status=trip.status,
                    planned_start_at=trip.planned_start_at,
                    created_at=trip.created_at,
                )
                for trip in sorted(trips, key=lambda item: item.created_at, reverse=True)
            ],
            conversation_ids=sorted(conversation_ids),
            events=[
                ProducerEventItem(
                    id=event.event_id,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    actor_type=event.actor_type,
                    summary=event.summary,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                )
                for event in events
            ],
        )

    def _producer_shipments(self, producer: Producer) -> list[ShipmentRequest]:
        phone = producer.normalized_phone_number or producer.contact_phone
        if not phone:
            return []
        return [
            shipment
            for shipment in self._shipments.list()
            if shipment.producer_id == producer.id or (phone and shipment.producer_phone_number == phone)
        ]

    def _producer_conversations(self, producer: Producer) -> list[ConversationSession]:
        phone = producer.normalized_phone_number or producer.contact_phone
        return [
            conversation
            for conversation in self._conversations.list()
            if (producer.user_id and conversation.participant_user_id == producer.user_id)
            or (phone and (conversation.normalized_phone_number == phone or conversation.participant_phone == phone))
            if not conversation.active_test_run_id or conversation.role_override in {None, "Producer"}
        ]

    def _list_item(self, producer: Producer) -> ProducerListItem:
        related_shipments = self._producer_shipments(producer)
        related_conversations = self._producer_conversations(producer)
        conversation_ids = {conversation.id for conversation in related_conversations}
        last_message = max(
            (
                message.received_at or message.sent_at or message.created_at
                for message in self._messages.list()
                if message.conversation_session_id in conversation_ids
            ),
            default=None,
        )
        activity = [producer.updated_at]
        if last_message is not None:
            activity.append(last_message)
        return ProducerListItem(
            id=producer.id,
            name=producer.name,
            phone=producer.normalized_phone_number or producer.contact_phone,
            is_validated=producer.is_validated,
            usual_location_id=producer.usual_location_id,
            last_activity_at=max(activity),
            shipments_count=len(related_shipments),
            active_shipments_count=sum(1 for shipment in related_shipments if shipment.status in self.ACTIVE_SHIPMENT_STATES),
            trips_count=sum(
                1
                for trip in self._trips.list()
                if trip.shipment_request_id in {shipment.id for shipment in related_shipments}
            ),
            conversations_count=len(related_conversations),
        )

    def _location_text(self, location_id: str | None) -> str | None:
        if not location_id:
            return None
        location = self._locations.get(location_id)
        if location is None:
            return None
        return location.normalized_name or location.locality or location.original_text
