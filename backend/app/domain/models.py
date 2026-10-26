from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_value(value: object, field_name: str) -> None:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")


@dataclass
class TimestampMixin:
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None

    def mark_updated(self) -> None:
        self.updated_at = utc_now()

    def soft_delete(self) -> None:
        self.deleted_at = utc_now()
        self.mark_updated()


@dataclass
class User(TimestampMixin):
    display_name: str = ""
    role: str = "UNKNOWN"
    id: str = field(default_factory=lambda: new_id("user"))
    phone_number: str | None = None
    normalized_phone_number: str | None = None
    provider_name: str | None = None
    provider_contact_id: str | None = None
    provider_conversation_id: str | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    status: str = "ACTIVE"
    notes: str | None = None

    def __post_init__(self) -> None:
        require_value(self.display_name, "display_name")
        require_value(self.role, "role")


@dataclass
class Producer(TimestampMixin):
    name: str = ""
    id: str = field(default_factory=lambda: new_id("prod"))
    user_id: str | None = None
    contact_phone: str | None = None
    normalized_phone_number: str | None = None
    provider_name: str | None = None
    provider_contact_id: str | None = None
    provider_conversation_id: str | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    usual_location_id: str | None = None
    trust_notes: str | None = None
    is_validated: bool = False
    validated_at: datetime | None = None

    def __post_init__(self) -> None:
        require_value(self.name, "name")


@dataclass
class Carrier(TimestampMixin):
    name: str = ""
    id: str = field(default_factory=lambda: new_id("car"))
    user_id: str | None = None
    contact_phone: str | None = None
    normalized_phone_number: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    truck_count: int | None = None
    truck_types: list[str] = field(default_factory=list)
    truck_body_type: str | None = None
    provider_name: str | None = None
    provider_contact_id: str | None = None
    provider_conversation_id: str | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    service_zone: str | None = None
    trust_notes: str | None = None
    availability_notes: str | None = None
    is_validated: bool = False
    validation_status: str = "DRAFT"
    validated_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    reviewed_by_user_id: str | None = None

    def __post_init__(self) -> None:
        require_value(self.name, "name")
        if self.is_validated and self.validation_status == "DRAFT":
            self.validation_status = "APPROVED"


@dataclass
class Vehicle(TimestampMixin):
    carrier_id: str = ""
    id: str = field(default_factory=lambda: new_id("veh"))
    vehicle_type: str | None = None
    capacity_estimate: Decimal | None = None
    plate: str | None = None
    status: str = "UNKNOWN"
    validation_status: str = "PENDING_REVIEW"
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    validation_flags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_value(self.carrier_id, "carrier_id")


@dataclass
class Driver(TimestampMixin):
    carrier_id: str = ""
    name: str = ""
    id: str = field(default_factory=lambda: new_id("drv"))
    phone: str | None = None
    license_category: str | None = None
    status: str = "ACTIVE"
    validation_status: str = "PENDING_REVIEW"
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        require_value(self.carrier_id, "carrier_id")
        require_value(self.name, "name")


@dataclass
class Location(TimestampMixin):
    original_text: str = ""
    id: str = field(default_factory=lambda: new_id("loc"))
    normalized_name: str | None = None
    province: str | None = None
    locality: str | None = None
    rural_reference: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_source: str | None = None
    coordinate_precision: str | None = None
    georef_id: str | None = None
    catalog_version: str | None = None
    provenance: str = "USER_DECLARED"
    confidence: str = "unknown"
    is_validated: bool = False

    def __post_init__(self) -> None:
        require_value(self.original_text, "original_text")


@dataclass
class ShipmentRequest(TimestampMixin):
    """Transport need, not trip execution."""

    id: str = field(default_factory=lambda: new_id("sr"))
    test_run_id: str | None = None
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
    weight_per_head_kg: Decimal | None = None
    required_equipment_type: str | None = None
    operational_notes: str | None = None
    status: str = "DRAFT"
    field_confidence: dict[str, str] = field(default_factory=dict)
    missing_critical_fields: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    has_ambiguous_location: bool = False
    has_estimated_values: bool = False
    source_message_id: str | None = None
    validated_by_user_id: str | None = None
    validated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.cargo_category is None and self.livestock_type:
            self.cargo_category = "LIVESTOCK"
        if self.cargo_type is None and self.livestock_type:
            self.cargo_type = self.livestock_type


