from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Float, Date, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models import utc_now
from app.infrastructure.db.base import Base


class TimestampColumns:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserRecord(TimestampColumns, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_contact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class OperatorRoleRecord(TimestampColumns, Base):
    __tablename__ = "operator_roles"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)


class ProducerRecord(TimestampColumns, Base):
    __tablename__ = "producers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_contact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usual_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    trust_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_validated: Mapped[bool] = mapped_column(default=False, nullable=False)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CarrierRecord(TimestampColumns, Base):
    __tablename__ = "carriers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    cuit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    truck_count: Mapped[int | None] = mapped_column(nullable=True)
    truck_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    truck_body_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_contact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_zone: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_validated: Mapped[bool] = mapped_column(default=False, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(64), default="DRAFT", nullable=False)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RouteAvailabilityRecord(TimestampColumns, Base):
    __tablename__ = "route_availabilities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), nullable=False, index=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    stops: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    capacity_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cargo_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    equipment_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    committed_shipment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declared_by_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class VehicleRecord(TimestampColumns, Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    vehicle_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(64), default="PENDING_REVIEW", nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class DriverRecord(TimestampColumns, Base):
    __tablename__ = "drivers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LocationRecord(TimestampColumns, Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    province: Mapped[str | None] = mapped_column(Text, nullable=True)
    locality: Mapped[str | None] = mapped_column(Text, nullable=True)
    rural_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coordinate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    coordinate_precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    georef_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    catalog_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), default="USER_DECLARED", nullable=False)
    confidence: Mapped[str] = mapped_column(String(64), nullable=False)
    is_validated: Mapped[bool] = mapped_column(default=False, nullable=False)


class GeographicCatalogRecord(TimestampColumns, Base):
    __tablename__ = "geographic_catalog"
    __table_args__ = (
        UniqueConstraint("kind", "georef_id", name="uq_geographic_catalog_kind_georef"),
        Index("ix_geographic_catalog_kind_parent_active", "kind", "parent_id", "active"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("geographic_catalog.id"), nullable=True)
    georef_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="MANUAL", nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)


class CargoCategoryRecord(TimestampColumns, Base):
    __tablename__ = "cargo_categories"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)


class CargoTypeRecord(TimestampColumns, Base):
    __tablename__ = "cargo_types"
    __table_args__ = (Index("ix_cargo_types_category_active", "category_code", "active"),)

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    category_code: Mapped[str] = mapped_column(ForeignKey("cargo_categories.code"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)


class ConversationSessionRecord(TimestampColumns, Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    external_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_contact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    participant_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    participant_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role_override: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    route_availability_capture: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageRecord(TimestampColumns, Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_sessions.id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    sender_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    related_entity_ids: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)


class NotificationOutboxRecord(TimestampColumns, Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_dispatch", "status", "available_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class MediaAssetRecord(TimestampColumns, Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_REQUIRED")
    transcription_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transcription_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcription_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShipmentRequestRecord(TimestampColumns, Base):
    __tablename__ = "shipment_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    producer_id: Mapped[str | None] = mapped_column(ForeignKey("producers.id"), nullable=True)
    producer_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    destination_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    date_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cargo_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cargo_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    livestock_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    weight_per_head_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_equipment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operational_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    field_confidence: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    missing_critical_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    has_ambiguous_location: Mapped[bool] = mapped_column(default=False, nullable=False)
    has_estimated_values: Mapped[bool] = mapped_column(default=False, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    validated_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TripOfferRecord(TimestampColumns, Base):
    __tablename__ = "trip_offers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    shipment_request_id: Mapped[str] = mapped_column(ForeignKey("shipment_requests.id"), nullable=False)
    carrier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    response_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    price_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    availability_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)


class AssignmentRecord(TimestampColumns, Base):
    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    shipment_request_id: Mapped[str] = mapped_column(ForeignKey("shipment_requests.id"), nullable=False)
    trip_offer_id: Mapped[str | None] = mapped_column(ForeignKey("trip_offers.id"), nullable=True)
    carrier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)


class TripRecord(TimestampColumns, Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    shipment_request_id: Mapped[str] = mapped_column(ForeignKey("shipment_requests.id"), nullable=False)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    carrier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    incident_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    closure_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)


class EventLogRecord(Base):
    __tablename__ = "event_logs"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    test_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    related_entity_ids: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)


class DocumentRecord(TimestampColumns, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    supersedes_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CarrierOnboardingRecord(TimestampColumns, Base):
    __tablename__ = "carrier_onboarding"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    required_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    capture_context: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)


class WhatsappAllowedContactRecord(TimestampColumns, Base):
    __tablename__ = "whatsapp_allowed_contacts"
    __table_args__ = (
        Index("ix_whatsapp_allowed_contacts_normalized_phone_number", "normalized_phone_number"),
        Index(
            "ix_whatsapp_allowed_contacts_phone_env_provider",
            "normalized_phone_number",
            "environment",
            "provider",
        ),
        Index("ix_whatsapp_allowed_contacts_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PaymentTermsRecord(TimestampColumns, Base):
    __tablename__ = "payment_terms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shipment_request_id: Mapped[str | None] = mapped_column(ForeignKey("shipment_requests.id"), nullable=True)
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("assignments.id"), nullable=True)
    trip_id: Mapped[str | None] = mapped_column(ForeignKey("trips.id"), nullable=True)
    amount_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    agreed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RiskFlagRecord(TimestampColumns, Base):
    __tablename__ = "risk_flags"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_shipment_requests_status", ShipmentRequestRecord.status)
Index("ix_shipment_requests_requires_human_review", ShipmentRequestRecord.requires_human_review)
Index("ix_trip_offers_shipment_request_id", TripOfferRecord.shipment_request_id)
Index("ix_assignments_shipment_request_id", AssignmentRecord.shipment_request_id)
Index("ix_trips_assignment_id", TripRecord.assignment_id)
Index("ix_messages_conversation_session_id", MessageRecord.conversation_session_id)
Index(
    "ix_messages_conversation_occurred_at",
    MessageRecord.conversation_session_id,
    func.coalesce(MessageRecord.received_at, MessageRecord.sent_at, MessageRecord.created_at),
    MessageRecord.id,
)
Index(
    "ix_event_logs_conversation_reply_failed",
    EventLogRecord.entity_type,
    EventLogRecord.entity_id,
    EventLogRecord.event_type,
    EventLogRecord.occurred_at,
    EventLogRecord.event_id,
)
Index("ix_media_assets_message_id", MediaAssetRecord.message_id)
Index("ix_media_assets_provider_media_id", MediaAssetRecord.provider_media_id)
Index("ix_event_logs_entity", EventLogRecord.entity_type, EventLogRecord.entity_id)
Index("ix_event_logs_event_type", EventLogRecord.event_type)
Index("ix_carrier_onboarding_carrier_id", CarrierOnboardingRecord.carrier_id)
Index("ix_carrier_onboarding_status", CarrierOnboardingRecord.status)

# Register route-operation metadata for explicit migrations and isolated tests.
from app.infrastructure.repositories.routing import RoutingOperationRecord  # noqa: E402,F401
