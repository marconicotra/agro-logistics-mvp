from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import (
    AuthenticatedUser,
    get_admin_ops_service,
    get_app_state,
    get_request_db_session,
    require_operator_user,
)
from app.application.admin_ops import (
    AdminOpsError,
    AdminOpsService,
    CarrierDashboardSummary,
    ChatDraftShipmentSummary,
    JourneyStatusSummary,
    OperationSummary,
    PendingAssignmentSummary,
    ProducerDashboardSummary,
    ProducerInterestedOfferSummary,
    ProducerShipmentSummary,
    ShipmentWithOffers,
)
from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.application.chat_shipment_parser import parse_chat_shipment_text
from app.core.config import get_settings
from app.domain.cargo import quantity_unit_label
from app.domain.models import Message, ShipmentRequest, Trip, TripOffer
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlConversationSessionRepository


router = APIRouter(prefix="/api/v1", tags=["admin-ops"])


class OperatorActionRequest(BaseModel):
    notes: str | None = None
    idempotency_key: str | None = None


class ValidateShipmentRequest(OperatorActionRequest):
    allow_missing_override: bool = False


class PublishShipmentRequest(BaseModel):
    carrier_ids: list[str]
    idempotency_key: str | None = None


class CreateShipmentFromChatRequest(BaseModel):
    text: str
    phone_number: str | None = None
    idempotency_key: str | None = None


class ChatShipmentPreviewRequest(BaseModel):
    text: str


class ChatShipmentPreviewResponse(BaseModel):
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_estimate: Decimal | None = None
    quantity_unit: str | None = None
    origin: str | None = None
    destination: str | None = None
    pickup_date: str | None = None
    pickup_date_display: str | None = None
    missing_fields: list[str]
    confirmation_summary: str


class ConfirmAssignmentRequest(BaseModel):
    confirmation_notes: str | None = None
    idempotency_key: str | None = None


class SelectOfferRequest(BaseModel):
    trip_offer_id: str
    idempotency_key: str | None = None


class ProducerAcceptOfferRequest(BaseModel):
    phone_number: str
    idempotency_key: str | None = None


class CancelTripRequest(BaseModel):
    reason: str
    idempotency_key: str | None = None


class ManualFallbackRequest(BaseModel):
    entity_type: str
    entity_id: str
    reason: str
    idempotency_key: str | None = None


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    producer_id: str | None = None
    missing_critical_fields: list[str]
    requires_human_review: bool


class OfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_request_id: str
    carrier_id: str
    response_type: str
    status: str
    requires_human_review: bool


class ShipmentOfferSummaryResponse(BaseModel):
    trip_offer_id: str
    carrier_id: str
    response_type: str
    status: str
    created_at: datetime


class ShipmentWithOffersResponse(BaseModel):
    shipment_id: str
    status: str
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    offers: list[ShipmentOfferSummaryResponse]


class ChatDraftShipmentResponse(BaseModel):
    shipment_id: str
    status: str
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    operational_notes: str | None = None
    created_at: datetime
    source_phone_number: str | None = None


class ProducerShipmentResponse(BaseModel):
    shipment_id: str
    status: str
    origin: str | None = None
    destination: str | None = None
    date_window_start: datetime | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    operational_notes: str | None = None
    created_at: datetime
    interested_offers_count: int


class ProducerInterestedOfferResponse(BaseModel):
    index: int
    shipment_id: str
    shipment_status: str
    trip_offer_id: str
    carrier_id: str
    response_type: str
    offer_status: str
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    created_at: datetime


class JourneyStatusResponse(BaseModel):
    shipment_id: str
    shipment_status: str
    trip_id: str | None = None
    trip_status: str | None = None
    assignment_id: str | None = None
    assignment_status: str | None = None
    origin: str | None = None
    destination: str | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    operational_notes: str | None = None
    interested_offers_count: int
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    counterparty_phone: str | None = None
    planned_start_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ProducerDashboardResponse(BaseModel):
    phone_number: str
    total_shipments: int
    active_shipments: int
    active_trips: int
    completed_trips: int
    pending_interested_offers: int
    current_operations: list[JourneyStatusResponse]
    past_operations: list[JourneyStatusResponse]


