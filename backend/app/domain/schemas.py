from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ShipmentRequestCreate(BaseModel):
    producer_id: str | None = None
    producer_phone_number: str | None = None
    origin_location_id: str | None = None
    destination_location_id: str | None = None
    date_window_start: datetime | None = None
    date_window_end: datetime | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    source_message_id: str | None = None


class ShipmentRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    producer_id: str | None = None
    producer_phone_number: str | None = None
    missing_critical_fields: list[str]
    requires_human_review: bool


class TripOfferCreate(BaseModel):
    shipment_request_id: str
    carrier_id: str
    response_type: str
    vehicle_id: str | None = None
    source_message_id: str | None = None
    price_estimate: Decimal | None = None


class TripOfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_request_id: str
    carrier_id: str
    response_type: str
    status: str
    requires_human_review: bool


class AssignmentCreate(BaseModel):
    shipment_request_id: str
    carrier_id: str
    selected_by_user_id: str
    trip_offer_id: str | None = None
    vehicle_id: str | None = None


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_request_id: str
    carrier_id: str
    status: str
    selected_by_user_id: str


class TripCreate(BaseModel):
    shipment_request_id: str
    assignment_id: str
    carrier_id: str
    vehicle_id: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None


class TripRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_request_id: str
    assignment_id: str
    carrier_id: str
    status: str