@dataclass
class TripOffer(TimestampMixin):
    """Offer implementation: carrier response, not assignment."""

    shipment_request_id: str = ""
    carrier_id: str = ""
    response_type: str = "INTERESTED"
    id: str = field(default_factory=lambda: new_id("off"))
    test_run_id: str | None = None
    vehicle_id: str | None = None
    source_message_id: str | None = None
    status: str = "RECEIVED"
    price_estimate: Decimal | None = None
    availability_window_start: datetime | None = None
    availability_window_end: datetime | None = None
    confidence: str = "unknown"
    requires_human_review: bool = False

    def __post_init__(self) -> None:
        require_value(self.shipment_request_id, "shipment_request_id")
        require_value(self.carrier_id, "carrier_id")
        require_value(self.response_type, "response_type")


@dataclass
class Assignment(TimestampMixin):
    """Confirmed or proposed match between a shipment request and a carrier."""

    shipment_request_id: str = ""
    carrier_id: str = ""
    selected_by_user_id: str = ""
    id: str = field(default_factory=lambda: new_id("asg"))
    test_run_id: str | None = None
    trip_offer_id: str | None = None
    vehicle_id: str | None = None
    status: str = "PROPOSED"
    confirmed_by_user_id: str | None = None
    confirmed_at: datetime | None = None
    confirmation_notes: str | None = None
    requires_human_review: bool = False

    def __post_init__(self) -> None:
        require_value(self.shipment_request_id, "shipment_request_id")
        require_value(self.carrier_id, "carrier_id")
        require_value(self.selected_by_user_id, "selected_by_user_id")


@dataclass
class Trip(TimestampMixin):
    """Logistics execution derived from a confirmed assignment."""

    shipment_request_id: str = ""
    assignment_id: str = ""
    carrier_id: str = ""
    id: str = field(default_factory=lambda: new_id("trip"))
    test_run_id: str | None = None
    driver_id: str | None = None
    vehicle_id: str | None = None
    status: str = "PLANNED"
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    incident_notes: str | None = None
    closure_notes: str | None = None
    requires_human_review: bool = False

    def __post_init__(self) -> None:
        require_value(self.shipment_request_id, "shipment_request_id")
        require_value(self.assignment_id, "assignment_id")
        require_value(self.carrier_id, "carrier_id")


@dataclass
class ConversationSession(TimestampMixin):
    channel: str = ""
    id: str = field(default_factory=lambda: new_id("cs"))
    external_conversation_id: str | None = None
    provider_name: str | None = None
    provider_contact_id: str | None = None
    provider_conversation_id: str | None = None
    workflow_execution_id: str | None = None
    participant_phone: str | None = None
    normalized_phone_number: str | None = None
    participant_user_id: str | None = None
    role_override: str | None = None
    active_test_run_id: str | None = None
    route_availability_capture: dict[str, Any] = field(default_factory=dict)
    status: str = "OPEN"
    started_at: datetime = field(default_factory=utc_now)
    last_message_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None

    def __post_init__(self) -> None:
        require_value(self.channel, "channel")


@dataclass
class Message(TimestampMixin):
    conversation_session_id: str = ""
    provider: str = "internal"
    direction: str = ""
    sender_type: str = ""
    message_type: str = "text"
    id: str = field(default_factory=lambda: new_id("msg"))
    test_run_id: str | None = None
    provider_message_id: str | None = None
    idempotency_key: str | None = None
    sender_id: str | None = None
    media_asset_id: str | None = None
    raw_content: str | None = None
    normalized_content: str | None = None
    received_at: datetime | None = None
    sent_at: datetime | None = None
    correlation_id: str | None = None
    related_entity_ids: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_value(self.conversation_session_id, "conversation_session_id")
        require_value(self.provider, "provider")
        require_value(self.direction, "direction")
        require_value(self.sender_type, "sender_type")
        require_value(self.message_type, "message_type")