class CarrierDashboardResponse(BaseModel):
    carrier_id: str
    carrier_name: str
    carrier_phone: str | None = None
    total_offers: int
    open_offers: int
    active_trips: int
    completed_trips: int
    cancelled_trips: int
    current_operations: list[JourneyStatusResponse]
    past_operations: list[JourneyStatusResponse]


class PendingAssignmentResponse(BaseModel):
    assignment_id: str
    assignment_status: str
    shipment_id: str
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    carrier_id: str
    trip_offer_id: str | None = None
    trip_id: str | None = None
    trip_status: str | None = None
    created_at: datetime


class OperationSummaryResponse(BaseModel):
    shipment_id: str
    shipment_status: str
    assignment_id: str
    assignment_status: str
    trip_id: str | None = None
    trip_status: str | None = None
    carrier_id: str
    trip_offer_id: str | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    operational_notes: str | None = None
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_session_id: str
    provider: str
    direction: str
    sender_type: str
    redacted_content: str | None = None
    received_at: datetime | None = None


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_request_id: str
    assignment_id: str
    carrier_id: str
    status: str
    requires_human_review: bool


class AssignmentConfirmResponse(BaseModel):
    assignment_id: str
    assignment_status: str
    trip_id: str
    trip_status: str
    event_types: list[str]


class SelectOfferResponse(BaseModel):
    assignment_id: str
    assignment_status: str
    trip_id: str
    trip_status: str
    carrier_id: str
    trip_offer_id: str
    event_types: list[str]


class ProducerAcceptOfferResponse(BaseModel):
    assignment_id: str
    assignment_status: str
    trip_id: str
    trip_status: str
    shipment_id: str
    shipment_status: str
    carrier_id: str
    trip_offer_id: str
    already_active_assignment: bool
    event_types: list[str]


class PublishShipmentResponse(BaseModel):
    id: str
    status: str
    notifications_queued: int
    notifications_sent: int = 0
    notifications_failed: int = 0
    notifications_skipped: int = 0
    event_types: list[str]


class CreateShipmentFromChatResponse(BaseModel):
    shipment_id: str
    status: str
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None


class ManualFallbackResponse(BaseModel):
    handoff_required: bool
    status: str
    event_id: str
    entity_type: str
    entity_id: str


class TestSessionStatusResponse(BaseModel):
    enabled: bool
    mode: str
    role_override: str | None = None
    active_test_run_id: str | None = None
    phone_number: str | None = None
    carrier_detected: bool
    carrier_id: str | None = None


@router.get("/admin/ops/pending-shipments", response_model=list[ShipmentResponse])
def list_pending_shipments(
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ShipmentRequest]:
    del operator
    return service.list_pending_shipments()


@router.get("/admin/ops/incomplete-shipments", response_model=list[ShipmentResponse])
def list_incomplete_shipments(
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ShipmentRequest]:
    del operator
    return service.list_incomplete_shipments()


@router.get("/admin/shipments/with-offers", response_model=list[ShipmentWithOffersResponse])
def list_shipments_with_offers(
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ShipmentWithOffers]:
    del operator
    return service.list_shipments_with_offers()


@router.get("/admin/shipments/from-chat/recent", response_model=list[ChatDraftShipmentResponse])
def list_recent_chat_drafts(
    phone_number: str | None = None,
    limit: int = 5,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ChatDraftShipmentSummary]:
    del operator
    return service.list_recent_chat_drafts(phone_number=phone_number, limit=limit)


@router.get("/admin/shipments/drafts", response_model=list[ChatDraftShipmentResponse])
def list_draft_shipments(
    limit: int = 20,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ChatDraftShipmentSummary]:
    del operator
    return service.list_draft_shipments(limit=limit)