@dataclass
class MediaAsset(TimestampMixin):
    provider: str = ""
    media_type: str = "unknown"
    id: str = field(default_factory=lambda: new_id("media"))
    message_id: str | None = None
    provider_media_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    external_url: str | None = None
    storage_uri: str | None = None
    sha256: str | None = None
    status: str = "RECEIVED"
    error_message: str | None = None
    transcription_status: str = "NOT_REQUIRED"
    transcription_text: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    transcription_error: str | None = None
    transcribed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_value(self.provider, "provider")
        require_value(self.media_type, "media_type")
        require_value(self.status, "status")
        require_value(self.transcription_status, "transcription_status")


@dataclass
class Document(TimestampMixin):
    entity_type: str = ""
    entity_id: str = ""
    document_type: str = ""
    id: str = field(default_factory=lambda: new_id("doc"))
    external_uri: str | None = None
    provider: str | None = None
    provider_media_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    storage_uri: str | None = None
    uploaded_by_phone: str | None = None
    status: str = "PENDING"
    notes: str | None = None
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    valid_from: date | None = None
    expires_at: date | None = None
    supersedes_document_id: str | None = None

    def __post_init__(self) -> None:
        require_value(self.entity_type, "entity_type")
        require_value(self.entity_id, "entity_id")
        require_value(self.document_type, "document_type")
        if self.valid_from and self.expires_at and self.valid_from > self.expires_at:
            raise ValueError("valid_from must not be after expires_at")
        if self.supersedes_document_id == self.id:
            raise ValueError("document cannot supersede itself")


@dataclass
class CarrierOnboarding(TimestampMixin):
    carrier_id: str = ""
    id: str = field(default_factory=lambda: new_id("cob"))
    status: str = "DRAFT"
    required_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    submitted_at: datetime | None = None
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    capture_context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_value(self.carrier_id, "carrier_id")


@dataclass
class WhatsappAllowedContact(TimestampMixin):
    phone_number: str = ""
    normalized_phone_number: str = ""
    id: str = field(default_factory=lambda: new_id("wac"))
    label: str | None = None
    environment: str = "all"
    provider: str = "all"
    status: str = "ACTIVE"
    notes: str | None = None
    created_by_user_id: str | None = None
    updated_by_user_id: str | None = None

    def __post_init__(self) -> None:
        require_value(self.phone_number, "phone_number")
        require_value(self.normalized_phone_number, "normalized_phone_number")
        require_value(self.environment, "environment")
        require_value(self.provider, "provider")
        require_value(self.status, "status")


@dataclass
class PaymentTerms(TimestampMixin):
    id: str = field(default_factory=lambda: new_id("pay"))
    shipment_request_id: str | None = None
    assignment_id: str | None = None
    trip_id: str | None = None
    amount_estimate: Decimal | None = None
    agreed_amount: Decimal | None = None
    commission_estimate: Decimal | None = None
    currency: str = "ARS"
    confidence: str = "unknown"
    source: str = "operator"
    notes: str | None = None

    def __post_init__(self) -> None:
        require_value(self.currency, "currency")
        require_value(self.confidence, "confidence")
        require_value(self.source, "source")


@dataclass
class RiskFlag(TimestampMixin):
    entity_type: str = ""
    entity_id: str = ""
    risk_type: str = ""
    severity: str = ""
    reason: str = ""
    created_by: str = ""
    id: str = field(default_factory=lambda: new_id("risk"))
    status: str = "OPEN"
    resolved_by_user_id: str | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        require_value(self.entity_type, "entity_type")
        require_value(self.entity_id, "entity_id")
        require_value(self.risk_type, "risk_type")
        require_value(self.severity, "severity")
        require_value(self.reason, "reason")
        require_value(self.created_by, "created_by")