@router.get("/producer/shipments", response_model=list[ProducerShipmentResponse])
def list_producer_shipments(
    phone_number: str,
    limit: int = 10,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ProducerShipmentSummary]:
    del operator
    try:
        return service.list_producer_shipments(phone_number=phone_number, limit=limit)
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/producer/shipments/interested-offers", response_model=list[ProducerInterestedOfferResponse])
def list_producer_interested_offers(
    phone_number: str,
    limit: int = 10,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ProducerInterestedOfferSummary]:
    del operator
    try:
        return service.list_producer_interested_offers(phone_number=phone_number, limit=limit)
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/producer/dashboard", response_model=ProducerDashboardResponse)
def get_producer_dashboard(
    phone_number: str,
    limit: int = 12,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ProducerDashboardSummary:
    del operator
    try:
        return service.get_producer_dashboard(phone_number=phone_number, limit=limit)
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/carrier/dashboard/{carrier_id}", response_model=CarrierDashboardResponse)
def get_carrier_dashboard(
    carrier_id: str,
    limit: int = 12,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierDashboardSummary:
    del operator
    try:
        return service.get_carrier_dashboard(carrier_id=carrier_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc


@router.get("/admin/test/session-status", response_model=TestSessionStatusResponse)
def get_test_session_status(
    phone_number: str,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TestSessionStatusResponse:
    del operator
    settings = get_settings()
    if not settings.enable_test_role_switching or settings.is_production:
        return TestSessionStatusResponse(
            enabled=False,
            mode="disabled",
            phone_number=_mask_phone(phone_number),
            carrier_detected=False,
        )

    normalized_phone = _safe_normalize_phone_number(phone_number)
    candidates = _phone_lookup_candidates(normalized_phone)
    if db_session is not None:
        conversations = SqlConversationSessionRepository(db_session).list()
        carriers = SqlCarrierRepository(db_session).list()
    else:
        state = get_app_state()
        conversations = state.conversation_sessions.list()
        carriers = state.carriers.list()

    matching_sessions = [
        conversation
        for conversation in conversations
        if conversation.normalized_phone_number in candidates
    ]
    matching_sessions.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
    session = matching_sessions[0] if matching_sessions else None
    carrier = _find_carrier_for_phone_candidates(carriers, candidates)
    role_override = session.role_override if session is not None else None
    return TestSessionStatusResponse(
        enabled=True,
        mode=_role_label(role_override),
        role_override=role_override,
        active_test_run_id=session.active_test_run_id if session is not None else None,
        phone_number=_mask_phone(normalized_phone or phone_number),
        carrier_detected=carrier is not None,
        carrier_id=carrier.id if carrier is not None else None,
    )


@router.get("/admin/assignments/pending", response_model=list[PendingAssignmentResponse])
def list_pending_assignments(
    limit: int = 20,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[PendingAssignmentSummary]:
    del operator
    return service.list_pending_assignments(limit=limit)


@router.get("/admin/assignments/active", response_model=list[OperationSummaryResponse])
def list_active_assignments(
    limit: int = 20,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[OperationSummary]:
    del operator
    return service.list_active_assignments(limit=limit)


@router.get("/admin/operations/lookup/{entity_id}", response_model=OperationSummaryResponse)
def lookup_operation(
    entity_id: str,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> OperationSummary:
    del operator
    try:
        return service.lookup_operation(entity_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active operation not found") from exc


@router.get("/shipment-requests/{shipment_request_id}/offers", response_model=list[OfferResponse])
def list_offers_for_shipment(
    shipment_request_id: str,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[TripOffer]:
    del operator
    try:
        return service.list_offers_for_shipment(shipment_request_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment request not found") from exc


@router.get("/conversations/{conversation_session_id}/messages", response_model=list[MessageResponse])
def list_messages_for_conversation(
    conversation_session_id: str,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[MessageResponse]:
    del operator
    try:
        messages = service.list_messages_for_conversation(conversation_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from exc
    return [
        MessageResponse(
            id=message.id,
            conversation_session_id=message.conversation_session_id,
            provider=message.provider,
            direction=message.direction,
            sender_type=message.sender_type,
            redacted_content=_redact_message(message.raw_content),
            received_at=message.received_at,
        )
        for message in messages
    ]


@router.post("/shipment-requests/from-chat", response_model=CreateShipmentFromChatResponse)
def create_shipment_from_chat(
    request: CreateShipmentFromChatRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CreateShipmentFromChatResponse:
    try:
        result = service.create_shipment_draft_from_chat(
            text=request.text,
            phone_number=request.phone_number,
            operator_user_id=operator.user_id,
            idempotency_key=request.idempotency_key,
        )
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CreateShipmentFromChatResponse(
        shipment_id=result.shipment.id,
        status=result.shipment.status,
        cargo_category=result.shipment.cargo_category,
        cargo_type=result.shipment.cargo_type,
        quantity_unit=result.shipment.quantity_unit,
    )


@router.post("/admin/shipments/chat-preview", response_model=ChatShipmentPreviewResponse)
def preview_chat_shipment(
    request: ChatShipmentPreviewRequest,
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ChatShipmentPreviewResponse:
    del operator
    if not request.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="text is required")

    timezone = ZoneInfo("America/Argentina/Buenos_Aires")
    parsed = parse_chat_shipment_text(
        request.text,
        reference_datetime=datetime.now(timezone),
    )
    pickup_date = parsed.date_window_start.astimezone(timezone) if parsed.date_window_start else None
    weekday_names = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    pickup_date_display = (
        f"{weekday_names[pickup_date.weekday()]} {pickup_date.strftime('%d/%m/%Y')}"
        if pickup_date
        else None
    )

    missing_fields = []
    if not parsed.cargo_type:
        missing_fields.append("tipo de carga")
    if parsed.quantity_estimate is None:
        missing_fields.append("cantidad")
    elif parsed.quantity_unit is None:
        missing_fields.append("unidad")
    if not parsed.origin:
        missing_fields.append("origen")
    if not parsed.destination:
        missing_fields.append("destino")
    if pickup_date is None:
        missing_fields.append("fecha")

    summary_lines = []
    if parsed.cargo_type:
        summary_lines.append(f"Tipo de carga: {parsed.cargo_type}")
    if parsed.quantity_estimate is not None:
        quantity_text = format(parsed.quantity_estimate, "f")
        if "." in quantity_text:
            quantity_text = quantity_text.rstrip("0").rstrip(".")
        unit_label = quantity_unit_label(parsed.quantity_unit)
        summary_lines.append(
            f"Cantidad: {quantity_text}" + (f" {unit_label}" if unit_label else "")
        )
    if parsed.origin:
        summary_lines.append(f"Origen: {parsed.origin}")
    if parsed.destination:
        summary_lines.append(f"Destino: {parsed.destination}")
    if pickup_date_display:
        summary_lines.append(f"Fecha: {pickup_date_display}")

    return ChatShipmentPreviewResponse(
        cargo_category=parsed.cargo_category,
        cargo_type=parsed.cargo_type,
        quantity_estimate=parsed.quantity_estimate,
        quantity_unit=parsed.quantity_unit,
        origin=parsed.origin,
        destination=parsed.destination,
        pickup_date=pickup_date.date().isoformat() if pickup_date else None,
        pickup_date_display=pickup_date_display,
        missing_fields=missing_fields,
        confirmation_summary="\n".join(summary_lines),
    )


@router.post("/shipment-requests/{shipment_request_id}/validate", response_model=ShipmentResponse)
def validate_shipment(
    shipment_request_id: str,
    request: ValidateShipmentRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ShipmentRequest:
    try:
        return service.validate_shipment(
            shipment_request_id=shipment_request_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
            allow_missing_override=request.allow_missing_override,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment request not found") from exc
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/shipment-requests/{shipment_request_id}/publish", response_model=PublishShipmentResponse)
def publish_shipment(
    shipment_request_id: str,
    request: PublishShipmentRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> PublishShipmentResponse:
    try:
        result = service.publish_shipment(
            shipment_request_id=shipment_request_id,
            operator_user_id=operator.user_id,
            carrier_ids=request.carrier_ids,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PublishShipmentResponse(
        id=result.shipment.id,
        status=result.shipment.status,
        notifications_queued=len(request.carrier_ids),
        notifications_sent=sum(1 for item in result.notification_results if item.status == "sent"),
        notifications_failed=sum(1 for item in result.notification_results if item.status == "failed"),
        notifications_skipped=sum(1 for item in result.notification_results if item.status == "skipped_duplicate"),
        event_types=[event.event_type for event in result.events],
    )


@router.post("/shipments/{shipment_id}/select-offer", response_model=SelectOfferResponse)
def select_offer(
    shipment_id: str,
    request: SelectOfferRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> SelectOfferResponse:
    try:
        result = service.select_offer(
            shipment_request_id=shipment_id,
            trip_offer_id=request.trip_offer_id,
            operator_user_id=operator.user_id,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        detail = "Trip offer not found" if str(exc).strip("'").startswith("trip_offer:") else "Shipment request not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SelectOfferResponse(
        assignment_id=result.assignment.id,
        assignment_status=result.assignment.status,
        trip_id=result.trip.id,
        trip_status=result.trip.status,
        carrier_id=result.assignment.carrier_id,
        trip_offer_id=result.assignment.trip_offer_id or request.trip_offer_id,
        event_types=[event.event_type for event in result.events],
    )


@router.post(
    "/shipments/{shipment_id}/offers/{trip_offer_id}/accept",
    response_model=ProducerAcceptOfferResponse,
)
def accept_offer_by_producer(
    shipment_id: str,
    trip_offer_id: str,
    request: ProducerAcceptOfferRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ProducerAcceptOfferResponse:
    del operator
    try:
        result = service.accept_offer_by_producer(
            shipment_request_id=shipment_id,
            trip_offer_id=trip_offer_id,
            producer_phone_number=request.phone_number,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        detail = "Trip offer not found" if str(exc).strip("'").startswith("trip_offer:") else "Shipment request not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ProducerAcceptOfferResponse(
        assignment_id=result.assignment.id,
        assignment_status=result.assignment.status,
        trip_id=result.trip.id,
        trip_status=result.trip.status,
        shipment_id=result.shipment.id,
        shipment_status=result.shipment.status,
        carrier_id=result.assignment.carrier_id,
        trip_offer_id=result.assignment.trip_offer_id or trip_offer_id,
        already_active_assignment=result.already_active_assignment,
        event_types=[event.event_type for event in result.events],
    )


@router.post("/assignments/{assignment_id}/confirm", response_model=AssignmentConfirmResponse)
def confirm_assignment(
    assignment_id: str,
    request: ConfirmAssignmentRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> AssignmentConfirmResponse:
    try:
        result = service.confirm_assignment(
            assignment_id=assignment_id,
            operator_user_id=operator.user_id,
            confirmation_notes=request.confirmation_notes,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AssignmentConfirmResponse(
        assignment_id=result.assignment.id,
        assignment_status=result.assignment.status,
        trip_id=result.trip.id,
        trip_status=result.trip.status,
        event_types=[event.event_type for event in result.events],
    )


@router.post("/trips/{trip_id}/cancel", response_model=TripResponse)
def cancel_trip(
    trip_id: str,
    request: CancelTripRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> Trip:
    try:
        result = service.cancel_trip(
            trip_id=trip_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return result.trip


@router.post("/admin/ops/fallback", response_model=ManualFallbackResponse)
def activate_manual_fallback(
    request: ManualFallbackRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ManualFallbackResponse:
    try:
        event = service.request_manual_review(
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found") from exc
    return ManualFallbackResponse(
        handoff_required=True,
        status="queued_for_operator",
        event_id=event.event_id,
        entity_type=request.entity_type,
        entity_id=request.entity_id,
    )


def _redact_message(raw_content: str | None) -> str | None:
    if not raw_content:
        return raw_content
    return "[redacted]"


def _safe_normalize_phone_number(phone_number: str | None) -> str | None:
    try:
        return normalize_phone_number(phone_number)
    except PhoneNormalizationError:
        return None


def _phone_lookup_candidates(normalized_phone: str | None) -> set[str]:
    if not normalized_phone:
        return set()
    candidates = {normalized_phone}
    digits = normalized_phone[1:] if normalized_phone.startswith("+") else normalized_phone
    if digits.startswith("549") and len(digits) >= 6:
        candidates.add(f"+54{digits[3:]}")
    if digits.startswith("54") and not digits.startswith("549") and len(digits) >= 5:
        national = digits[2:]
        if national.startswith("11") and len(national) == 10:
            candidates.add(f"+549{national}")
    return candidates


def _find_carrier_for_phone_candidates(carriers, candidates: set[str]):  # noqa: ANN001, ANN201
    if not candidates:
        return None
    for carrier in carriers:
        carrier_candidates = _phone_lookup_candidates(carrier.normalized_phone_number)
        carrier_candidates.update(_phone_lookup_candidates(_safe_normalize_phone_number(carrier.contact_phone)))
        if carrier_candidates.intersection(candidates):
            return carrier
    return None


def _mask_phone(phone_number: str | None) -> str | None:
    if not phone_number:
        return None
    digits = "".join(character for character in phone_number if character.isdigit())
    if len(digits) <= 4:
        return "***"
    prefix = "+" if phone_number.strip().startswith("+") else ""
    return f"{prefix}{digits[:3]}***{digits[-3:]}"


def _role_label(role: str | None) -> str:
    return {
        "Producer": "Productor",
        "Carrier": "Transportista",
        "Operator": "Operador",
    }.get(role or "", "Automático")
