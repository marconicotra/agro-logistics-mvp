from dataclasses import replace
from datetime import UTC, date, datetime
import base64
import json
from typing import Generic, Literal, TypeVar
from decimal import Decimal
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    AuthenticatedUser,
    get_admin_ops_service,
    get_backoffice_service,
    get_carrier_onboarding_service,
    get_event_log_service,
    get_notification_outbox_admin_service,
    get_producer_backoffice_service,
    get_route_availability_repository,
    get_request_db_session,
    require_admin_user,
    get_whatsapp_allowlist_service,
    require_operator_user,
)
from app.application.admin_ops import AdminOpsError, AdminOpsService, TripStatusUpdateResult
from app.application.backoffice import (
    BackofficeOverview,
    BackofficeService,
    OpenConversationSummary,
    PendingCarrierSummary,
    ShipmentDetail,
    ShipmentEventTimelineItem,
    ShipmentAssignmentDetailSummary,
    ShipmentOfferDetailSummary,
    ShipmentTripDetailSummary,
    ShipmentDetailSummary,
    ShipmentMutationInput,
    TripMutationInput,
    TripSummary,
    UnassignedShipmentSummary,
)
from app.application.carrier_onboarding import (
    CarrierMutationInput,
    CarrierSummary,
    CarrierOnboardingDetail,
    CarrierOnboardingError,
    CarrierOnboardingPendingSummary,
    CarrierOnboardingService,
    DriverMutationInput,
    DocumentMutationInput,
    VehicleMutationInput,
)
from app.application.notification_outbox_admin import (
    NotificationOutboxAdminService,
    NotificationOutboxStatus,
)
from app.application.producer_backoffice import ProducerBackofficeService
from app.application.whatsapp_allowlist import (
    WhatsappAllowedContactInput,
    WhatsappAllowedContactSummary,
    WhatsappAllowlistError,
    WhatsappAllowlistService,
)
from app.core.config import get_settings
from app.domain.models import Document
from app.domain.route_availability import RouteAvailability, match_route_availability
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.models import (
    CargoCategoryRecord,
    CargoTypeRecord,
    GeographicCatalogRecord,
    OperatorRoleRecord,
)
from app.infrastructure.db.models import EventLogRecord, MessageRecord


router = APIRouter(prefix="/api/v1/backoffice", tags=["backoffice"])
PageItem = TypeVar("PageItem")


class ListPageResponse(BaseModel, Generic[PageItem]):
    items: list[PageItem]
    total: int
    limit: int
    offset: int


def _fold_catalog_name(value: str) -> str:
    plain = "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def _catalog_aliases(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        clean = " ".join(value.split())
        folded = _fold_catalog_name(clean)
        if clean and folded not in seen:
            result.append(clean)
            seen.add(folded)
    return result


def _catalog_session(db_session: Session | None) -> Session:
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Los catálogos requieren base SQL")
    return db_session


def _geography_response(row: GeographicCatalogRecord, session: Session) -> "GeographicCatalogResponse":
    parent = session.get(GeographicCatalogRecord, row.parent_id) if row.parent_id else None
    return GeographicCatalogResponse(
        id=row.id,
        kind=row.kind,
        name=row.name,
        normalized_name=row.normalized_name,
        parent_id=row.parent_id,
        parent_name=parent.name if parent else None,
        georef_id=row.georef_id,
        aliases=list(row.aliases or []),
        source=row.source,
        active=row.active,
    )


def _cargo_category_response(row: CargoCategoryRecord) -> "CargoCategoryResponse":
    return CargoCategoryResponse(
        code=row.code, name=row.name, aliases=list(row.aliases or []), active=row.active, sort_order=row.sort_order
    )


def _cargo_type_response(row: CargoTypeRecord, category: CargoCategoryRecord) -> "CargoTypeResponse":
    return CargoTypeResponse(
        code=row.code,
        category_code=row.category_code,
        category_name=category.name,
        name=row.name,
        aliases=list(row.aliases or []),
        active=row.active,
        sort_order=row.sort_order,
    )


class BackofficeOverviewResponse(BaseModel):
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


class RouteAvailabilityCreateRequest(BaseModel):
    carrier_id: str
    test_run_id: str | None = None
    origin: str
    destination: str
    stops: list[str] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    capacity: Decimal | None = None
    capacity_unit: str | None = None
    cargo_types: list[str] = Field(default_factory=list)
    equipment_types: list[str] = Field(default_factory=list)


class RouteAvailabilityStatusRequest(BaseModel):
    status: Literal["ACTIVE", "CLOSED", "CANCELLED"]


class RouteMatchRequest(BaseModel):
    origin: str
    destination: str
    shipment_at: datetime | None = None
    cargo_type: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    equipment_type: str | None = None


class RouteAvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    carrier_id: str
    test_run_id: str | None
    origin: str
    destination: str
    stops: list[str]
    window_start: datetime | None
    window_end: datetime | None
    capacity: Decimal | None
    capacity_unit: str | None
    cargo_types: list[str]
    equipment_types: list[str]
    status: str
    committed_shipment_id: str | None


class RouteAvailabilityMatchResponse(BaseModel):
    availability: RouteAvailabilityResponse
    segment_origin: str
    segment_destination: str
    reasons: list[str]


class GeographicCatalogResponse(BaseModel):
    id: str
    kind: Literal["PROVINCE", "DEPARTMENT", "LOCALITY"]
    name: str
    normalized_name: str
    parent_id: str | None
    parent_name: str | None = None
    georef_id: str | None
    aliases: list[str]
    source: str
    active: bool


class GeographicCatalogCreateRequest(BaseModel):
    kind: Literal["PROVINCE", "DEPARTMENT", "LOCALITY"]
    name: str = Field(min_length=1, max_length=160)
    parent_id: str | None = None
    aliases: list[str] = Field(default_factory=list, max_length=30)


class GeographicCatalogUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: str | None = None
    aliases: list[str] | None = Field(default=None, max_length=30)
    active: bool | None = None


class CargoCategoryResponse(BaseModel):
    code: str
    name: str
    aliases: list[str]
    active: bool
    sort_order: int


class CargoCategoryCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    active: bool = True
    sort_order: int = 0


class CargoCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = Field(default=None, max_length=30)
    active: bool | None = None
    sort_order: int | None = None


class CargoTypeResponse(BaseModel):
    code: str
    category_code: str
    category_name: str
    name: str
    aliases: list[str]
    active: bool
    sort_order: int


class CargoCatalogResponse(BaseModel):
    categories: list[CargoCategoryResponse]
    types: list[CargoTypeResponse]


class CargoTypeCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    category_code: str
    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    active: bool = True
    sort_order: int = 0


class CargoTypeUpdateRequest(BaseModel):
    category_code: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = Field(default=None, max_length=30)
    active: bool | None = None
    sort_order: int | None = None


@router.get("/catalogs/geography", response_model=ListPageResponse[GeographicCatalogResponse])
def list_geographic_catalog(
    kind: Literal["PROVINCE", "DEPARTMENT", "LOCALITY"] | None = None,
    parent_id: str | None = None,
    search: str | None = None,
    active: bool | None = True,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ListPageResponse[GeographicCatalogResponse]:
    del operator
    session = _catalog_session(db_session)
    statement = select(GeographicCatalogRecord).where(GeographicCatalogRecord.deleted_at.is_(None))
    if kind:
        statement = statement.where(GeographicCatalogRecord.kind == kind)
    if parent_id:
        if kind == "LOCALITY":
            department_ids = select(GeographicCatalogRecord.id).where(
                GeographicCatalogRecord.kind == "DEPARTMENT",
                GeographicCatalogRecord.parent_id == parent_id,
                GeographicCatalogRecord.deleted_at.is_(None),
            )
            statement = statement.where(
                or_(
                    GeographicCatalogRecord.parent_id == parent_id,
                    GeographicCatalogRecord.parent_id.in_(department_ids),
                )
            )
        else:
            statement = statement.where(GeographicCatalogRecord.parent_id == parent_id)
    if active is not None:
        statement = statement.where(GeographicCatalogRecord.active.is_(active))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(GeographicCatalogRecord.name.ilike(pattern))
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(GeographicCatalogRecord.normalized_name, GeographicCatalogRecord.id)
        .offset(offset).limit(limit)
    ).all()
    return ListPageResponse(
        items=[_geography_response(row, session) for row in rows], total=total, limit=limit, offset=offset
    )


@router.post("/catalogs/geography", response_model=GeographicCatalogResponse, status_code=status.HTTP_201_CREATED)
def create_geographic_catalog_entry(
    request: GeographicCatalogCreateRequest,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_admin_user),
) -> GeographicCatalogResponse:
    session = _catalog_session(db_session)
    name = " ".join(request.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacío")
    parent = session.get(GeographicCatalogRecord, request.parent_id) if request.parent_id else None
    expected_parent = {"PROVINCE": None, "DEPARTMENT": "PROVINCE", "LOCALITY": {"PROVINCE", "DEPARTMENT"}}[request.kind]
    if request.kind == "PROVINCE" and request.parent_id:
        raise HTTPException(status_code=422, detail="Una provincia no puede depender de otra entrada")
    if request.kind != "PROVINCE" and (parent is None or parent.deleted_at is not None or not parent.active):
        raise HTTPException(status_code=422, detail="Seleccioná una provincia o partido activo como superior")
    if request.kind == "DEPARTMENT" and parent and parent.kind != expected_parent:
        raise HTTPException(status_code=422, detail="Un partido debe depender de una provincia")
    if request.kind == "LOCALITY" and parent and parent.kind not in expected_parent:
        raise HTTPException(status_code=422, detail="Una localidad debe depender de una provincia o partido")
    normalized = _fold_catalog_name(name)
    duplicate = session.scalar(
        select(GeographicCatalogRecord.id).where(
            GeographicCatalogRecord.kind == request.kind,
            GeographicCatalogRecord.parent_id.is_(None) if request.parent_id is None else GeographicCatalogRecord.parent_id == request.parent_id,
            GeographicCatalogRecord.normalized_name == normalized,
            GeographicCatalogRecord.deleted_at.is_(None),
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Ya existe una entrada con ese nombre en la misma zona")
    row = GeographicCatalogRecord(
        id=f"manual:{uuid4().hex}", kind=request.kind, name=name, normalized_name=normalized,
        parent_id=request.parent_id, georef_id=None, aliases=_catalog_aliases(request.aliases), source="MANUAL", active=True,
    )
    session.add(row)
    SqlEventLogService(session).record(
        event_type="GEOGRAPHIC_CATALOG_ENTRY_CREATED", actor_type="ADMIN", actor_id=operator.user_id,
        entity_type="GeographicCatalogEntry", entity_id=row.id, summary="Entrada geográfica creada",
        payload={"kind": row.kind, "name": row.name, "parent_id": row.parent_id}, source="backoffice_catalogs",
    )
    session.commit()
    return _geography_response(row, session)


@router.patch("/catalogs/geography/{entry_id}", response_model=GeographicCatalogResponse)
def update_geographic_catalog_entry(
    entry_id: str,
    request: GeographicCatalogUpdateRequest,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_admin_user),
) -> GeographicCatalogResponse:
    session = _catalog_session(db_session)
    row = session.get(GeographicCatalogRecord, entry_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="No se encontró la entrada geográfica")
    changes = request.model_dump(exclude_unset=True)
    next_parent_id = changes.get("parent_id", row.parent_id)
    if next_parent_id != row.parent_id:
        if next_parent_id == row.id:
            raise HTTPException(status_code=422, detail="Una entrada no puede depender de sí misma")
        parent = session.get(GeographicCatalogRecord, next_parent_id) if next_parent_id else None
        allowed = {"PROVINCE": None, "DEPARTMENT": {"PROVINCE"}, "LOCALITY": {"PROVINCE", "DEPARTMENT"}}[row.kind]
        if row.kind == "PROVINCE" and next_parent_id:
            raise HTTPException(status_code=422, detail="Una provincia no puede depender de otra entrada")
        if row.kind != "PROVINCE" and (
            parent is None or parent.deleted_at is not None or not parent.active or parent.kind not in allowed
        ):
            raise HTTPException(status_code=422, detail="La jerarquía geográfica seleccionada no es válida")
        if row.kind == "DEPARTMENT":
            child = session.scalar(select(GeographicCatalogRecord.id).where(GeographicCatalogRecord.parent_id == row.id).limit(1))
            if child and child != next_parent_id:
                raise HTTPException(status_code=409, detail="No se puede mover un partido con localidades asociadas")
        row.parent_id = next_parent_id
    if "name" in changes and changes["name"] is not None:
        row.name = " ".join(changes["name"].split())
        row.normalized_name = _fold_catalog_name(row.name)
    if "aliases" in changes and changes["aliases"] is not None:
        row.aliases = _catalog_aliases(changes["aliases"])
    if changes.get("active") is not None:
        if changes["active"] is False and session.scalar(
            select(GeographicCatalogRecord.id).where(
                GeographicCatalogRecord.parent_id == row.id,
                GeographicCatalogRecord.active.is_(True),
                GeographicCatalogRecord.deleted_at.is_(None),
            ).limit(1)
        ):
            raise HTTPException(status_code=409, detail="Primero desactivá las entradas geográficas dependientes")
        row.active = changes["active"]
    duplicate = session.scalar(
        select(GeographicCatalogRecord.id).where(
            GeographicCatalogRecord.id != row.id,
            GeographicCatalogRecord.kind == row.kind,
            GeographicCatalogRecord.parent_id.is_(None) if row.parent_id is None else GeographicCatalogRecord.parent_id == row.parent_id,
            GeographicCatalogRecord.normalized_name == row.normalized_name,
            GeographicCatalogRecord.deleted_at.is_(None),
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Ya existe una entrada con ese nombre en la misma zona")
    row.updated_at = datetime.now(UTC)
    SqlEventLogService(session).record(
        event_type="GEOGRAPHIC_CATALOG_ENTRY_UPDATED", actor_type="ADMIN", actor_id=operator.user_id,
        entity_type="GeographicCatalogEntry", entity_id=row.id, summary="Entrada geográfica actualizada",
        payload={"kind": row.kind, "name": row.name, "parent_id": row.parent_id, "active": row.active},
        source="backoffice_catalogs",
    )
    session.commit()
    return _geography_response(row, session)


@router.get("/catalogs/cargo", response_model=CargoCatalogResponse)
def list_cargo_catalog(
    include_inactive: bool = False,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CargoCatalogResponse:
    del operator
    session = _catalog_session(db_session)
    categories_statement = select(CargoCategoryRecord).where(CargoCategoryRecord.deleted_at.is_(None))
    types_statement = select(CargoTypeRecord).where(CargoTypeRecord.deleted_at.is_(None))
    if not include_inactive:
        categories_statement = categories_statement.where(CargoCategoryRecord.active.is_(True))
        types_statement = types_statement.where(CargoTypeRecord.active.is_(True))
    categories = session.scalars(categories_statement.order_by(CargoCategoryRecord.sort_order)).all()
    by_code = {row.code: row for row in categories}
    types = [row for row in session.scalars(types_statement.order_by(CargoTypeRecord.sort_order)).all() if row.category_code in by_code]
    return CargoCatalogResponse(
        categories=[_cargo_category_response(row) for row in categories],
        types=[_cargo_type_response(row, by_code[row.category_code]) for row in types],
    )


@router.post("/catalogs/cargo/categories", response_model=CargoCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_cargo_category(
    request: CargoCategoryCreateRequest,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_admin_user),
) -> CargoCategoryResponse:
    session = _catalog_session(db_session)
    if session.get(CargoCategoryRecord, request.code):
        raise HTTPException(status_code=409, detail="Ese código de categoría ya existe")
    row = CargoCategoryRecord(
        code=request.code, name=" ".join(request.name.split()), aliases=_catalog_aliases(request.aliases),
        active=request.active, sort_order=request.sort_order,
    )
    session.add(row)
    SqlEventLogService(session).record(
        event_type="CARGO_CATEGORY_CREATED", actor_type="ADMIN", actor_id=operator.user_id,
        entity_type="CargoCategory", entity_id=row.code, summary="Categoría de carga creada",
        payload={"code": row.code, "name": row.name}, source="backoffice_catalogs",
    )
    session.commit()
    return _cargo_category_response(row)


@router.patch("/catalogs/cargo/categories/{code}", response_model=CargoCategoryResponse)
def update_cargo_category(
    code: str,
    request: CargoCategoryUpdateRequest,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_admin_user),
) -> CargoCategoryResponse:
    session = _catalog_session(db_session)
    row = session.get(CargoCategoryRecord, code)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="No se encontró la categoría")
    changes = request.model_dump(exclude_unset=True)
    if changes.get("active") is False and session.scalar(
        select(CargoTypeRecord.code).where(CargoTypeRecord.category_code == code, CargoTypeRecord.active.is_(True)).limit(1)
    ):
        raise HTTPException(status_code=409, detail="Primero desactivá los tipos de carga de esta categoría")
    for field in ("name", "aliases", "active", "sort_order"):
        if field in changes and changes[field] is not None:
            setattr(row, field, " ".join(changes[field].split()) if field == "name" else _catalog_aliases(changes[field]) if field == "aliases" else changes[field])
    row.updated_at = datetime.now(UTC)
    SqlEventLogService(session).record(
        event_type="CARGO_CATEGORY_UPDATED", actor_type="ADMIN", actor_id=operator.user_id,
        entity_type="CargoCategory", entity_id=row.code, summary="Categoría de carga actualizada",
        payload={"name": row.name, "active": row.active, "sort_order": row.sort_order}, source="backoffice_catalogs",
    )
    session.commit()
    return _cargo_category_response(row)


@router.post("/catalogs/cargo/types", response_model=CargoTypeResponse, status_code=status.HTTP_201_CREATED)
def create_cargo_type(
    request: CargoTypeCreateRequest,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_admin_user),
) -> CargoTypeResponse:
    session = _catalog_session(db_session)
    category = session.get(CargoCategoryRecord, request.category_code)
    if category is None or not category.active or category.deleted_at is not None:
        raise HTTPException(status_code=422, detail="La categoría seleccionada no está activa")
    if session.get(CargoTypeRecord, request.code):
        raise HTTPException(status_code=409, detail="Ese código de tipo ya existe")
    row = CargoTypeRecord(
        code=request.code, category_code=category.code, name=" ".join(request.name.split()),
        aliases=_catalog_aliases(request.aliases), active=request.active, sort_order=request.sort_order,
    )
    session.add(row)
    SqlEventLogService(session).record(
        event_type="CARGO_TYPE_CREATED", actor_type="ADMIN", actor_id=operator.user_id,
        entity_type="CargoType", entity_id=row.code, summary="Tipo de carga creado",
        payload={"category_code": row.category_code, "name": row.name}, source="backoffice_catalogs",
    )
    session.commit()
    return _cargo_type_response(row, category)


@router.patch("/catalogs/cargo/types/{code}", response_model=CargoTypeResponse)
def update_cargo_type(
    code: str,
    request: CargoTypeUpdateRequest,
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_admin_user),
) -> CargoTypeResponse:
    session = _catalog_session(db_session)
    row = session.get(CargoTypeRecord, code)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="No se encontró el tipo de carga")
    changes = request.model_dump(exclude_unset=True)
    if changes.get("category_code"):
        category = session.get(CargoCategoryRecord, changes["category_code"])
        if category is None or not category.active or category.deleted_at is not None:
            raise HTTPException(status_code=422, detail="La categoría seleccionada no está activa")
        row.category_code = category.code
    else:
        category = session.get(CargoCategoryRecord, row.category_code)
    if changes.get("name") is not None:
        row.name = " ".join(changes["name"].split())
    if changes.get("aliases") is not None:
        row.aliases = _catalog_aliases(changes["aliases"])
    if changes.get("active") is not None:
        row.active = changes["active"]
    if changes.get("sort_order") is not None:
        row.sort_order = changes["sort_order"]
    row.updated_at = datetime.now(UTC)
    SqlEventLogService(session).record(
        event_type="CARGO_TYPE_UPDATED", actor_type="ADMIN", actor_id=operator.user_id,
        entity_type="CargoType", entity_id=row.code, summary="Tipo de carga actualizado",
        payload={"category_code": row.category_code, "name": row.name, "active": row.active}, source="backoffice_catalogs",
    )
    session.commit()
    assert category is not None
    return _cargo_type_response(row, category)


class NotificationOutboxItemResponse(BaseModel):
    id: str
    status: str
    provider: str
    notification_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    test_run_id: str | None = None
    attempts: int
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    last_error_code: str | None = None


class NotificationOutboxResponse(BaseModel):
    counts: dict[str, int]
    items: list[NotificationOutboxItemResponse]
    total: int
    limit: int
    offset: int


class NotificationOutboxReconciliationRequest(BaseModel):
    resolution: Literal["ACCEPTED", "RETRY_NOT_SENT"]
    evidence_reference: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:/-]+$")


class NotificationOutboxReconciliationResponse(BaseModel):
    id: str
    status: str


class ProducerListItemResponse(BaseModel):
    id: str
    name: str
    phone: str | None = None
    is_validated: bool
    usual_location_id: str | None = None
    last_activity_at: datetime | None = None
    shipments_count: int
    active_shipments_count: int
    trips_count: int
    conversations_count: int


class ProducerShipmentItemResponse(BaseModel):
    id: str
    status: str
    origin: str | None = None
    destination: str | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_estimate: Decimal | None = None
    weight_per_head_kg: Decimal | None = None
    quantity_unit: str | None = None
    date_window_start: datetime | None = None
    date_window_end: datetime | None = None
    created_at: datetime


class ProducerOfferItemResponse(BaseModel):
    id: str
    shipment_request_id: str
    carrier_id: str
    status: str
    response_type: str
    created_at: datetime


class ProducerTripItemResponse(BaseModel):
    id: str
    shipment_request_id: str
    carrier_id: str
    status: str
    planned_start_at: datetime | None = None
    created_at: datetime


class ProducerEventItemResponse(BaseModel):
    id: str
    event_type: str
    occurred_at: datetime
    actor_type: str
    summary: str
    entity_type: str
    entity_id: str


class ProducerDetailResponse(BaseModel):
    producer: ProducerListItemResponse
    email: str | None = None
    trust_notes: str | None = None
    validated_at: datetime | None = None
    shipments: list[ProducerShipmentItemResponse]
    offers: list[ProducerOfferItemResponse]
    trips: list[ProducerTripItemResponse]
    conversation_ids: list[str]
    events: list[ProducerEventItemResponse]


class OperatorRoleRequest(BaseModel):
    role: Literal["operator", "admin"]


class OperatorRoleResponse(BaseModel):
    user_id: str
    role: str
    assigned_by_user_id: str


class OperatorProfileResponse(BaseModel):
    user_id: str
    role: str


class OpenConversationResponse(BaseModel):
    id: str
    participant_phone: str | None = None
    channel: str
    last_message_preview: str | None = None
    last_activity_at: datetime | None = None
    status: str
    needs_operator: bool
    related_entity_type: str | None = None
    related_entity_id: str | None = None


class OpenConversationPageResponse(BaseModel):
    items: list[OpenConversationResponse]
    total: int
    limit: int
    offset: int


class ConversationMessageResponse(BaseModel):
    id: str
    conversation_session_id: str
    direction: str
    sender_type: str
    message_type: str
    content: str | None = None
    occurred_at: datetime
    test_run_id: str | None = None
    qa_role: str | None = None
    delivery_status: str | None = None


class ConversationMessagePageResponse(BaseModel):
    items: list[ConversationMessageResponse]
    next_cursor: str | None = None
    latest_cursor: str | None = None
    has_more: bool


class UnassignedShipmentResponse(BaseModel):
    id: str
    origin: str | None = None
    destination: str | None = None
    cargo_category: str | None = None
    cargo_type: str | None = None
    quantity_unit: str | None = None
    livestock_type: str | None = None
    quantity_estimate: Decimal | None = None
    weight_per_head_kg: Decimal | None = None
    status: str
    created_at: datetime
    age_hours: float
    offers_count: int
    interested_carriers_count: int


class ShipmentDetailCoreResponse(BaseModel):
    id: str
    test_run_id: str | None = None
    status: str
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
    source_message_id: str | None = None
    source_message_preview: str | None = None
    requires_human_review: bool
    has_ambiguous_location: bool
    has_estimated_values: bool
    missing_critical_fields: list[str]
    field_confidence: dict[str, str]
    created_at: datetime
    updated_at: datetime


class ShipmentOfferDetailResponse(BaseModel):
    id: str
    carrier_id: str
    carrier_name: str | None = None
    carrier_phone: str | None = None
    vehicle_id: str | None = None
    vehicle_plate: str | None = None
    response_type: str
    status: str
    price_estimate: Decimal | None = None
    availability_window_start: datetime | None = None
    availability_window_end: datetime | None = None
    confidence: str
    requires_human_review: bool
    source_message_id: str | None = None
    source_message_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class ShipmentAssignmentDetailResponse(BaseModel):
    id: str
    shipment_request_id: str
    carrier_id: str
    carrier_name: str | None = None
    carrier_phone: str | None = None
    vehicle_id: str | None = None
    vehicle_plate: str | None = None
    trip_offer_id: str | None = None
    status: str
    selected_by_user_id: str
    confirmed_by_user_id: str | None = None
    confirmed_at: datetime | None = None
    confirmation_notes: str | None = None
    requires_human_review: bool
    created_at: datetime
    updated_at: datetime


class ShipmentTripDetailResponse(BaseModel):
    id: str
    shipment_request_id: str
    assignment_id: str
    carrier_id: str
    carrier_name: str | None = None
    carrier_phone: str | None = None
    driver_id: str | None = None
    vehicle_id: str | None = None
    vehicle_plate: str | None = None
    status: str
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    incident_notes: str | None = None
    closure_notes: str | None = None
    requires_human_review: bool
    created_at: datetime
    updated_at: datetime


class ShipmentEventTimelineResponse(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    actor_type: str
    actor_id: str | None = None
    entity_type: str
    entity_id: str
    summary: str
    previous_state: str | None = None
    new_state: str | None = None
    related_entity_ids: dict[str, str]
    source: str


class ShipmentDetailResponse(BaseModel):
    shipment: ShipmentDetailCoreResponse
    offers: list[ShipmentOfferDetailResponse]
    active_assignment: ShipmentAssignmentDetailResponse | None = None
    assignments: list[ShipmentAssignmentDetailResponse]
    active_trip: ShipmentTripDetailResponse | None = None
    trips: list[ShipmentTripDetailResponse]
    events: list[ShipmentEventTimelineResponse]


class ShipmentMutationRequest(BaseModel):
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


class ManualShipmentCarrierActionRequest(BaseModel):
    carrier_id: str
    notes: str | None = None
    idempotency_key: str | None = None


class ManualShipmentInterestResponse(BaseModel):
    shipment_id: str
    shipment_status: str
    trip_offer_id: str
    trip_offer_status: str
    carrier_id: str
    carrier_notification_status: str | None = None
    producer_notification_status: str | None = None
    event_types: list[str]


class ManualShipmentAssignmentResponse(BaseModel):
    shipment_id: str
    shipment_status: str
    trip_offer_id: str
    assignment_id: str
    assignment_status: str
    trip_id: str
    trip_status: str
    carrier_id: str
    carrier_notification_status: str | None = None
    producer_notification_status: str | None = None
    event_types: list[str]


class TripOperatorActionRequest(BaseModel):
    notes: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None


class TripOperatorActionResponse(BaseModel):
    shipment_id: str
    shipment_status: str
    trip_id: str
    trip_status: str
    carrier_notification_status: str | None = None
    producer_notification_status: str | None = None
    event_types: list[str]


class TripCrewAssignmentResponse(BaseModel):
    trip_id: str
    carrier_id: str
    driver_id: str
    vehicle_id: str
    trip_status: str


class TripMutationRequest(BaseModel):
    status: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    incident_notes: str | None = None
    closure_notes: str | None = None
    requires_human_review: bool | None = None


class TripCrewAssignmentRequest(BaseModel):
    driver_id: str
    vehicle_id: str


class DriverCreateRequest(BaseModel):
    name: str
    phone: str | None = None
    license_category: str | None = None


class DriverReviewRequest(BaseModel):
    notes: str


class DriverRejectRequest(BaseModel):
    reason: str


class TripResponse(BaseModel):
    test_run_id: str | None = None
    id: str
    status: str
    shipment_request_id: str
    carrier_id: str
    driver_id: str | None = None
    vehicle_id: str | None = None
    carrier_name: str | None = None
    origin: str | None = None
    destination: str | None = None
    planned_start_at: datetime | None = None
    updated_at: datetime


class PendingCarrierResponse(BaseModel):
    id: str
    name: str
    contact_phone: str | None = None
    phone: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    truck_count: int
    vehicles_count: int
    documents_count: int
    pending_documents_count: int
    created_at: datetime


class CarrierOnboardingPendingResponse(BaseModel):
    carrier_id: str
    onboarding_id: str | None = None
    name: str
    contact_phone: str | None = None
    phone: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    validation_status: str
    onboarding_status: str | None = None
    missing_fields: list[str]
    documents_count: int
    pending_documents_count: int
    created_at: datetime
    submitted_at: datetime | None = None


class CarrierOnboardingDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_type: str
    entity_id: str
    document_type: str
    has_file: bool = False
    provider: str | None = None
    provider_media_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    uploaded_by_phone: str | None = None
    status: str
    notes: str | None = None
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    valid_from: date | None = None
    expires_at: date | None = None
    supersedes_document_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CarrierOnboardingVehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    vehicle_type: str | None = None
    capacity_estimate: object | None = None
    plate_number: str | None = None
    body_type: str | None = None
    status: str
    validation_status: str
    updated_at: datetime
    documents: list[CarrierOnboardingDocumentResponse] = Field(default_factory=list)


class CarrierOnboardingDriverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    phone: str | None = None
    license_category: str | None = None
    status: str
    validation_status: str
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    updated_at: datetime
    documents: list[CarrierOnboardingDocumentResponse] = Field(default_factory=list)


class CarrierOnboardingEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: str
    occurred_at: datetime
    actor_type: str
    actor_id: str | None = None
    entity_type: str
    entity_id: str
    summary: str


class CarrierOnboardingCarrierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    contact_phone: str | None = None
    normalized_phone_number: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    truck_count: int | None = None
    truck_types: list[str]
    truck_body_type: str | None = None
    is_validated: bool
    validation_status: str
    validated_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    reviewed_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CarrierOnboardingStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    carrier_id: str
    status: str
    required_fields: list[str]
    missing_fields: list[str]
    submitted_at: datetime | None = None
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None


class CarrierCaptureProgressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: str | None = None
    captured_vehicle_count: int
    declared_vehicle_count: int


class CarrierOnboardingDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    carrier: CarrierOnboardingCarrierResponse
    onboarding: CarrierOnboardingStatusResponse
    vehicles: list[CarrierOnboardingVehicleResponse]
    drivers: list[CarrierOnboardingDriverResponse]
    documents: list[CarrierOnboardingDocumentResponse]
    capture_progress: CarrierCaptureProgressResponse
    events: list[CarrierOnboardingEventResponse]


class CarrierListItemResponse(BaseModel):
    id: str
    name: str
    contact_phone: str | None = None
    phone: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    truck_count: int | None = None
    truck_types: list[str]
    truck_body_type: str | None = None
    is_validated: bool
    validation_status: str
    onboarding_status: str | None = None
    missing_fields: list[str]
    vehicles_count: int
    documents_count: int
    pending_documents_count: int
    created_at: datetime
    updated_at: datetime


class CarrierCreateRequest(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    truck_count: int | None = None
    truck_types: list[str] | None = None
    truck_body_type: str | None = None


class CarrierUpdateRequest(CarrierCreateRequest):
    pass


class SuspendCarrierRequest(BaseModel):
    reason: str


class MarkCarrierInReviewRequest(BaseModel):
    notes: str | None = None


class VehicleCreateRequest(BaseModel):
    plate_number: str | None = None
    vehicle_type: str | None = None
    body_type: str | None = None
    capacity: Decimal | None = None
    status: str | None = None


class VehicleUpdateRequest(VehicleCreateRequest):
    pass


class DocumentCreateRequest(BaseModel):
    document_type: str
    entity_type: str = "carrier"
    entity_id: str | None = None
    external_uri: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    notes: str | None = None
    storage_uri: str | None = None
    valid_from: date | None = None
    expires_at: date | None = None
    supersedes_document_id: str | None = None


class DocumentUpdateRequest(DocumentCreateRequest):
    pass


class WhatsappAllowlistContactResponse(BaseModel):
    id: str
    phone_number: str
    normalized_phone_number: str
    label: str | None = None
    environment: str
    provider: str
    status: str
    notes: str | None = None
    created_by_user_id: str | None = None
    updated_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class WhatsappAllowlistCreateRequest(BaseModel):
    phone_number: str
    label: str | None = None
    environment: str = "all"
    provider: str = "all"
    status: str = "ACTIVE"
    notes: str | None = None


class WhatsappAllowlistUpdateRequest(WhatsappAllowlistCreateRequest):
    pass


class WhatsappAllowlistBlockRequest(BaseModel):
    reason: str


class ApproveCarrierRequest(BaseModel):
    notes: str | None = None


class RejectCarrierRequest(BaseModel):
    reason: str


class ApproveDocumentRequest(BaseModel):
    notes: str | None = None


class RejectDocumentRequest(BaseModel):
    reason: str


def _carrier_input_from_request(request: CarrierCreateRequest | CarrierUpdateRequest) -> CarrierMutationInput:
    return CarrierMutationInput(
        name=request.name,
        phone=request.phone,
        email=request.email,
        company_name=request.company_name,
        cuit=request.cuit,
        truck_count=request.truck_count,
        truck_types=request.truck_types,
        truck_body_type=request.truck_body_type,
    )


def _vehicle_input_from_request(request: VehicleCreateRequest | VehicleUpdateRequest) -> VehicleMutationInput:
    return VehicleMutationInput(
        plate_number=request.plate_number,
        vehicle_type=request.vehicle_type,
        body_type=request.body_type,
        capacity=request.capacity,
        status=request.status,
    )


def _document_input_from_request(
    request: DocumentCreateRequest | DocumentUpdateRequest,
) -> DocumentMutationInput:
    return DocumentMutationInput(
        document_type=request.document_type,
        external_uri=request.external_uri,
        file_name=request.file_name,
        mime_type=request.mime_type,
        notes=request.notes,
        storage_uri=request.storage_uri,
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        valid_from=request.valid_from,
        expires_at=request.expires_at,
        supersedes_document_id=request.supersedes_document_id,
    )


def _allowlist_input_from_request(
    request: WhatsappAllowlistCreateRequest | WhatsappAllowlistUpdateRequest,
) -> WhatsappAllowedContactInput:
    return WhatsappAllowedContactInput(
        phone_number=request.phone_number,
        label=request.label,
        environment=request.environment,
        provider=request.provider,
        status=request.status,
        notes=request.notes,
    )


@router.get("/overview", response_model=BackofficeOverviewResponse)
def get_overview(
    service: BackofficeService = Depends(get_backoffice_service),
    outbox_service: NotificationOutboxAdminService = Depends(get_notification_outbox_admin_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> BackofficeOverview:
    del operator
    overview = service.overview()
    failed = outbox_service.list_page(status="FAILED", limit=1, offset=0).total
    return replace(overview, failed_notifications=failed)


@router.get("/me", response_model=OperatorProfileResponse)
def get_operator_profile(
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> OperatorProfileResponse:
    return OperatorProfileResponse(user_id=operator.user_id, role=operator.role)


@router.get("/notification-outbox", response_model=NotificationOutboxResponse)
def list_notification_outbox(
    status_filter: NotificationOutboxStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: NotificationOutboxAdminService = Depends(get_notification_outbox_admin_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> NotificationOutboxResponse:
    del operator
    page = service.list_page(
        status=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )
    return NotificationOutboxResponse(
        counts=page.counts,
        items=[NotificationOutboxItemResponse(**item.__dict__) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/notification-outbox/{outbox_id}/reconcile",
    response_model=NotificationOutboxReconciliationResponse,
)
def reconcile_notification_outbox(
    outbox_id: str,
    request: NotificationOutboxReconciliationRequest,
    service: NotificationOutboxAdminService = Depends(get_notification_outbox_admin_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> NotificationOutboxReconciliationResponse:
    if operator.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    try:
        current_status = service.reconcile(
            outbox_id=outbox_id,
            resolution=request.resolution,
            evidence_reference=request.evidence_reference,
            operator_user_id=operator.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbox item not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return NotificationOutboxReconciliationResponse(id=outbox_id, status=current_status)


@router.put("/operators/{user_id}/role", response_model=OperatorRoleResponse)
def set_operator_role(
    user_id: str,
    request: OperatorRoleRequest,
    operator: AuthenticatedUser = Depends(require_admin_user),
    db_session=Depends(get_request_db_session),
) -> OperatorRoleResponse:
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Role management requires SQL storage")
    if user_id == get_settings().supabase_bootstrap_admin_user_id and request.role != "admin":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bootstrap administrator role is fixed")
    try:
        row = db_session.get(OperatorRoleRecord, user_id)
        if row is None:
            row = OperatorRoleRecord(
                user_id=user_id,
                role=request.role,
                assigned_by_user_id=operator.user_id,
            )
            db_session.add(row)
        else:
            if row.deleted_at is not None:
                row.deleted_at = None
            row.role = request.role
            row.assigned_by_user_id = operator.user_id
        SqlEventLogService(db_session).record(
            event_type="BACKOFFICE_ROLE_ASSIGNED",
            actor_type="ADMIN",
            actor_id=operator.user_id,
            entity_type="OperatorRole",
            entity_id=user_id,
            summary="Rol de backoffice asignado por administrador",
            payload={"role": request.role},
            source="backoffice_access_control",
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    return OperatorRoleResponse(
        user_id=row.user_id,
        role=row.role,
        assigned_by_user_id=row.assigned_by_user_id,
    )


@router.delete("/operators/{user_id}/role", status_code=status.HTTP_204_NO_CONTENT)
def revoke_operator_role(
    user_id: str,
    operator: AuthenticatedUser = Depends(require_admin_user),
    db_session=Depends(get_request_db_session),
) -> None:
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Role management requires SQL storage")
    if user_id == get_settings().supabase_bootstrap_admin_user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bootstrap administrator role is fixed")
    row = db_session.get(OperatorRoleRecord, user_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator role not found")
    try:
        row.deleted_at = datetime.now(UTC)
        SqlEventLogService(db_session).record(
            event_type="BACKOFFICE_ROLE_REVOKED",
            actor_type="ADMIN",
            actor_id=operator.user_id,
            entity_type="OperatorRole",
            entity_id=user_id,
            summary="Acceso de backoffice revocado por administrador",
            payload={"role": row.role},
            source="backoffice_access_control",
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
@router.get("/producers", response_model=list[ProducerListItemResponse])
def list_producers(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ProducerBackofficeService = Depends(get_producer_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ProducerListItemResponse]:
    del operator
    return [
        ProducerListItemResponse(**item.__dict__)
        for item in service.list_producers(search=search, limit=limit, offset=offset)
    ]


@router.get("/producers/page", response_model=ListPageResponse[ProducerListItemResponse])
def list_producer_page(
    search: str | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    service: ProducerBackofficeService = Depends(get_producer_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ListPageResponse[ProducerListItemResponse]:
    del operator
    all_rows = service.list_producers(search=search, limit=100_000, offset=0)
    return ListPageResponse(
        items=[ProducerListItemResponse(**item.__dict__) for item in all_rows[offset : offset + limit]],
        total=len(all_rows), limit=limit, offset=offset,
    )


@router.get("/producers/{producer_id}", response_model=ProducerDetailResponse)
def get_producer(
    producer_id: str,
    service: ProducerBackofficeService = Depends(get_producer_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ProducerDetailResponse:
    del operator
    try:
        detail = service.get_producer(producer_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producer not found") from exc
    return ProducerDetailResponse(
        producer=ProducerListItemResponse(**detail.producer.__dict__),
        email=detail.email,
        trust_notes=detail.trust_notes,
        validated_at=detail.validated_at,
        shipments=[ProducerShipmentItemResponse(**item.__dict__) for item in detail.shipments],
        offers=[ProducerOfferItemResponse(**item.__dict__) for item in detail.offers],
        trips=[ProducerTripItemResponse(**item.__dict__) for item in detail.trips],
        conversation_ids=detail.conversation_ids,
        events=[ProducerEventItemResponse(**item.__dict__) for item in detail.events],
    )

@router.get("/conversations/open", response_model=list[OpenConversationResponse])
def list_open_conversations(
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    needs_operator: bool | None = None,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[OpenConversationSummary]:
    del operator
    return service.list_open_conversations(limit=limit, offset=offset, needs_operator=needs_operator)


@router.get("/conversations/open/page", response_model=OpenConversationPageResponse)
def list_open_conversation_page(
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    needs_operator: bool | None = None,
    ambiguous_only: bool = False,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> OpenConversationPageResponse:
    del operator
    page = service.list_open_conversation_page(
        limit=limit, offset=offset, needs_operator=needs_operator, ambiguous_only=ambiguous_only
    )
    return OpenConversationPageResponse(
        items=[OpenConversationResponse(**item.__dict__) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/conversations/{conversation_session_id}/messages",
    response_model=list[ConversationMessageResponse],
)
def list_conversation_messages(
    conversation_session_id: str,
    service: AdminOpsService = Depends(get_admin_ops_service),
    backoffice_service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[ConversationMessageResponse]:
    del operator
    try:
        messages = service.list_messages_for_conversation(conversation_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from exc

    rows = [
        ConversationMessageResponse(
            id=message.id,
            conversation_session_id=message.conversation_session_id,
            direction=message.direction,
            sender_type=message.sender_type,
            message_type=message.message_type,
            # Text is available only in this operator-authenticated detail view. Media
            # payloads and provider identifiers stay out of the backoffice response.
            content=message.raw_content if message.message_type.lower() in {"text", "interactive"} else None,
            occurred_at=message.received_at or message.sent_at or message.created_at,
            test_run_id=message.test_run_id,
            qa_role=message.related_entity_ids.get("qaRole"),
            delivery_status=(
                "accepted_by_provider"
                if message.direction == "outbound"
                and message.provider.lower() not in {"mock", "mock_whatsapp", "local-demo-mock"}
                else None
            ),
        )
        for message in messages
    ]
    try:
        failures = backoffice_service.list_conversation_reply_failures(conversation_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from exc
    rows.extend(
        ConversationMessageResponse(
            id=event.event_id,
            conversation_session_id=conversation_session_id,
            direction="system",
            sender_type="SYSTEM",
            message_type="status",
            content="No se pudo enviar la respuesta automática.",
            occurred_at=event.occurred_at,
            test_run_id=event.test_run_id,
            delivery_status="failed",
        )
        for event in failures
    )
    rows.sort(key=lambda row: row.occurred_at)
    return rows


@router.get(
    "/conversations/{conversation_session_id}/messages/page",
    response_model=ConversationMessagePageResponse,
)
def page_conversation_messages(
    conversation_session_id: str,
    limit: int = Query(default=50, ge=1, le=50),
    cursor: str | None = None,
    direction: Literal["older", "newer"] = "older",
    service: AdminOpsService = Depends(get_admin_ops_service),
    backoffice_service: BackofficeService = Depends(get_backoffice_service),
    db_session: Session | None = Depends(get_request_db_session),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ConversationMessagePageResponse:
    del operator
    try:
        # Resolving the session first ensures a cursor cannot be used to read an
        # unrelated conversation.
        service._require_conversation(conversation_session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró la conversación") from exc

    boundary: tuple[datetime, str] | None = None
    if cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            boundary = (datetime.fromisoformat(payload["at"]), str(payload["id"]))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El cursor de mensajes no es válido") from exc

    if db_session is not None:
        message_time = func.coalesce(MessageRecord.received_at, MessageRecord.sent_at, MessageRecord.created_at)
        message_query = select(MessageRecord).where(MessageRecord.conversation_session_id == conversation_session_id)
        failure_query = select(EventLogRecord).where(
            EventLogRecord.entity_type == "ConversationSession",
            EventLogRecord.entity_id == conversation_session_id,
            EventLogRecord.event_type == "CONVERSATION_REPLY_FAILED",
        )
        if boundary:
            at, item_id = boundary
            comparator = or_(message_time < at, and_(message_time == at, MessageRecord.id < item_id)) if direction == "older" else or_(message_time > at, and_(message_time == at, MessageRecord.id > item_id))
            event_comparator = or_(EventLogRecord.occurred_at < at, and_(EventLogRecord.occurred_at == at, EventLogRecord.event_id < item_id)) if direction == "older" else or_(EventLogRecord.occurred_at > at, and_(EventLogRecord.occurred_at == at, EventLogRecord.event_id > item_id))
            message_query = message_query.where(comparator)
            failure_query = failure_query.where(event_comparator)
        ordering = (message_time.desc(), MessageRecord.id.desc()) if direction == "older" else (message_time.asc(), MessageRecord.id.asc())
        event_ordering = (EventLogRecord.occurred_at.desc(), EventLogRecord.event_id.desc()) if direction == "older" else (EventLogRecord.occurred_at.asc(), EventLogRecord.event_id.asc())
        messages = db_session.scalars(message_query.order_by(*ordering).limit(limit + 1)).all()
        failures = db_session.scalars(failure_query.order_by(*event_ordering).limit(limit + 1)).all()
        entries: list[ConversationMessageResponse] = [
            ConversationMessageResponse(
                id=item.id,
                conversation_session_id=conversation_session_id,
                direction=item.direction,
                sender_type=item.sender_type,
                message_type=item.message_type,
                content=item.raw_content if item.message_type.lower() in {"text", "interactive"} else None,
                occurred_at=item.received_at or item.sent_at or item.created_at,
                test_run_id=item.test_run_id,
                qa_role=(item.related_entity_ids or {}).get("qaRole"),
                delivery_status=("accepted_by_provider" if item.direction == "outbound" and item.provider.lower() not in {"mock", "mock_whatsapp", "local-demo-mock"} else None),
            ) for item in messages
        ]
        entries.extend(
            ConversationMessageResponse(
                id=item.event_id, conversation_session_id=conversation_session_id, direction="system",
                sender_type="SYSTEM", message_type="status", content="No se pudo enviar la respuesta automática.",
                occurred_at=item.occurred_at, test_run_id=item.test_run_id, delivery_status="failed",
            ) for item in failures
        )
        source_has_more = len(messages) > limit or len(failures) > limit
    else:
        messages = service.list_messages_for_conversation(conversation_session_id)
        failures = backoffice_service.list_conversation_reply_failures(conversation_session_id)
        entries = [
            ConversationMessageResponse(
                id=item.id, conversation_session_id=conversation_session_id, direction=item.direction,
                sender_type=item.sender_type, message_type=item.message_type,
                content=item.raw_content if item.message_type.lower() in {"text", "interactive"} else None,
                occurred_at=item.received_at or item.sent_at or item.created_at,
                test_run_id=item.test_run_id, qa_role=(item.related_entity_ids or {}).get("qaRole"),
                delivery_status=("accepted_by_provider" if item.direction == "outbound" and item.provider.lower() not in {"mock", "mock_whatsapp", "local-demo-mock"} else None),
            ) for item in messages
        ]
        entries.extend(
            ConversationMessageResponse(
                id=item.event_id, conversation_session_id=conversation_session_id, direction="system",
                sender_type="SYSTEM", message_type="status", content="No se pudo enviar la respuesta automática.",
                occurred_at=item.occurred_at, test_run_id=item.test_run_id, delivery_status="failed",
            ) for item in failures
        )
        entries.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
        if boundary:
            if direction == "older":
                entries = [item for item in entries if (item.occurred_at, item.id) < boundary]
            else:
                entries = [item for item in entries if (item.occurred_at, item.id) > boundary]
        source_has_more = len(entries) > limit

    entries.sort(key=lambda item: (item.occurred_at, item.id), reverse=(direction == "older"))
    has_more = source_has_more or len(entries) > limit
    page = entries[:limit]
    if direction == "older":
        page.reverse()
    next_item = page[0] if direction == "older" and has_more else page[-1] if page and has_more else None
    latest_item = page[-1] if page else None
    return ConversationMessagePageResponse(
        items=page,
        next_cursor=_message_cursor(next_item) if next_item else None,
        latest_cursor=_message_cursor(latest_item) if latest_item else None,
        has_more=has_more,
    )


def _message_cursor(item: ConversationMessageResponse) -> str:
    value = json.dumps({"at": item.occurred_at.isoformat(), "id": item.id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@router.get("/shipments/unassigned", response_model=list[UnassignedShipmentResponse])
def list_unassigned_shipments(
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[UnassignedShipmentSummary]:
    del operator
    return service.list_unassigned_shipments()


@router.get("/shipments/unassigned/page", response_model=ListPageResponse[UnassignedShipmentResponse])
def list_unassigned_shipment_page(
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ListPageResponse[UnassignedShipmentResponse]:
    del operator
    all_rows = service.list_unassigned_shipments()
    return ListPageResponse(
        items=[UnassignedShipmentResponse(**item.__dict__) for item in all_rows[offset : offset + limit]],
        total=len(all_rows), limit=limit, offset=offset,
    )


@router.get("/shipments/{shipment_id}", response_model=ShipmentDetailResponse)
def get_shipment_detail(
    shipment_id: str,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ShipmentDetail:
    del operator
    try:
        return service.get_shipment_detail(shipment_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment request not found") from exc


@router.patch("/shipments/{shipment_id}", response_model=ShipmentDetailResponse)
def update_shipment(
    shipment_id: str,
    request: ShipmentMutationRequest,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ShipmentDetail:
    try:
        return service.update_shipment(
            shipment_id,
            ShipmentMutationInput(**request.model_dump(exclude_unset=True)),
            operator_user_id=operator.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment request not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/shipments/{shipment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shipment(
    shipment_id: str,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> None:
    try:
        service.delete_shipment(shipment_id, operator_user_id=operator.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment request not found") from exc


@router.post("/shipments/{shipment_id}/manual-interest", response_model=ManualShipmentInterestResponse)
def register_manual_interest(
    shipment_id: str,
    request: ManualShipmentCarrierActionRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ManualShipmentInterestResponse:
    try:
        result = service.register_manual_interest(
            shipment_request_id=shipment_id,
            carrier_id=request.carrier_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        detail = "Carrier not found" if str(exc).strip("'").startswith("car_") else "Shipment request not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ManualShipmentInterestResponse(
        shipment_id=result.shipment.id,
        shipment_status=result.shipment.status,
        trip_offer_id=result.trip_offer.id,
        trip_offer_status=result.trip_offer.status,
        carrier_id=result.trip_offer.carrier_id,
        carrier_notification_status=result.carrier_notification.status if result.carrier_notification else None,
        producer_notification_status=result.producer_notification.status if result.producer_notification else None,
        event_types=[event.event_type for event in result.events],
    )


@router.post("/shipments/{shipment_id}/manual-assign", response_model=ManualShipmentAssignmentResponse)
def assign_shipment_manually(
    shipment_id: str,
    request: ManualShipmentCarrierActionRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ManualShipmentAssignmentResponse:
    try:
        result = service.assign_shipment_to_carrier_manually(
            shipment_request_id=shipment_id,
            carrier_id=request.carrier_id,
            operator_user_id=operator.user_id,
            confirmation_notes=request.notes,
            interest_notes=request.notes,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        detail = "Carrier not found" if str(exc).strip("'").startswith("car_") else "Shipment request not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    except AdminOpsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ManualShipmentAssignmentResponse(
        shipment_id=result.shipment.id,
        shipment_status=result.shipment.status,
        trip_offer_id=result.trip_offer.id,
        assignment_id=result.assignment.id,
        assignment_status=result.assignment.status,
        trip_id=result.trip.id,
        trip_status=result.trip.status,
        carrier_id=result.assignment.carrier_id,
        carrier_notification_status=result.carrier_notification.status if result.carrier_notification else None,
        producer_notification_status=result.producer_notification.status if result.producer_notification else None,
        event_types=[event.event_type for event in result.events],
    )


@router.get("/trips", response_model=list[TripResponse])
def list_trips(
    status: str | None = None,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[TripSummary]:
    del operator
    return service.list_trips(status=status)


@router.get("/trips/page", response_model=ListPageResponse[TripResponse])
def list_trip_page(
    status: str | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ListPageResponse[TripResponse]:
    del operator
    all_rows = service.list_trips(status=status)
    return ListPageResponse(
        items=[TripResponse(**item.__dict__) for item in all_rows[offset : offset + limit]],
        total=len(all_rows), limit=limit, offset=offset,
    )


@router.patch("/trips/{trip_id}", response_model=TripResponse)
def update_trip(
    trip_id: str,
    request: TripMutationRequest,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TripSummary:
    try:
        return service.update_trip(
            trip_id,
            TripMutationInput(**request.model_dump(exclude_unset=True)),
            operator_user_id=operator.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/trips/{trip_id}/crew", response_model=TripCrewAssignmentResponse)
def assign_trip_crew(
    trip_id: str,
    request: TripCrewAssignmentRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TripCrewAssignmentResponse:
    try:
        trip = service.assign_trip_crew(
            trip_id=trip_id,
            driver_id=request.driver_id,
            vehicle_id=request.vehicle_id,
            operator_user_id=operator.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip, driver, or vehicle not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TripCrewAssignmentResponse(
        trip_id=trip.id,
        carrier_id=trip.carrier_id,
        driver_id=trip.driver_id or "",
        vehicle_id=trip.vehicle_id or "",
        trip_status=trip.status,
    )


@router.delete("/trips/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(
    trip_id: str,
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> None:
    try:
        service.delete_trip(trip_id, operator_user_id=operator.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc


def _trip_action_response(result: TripStatusUpdateResult) -> TripOperatorActionResponse:
    if result.shipment is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Trip is missing shipment context")
    return TripOperatorActionResponse(
        shipment_id=result.shipment.id,
        shipment_status=result.shipment.status,
        trip_id=result.trip.id,
        trip_status=result.trip.status,
        carrier_notification_status=result.carrier_notification.status if result.carrier_notification else None,
        producer_notification_status=result.producer_notification.status if result.producer_notification else None,
        event_types=[event.event_type for event in result.events],
    )


@router.post("/trips/{trip_id}/start", response_model=TripOperatorActionResponse)
def start_trip(
    trip_id: str,
    request: TripOperatorActionRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TripOperatorActionResponse:
    try:
        result = service.start_trip(
            trip_id=trip_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _trip_action_response(result)


@router.post("/trips/{trip_id}/mark-in-transit", response_model=TripOperatorActionResponse)
def mark_trip_in_transit(
    trip_id: str,
    request: TripOperatorActionRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TripOperatorActionResponse:
    try:
        result = service.mark_trip_in_transit(
            trip_id=trip_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _trip_action_response(result)


@router.post("/trips/{trip_id}/complete", response_model=TripOperatorActionResponse)
def complete_trip(
    trip_id: str,
    request: TripOperatorActionRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TripOperatorActionResponse:
    try:
        result = service.complete_trip(
            trip_id=trip_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _trip_action_response(result)


@router.post("/trips/{trip_id}/cancel", response_model=TripOperatorActionResponse)
def cancel_trip(
    trip_id: str,
    request: TripOperatorActionRequest,
    service: AdminOpsService = Depends(get_admin_ops_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> TripOperatorActionResponse:
    if not request.reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="reason is required")
    try:
        result = service.cancel_trip(
            trip_id=trip_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
            notify_parties=True,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _trip_action_response(result)


@router.get("/route-availabilities", response_model=list[RouteAvailabilityResponse])
def list_route_availabilities(
    carrier_id: str | None = None,
    test_run_id: str | None = None,
    status_filter: Literal["DRAFT", "ACTIVE", "COMMITTED", "CLOSED", "CANCELLED", "EXPIRED"] | None = Query(default=None, alias="status"),
    repository=Depends(get_route_availability_repository),
    event_log=Depends(get_event_log_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[RouteAvailability]:
    del operator
    rows = repository.list()
    for item in rows:
        if item.expire_if_due():
            repository.save(item)
            event_log.record(
                event_type="ROUTE_AVAILABILITY_EXPIRED",
                actor_type="System",
                entity_type="RouteAvailability",
                entity_id=item.id,
                test_run_id=item.test_run_id,
                summary="Disponibilidad vencida al finalizar su ventana declarada",
                related_entity_ids={"carrierId": item.carrier_id},
                previous_state="ACTIVE",
                new_state="EXPIRED",
                source="backoffice_read",
            )
    return [
        item for item in rows
        if (carrier_id is None or item.carrier_id == carrier_id)
        and (test_run_id is None or item.test_run_id == test_run_id)
        and (status_filter is None or item.status == status_filter)
    ]


@router.get("/route-availabilities/page", response_model=ListPageResponse[RouteAvailabilityResponse])
def list_route_availability_page(
    carrier_id: str | None = None,
    test_run_id: str | None = None,
    status_filter: Literal["DRAFT", "ACTIVE", "COMMITTED", "CLOSED", "CANCELLED", "EXPIRED"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    repository=Depends(get_route_availability_repository),
    event_log=Depends(get_event_log_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ListPageResponse[RouteAvailabilityResponse]:
    all_rows = list_route_availabilities(
        carrier_id=carrier_id, test_run_id=test_run_id, status_filter=status_filter,
        repository=repository, event_log=event_log, operator=operator,
    )
    return ListPageResponse(
        items=[RouteAvailabilityResponse.model_validate(item) for item in all_rows[offset : offset + limit]],
        total=len(all_rows), limit=limit, offset=offset,
    )


@router.post("/route-availabilities", response_model=RouteAvailabilityResponse, status_code=status.HTTP_201_CREATED)
def create_route_availability(
    request: RouteAvailabilityCreateRequest,
    repository=Depends(get_route_availability_repository),
    event_log=Depends(get_event_log_service),
    carrier_service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> RouteAvailability:
    carrier_exists = any(item.id == request.carrier_id for item in carrier_service.list_carriers(limit=10000))
    if not carrier_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found")
    try:
        availability = RouteAvailability(
            carrier_id=request.carrier_id,
            test_run_id=request.test_run_id,
            origin=request.origin.strip(),
            destination=request.destination.strip(),
            stops=[item.strip() for item in request.stops],
            window_start=request.window_start,
            window_end=request.window_end,
            capacity=request.capacity,
            capacity_unit=request.capacity_unit,
            cargo_types=request.cargo_types,
            equipment_types=request.equipment_types,
            declared_by_user_id=operator.user_id,
        )
        saved = repository.add(availability)
        event_log.record(
            event_type="ROUTE_AVAILABILITY_CREATED",
            actor_type="Operator",
            actor_id=operator.user_id,
            entity_type="RouteAvailability",
            entity_id=saved.id,
            test_run_id=saved.test_run_id,
            summary="Disponibilidad de recorrido creada como borrador",
            related_entity_ids={"carrierId": saved.carrier_id},
            new_state=saved.status,
            payload={
                "origin": saved.origin,
                "destination": saved.destination,
                "stops": saved.stops,
                "window_start": saved.window_start.isoformat() if saved.window_start else None,
                "window_end": saved.window_end.isoformat() if saved.window_end else None,
                "capacity": str(saved.capacity) if saved.capacity is not None else None,
                "capacity_unit": saved.capacity_unit,
                "cargo_types": saved.cargo_types,
                "equipment_types": saved.equipment_types,
            },
            source="backoffice",
        )
        return saved
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/route-availabilities/{availability_id}/status", response_model=RouteAvailabilityResponse)
def update_route_availability_status(
    availability_id: str,
    request: RouteAvailabilityStatusRequest,
    repository=Depends(get_route_availability_repository),
    event_log=Depends(get_event_log_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> RouteAvailability:
    item = repository.get(availability_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability not found")
    allowed = {"DRAFT": {"ACTIVE", "CANCELLED"}, "ACTIVE": {"CLOSED", "CANCELLED"}}
    if request.status not in allowed.get(item.status, set()):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid availability state transition")
    previous_status = item.status
    item.status = request.status
    saved = repository.save(item)
    event_log.record(
        event_type=f"ROUTE_AVAILABILITY_{request.status}",
        actor_type="Operator",
        actor_id=operator.user_id,
        entity_type="RouteAvailability",
        entity_id=saved.id,
        test_run_id=saved.test_run_id,
        summary=f"Disponibilidad de recorrido: {previous_status} → {request.status}",
        related_entity_ids={"carrierId": saved.carrier_id},
        previous_state=previous_status,
        new_state=request.status,
        source="backoffice",
    )
    return saved


@router.post("/route-availabilities/match", response_model=list[RouteAvailabilityMatchResponse])
def match_route_availabilities(
    request: RouteMatchRequest,
    repository=Depends(get_route_availability_repository),
    event_log=Depends(get_event_log_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[RouteAvailabilityMatchResponse]:
    del operator
    matches = []
    for item in repository.list():
        if item.expire_if_due():
            repository.save(item)
            event_log.record(
                event_type="ROUTE_AVAILABILITY_EXPIRED",
                actor_type="System",
                entity_type="RouteAvailability",
                entity_id=item.id,
                test_run_id=item.test_run_id,
                summary="Disponibilidad vencida al finalizar su ventana declarada",
                related_entity_ids={"carrierId": item.carrier_id},
                previous_state="ACTIVE",
                new_state="EXPIRED",
                source="backoffice_match",
            )
            continue
        match = match_route_availability(
            item,
            origin=request.origin,
            destination=request.destination,
            shipment_at=request.shipment_at,
            cargo_type=request.cargo_type,
            quantity=request.quantity,
            quantity_unit=request.quantity_unit,
            equipment_type=request.equipment_type,
        )
        if match:
            matches.append(RouteAvailabilityMatchResponse(
                availability=item,
                segment_origin=match.segment_origin,
                segment_destination=match.segment_destination,
                reasons=list(match.reasons),
            ))
    return matches


@router.get("/carriers", response_model=list[CarrierListItemResponse])
def list_all_carriers(
    validation_status: str | None = None,
    pending_only: bool = False,
    onboarding_pending_only: bool = False,
    is_validated: bool | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[CarrierSummary]:
    del operator
    return service.list_carriers(
        validation_status=validation_status,
        pending_only=pending_only,
        onboarding_pending_only=onboarding_pending_only,
        is_validated=is_validated,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/carriers/page", response_model=ListPageResponse[CarrierListItemResponse])
def list_carrier_page(
    validation_status: str | None = None,
    pending_only: bool = False,
    onboarding_pending_only: bool = False,
    is_validated: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> ListPageResponse[CarrierListItemResponse]:
    del operator
    filters = dict(
        validation_status=validation_status, pending_only=pending_only,
        onboarding_pending_only=onboarding_pending_only, is_validated=is_validated, search=search,
    )
    all_rows: list[CarrierSummary] = []
    batch_offset = 0
    while True:
        batch = service.list_carriers(**filters, limit=200, offset=batch_offset)
        all_rows.extend(batch)
        if len(batch) < 200:
            break
        batch_offset += len(batch)
    return ListPageResponse(
        items=[CarrierListItemResponse(**item.__dict__) for item in all_rows[offset : offset + limit]],
        total=len(all_rows), limit=limit, offset=offset,
    )


@router.get("/carriers/pending-approval", response_model=list[PendingCarrierResponse])
def list_pending_carriers(
    service: BackofficeService = Depends(get_backoffice_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[PendingCarrierSummary]:
    del operator
    return service.list_pending_carriers()


@router.get("/carriers/{carrier_id}/documents", response_model=list[CarrierOnboardingDocumentResponse])
def list_carrier_documents(
    carrier_id: str,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    del operator
    try:
        return service.list_documents(carrier_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc


@router.get("/carriers/{carrier_id}/drivers", response_model=list[CarrierOnboardingDriverResponse])
def list_carrier_drivers(
    carrier_id: str,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    del operator
    try:
        return service.list_drivers(carrier_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc


@router.post(
    "/carriers/{carrier_id}/drivers",
    response_model=CarrierOnboardingDriverResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_carrier_driver(
    carrier_id: str,
    request: DriverCreateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.create_driver(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            data=DriverMutationInput(**request.model_dump()),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/carriers/{carrier_id}/documents/{document_id}/content")
def download_carrier_document(
    carrier_id: str,
    document_id: str,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> FileResponse:
    try:
        file_path, document = service.resolve_carrier_document_file(
            carrier_id=carrier_id,
            document_id=document_id,
            storage_root=get_settings().media_storage_dir,
            operator_user_id=operator.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc

    filename = Path(document.file_name or file_path.name).name or file_path.name
    return FileResponse(
        path=file_path,
        media_type=document.mime_type or "application/octet-stream",
        filename=filename,
        content_disposition_type="attachment",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/carriers",
    response_model=CarrierOnboardingDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_carrier(
    request: CarrierCreateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    try:
        return service.create_carrier(
            operator_user_id=operator.user_id,
            data=_carrier_input_from_request(request),
        )
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch(
    "/carriers/{carrier_id}",
    response_model=CarrierOnboardingDetailResponse,
)
def update_carrier(
    carrier_id: str,
    request: CarrierUpdateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    try:
        return service.update_carrier(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            data=_carrier_input_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/carrier-onboarding/pending",
    response_model=list[CarrierOnboardingPendingResponse],
)
def list_pending_carrier_onboarding(
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[CarrierOnboardingPendingSummary]:
    del operator
    return service.list_pending()


@router.get(
    "/carriers/{carrier_id}/onboarding",
    response_model=CarrierOnboardingDetailResponse,
)
def get_carrier_onboarding_detail(
    carrier_id: str,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    del operator
    try:
        return service.detail(carrier_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc


@router.post(
    "/carriers/{carrier_id}/approve",
    response_model=CarrierOnboardingDetailResponse,
)
def approve_carrier(
    carrier_id: str,
    request: ApproveCarrierRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    try:
        return service.approve_carrier(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/suspend",
    response_model=CarrierOnboardingDetailResponse,
)
def suspend_carrier(
    carrier_id: str,
    request: SuspendCarrierRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    try:
        return service.suspend_carrier(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/mark-in-review",
    response_model=CarrierOnboardingDetailResponse,
)
def mark_carrier_in_review(
    carrier_id: str,
    request: MarkCarrierInReviewRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    try:
        return service.mark_in_review(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/reject",
    response_model=CarrierOnboardingDetailResponse,
)
def reject_carrier(
    carrier_id: str,
    request: RejectCarrierRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> CarrierOnboardingDetail:
    try:
        return service.reject_carrier(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/vehicles",
    response_model=CarrierOnboardingVehicleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_carrier_vehicle(
    carrier_id: str,
    request: VehicleCreateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.create_vehicle(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            data=_vehicle_input_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch(
    "/carriers/{carrier_id}/vehicles/{vehicle_id}",
    response_model=CarrierOnboardingVehicleResponse,
)
def update_carrier_vehicle(
    carrier_id: str,
    vehicle_id: str,
    request: VehicleUpdateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.update_vehicle(
            carrier_id=carrier_id,
            vehicle_id=vehicle_id,
            operator_user_id=operator.user_id,
            data=_vehicle_input_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/carriers/{carrier_id}/vehicles/{vehicle_id}",
    response_model=CarrierOnboardingVehicleResponse,
)
def delete_carrier_vehicle(
    carrier_id: str,
    vehicle_id: str,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.delete_vehicle(
            carrier_id=carrier_id,
            vehicle_id=vehicle_id,
            operator_user_id=operator.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/vehicles/{vehicle_id}/approve",
    response_model=CarrierOnboardingVehicleResponse,
)
def approve_carrier_vehicle(
    carrier_id: str,
    vehicle_id: str,
    request: DriverReviewRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.approve_vehicle(
            carrier_id=carrier_id,
            vehicle_id=vehicle_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/drivers/{driver_id}/approve",
    response_model=CarrierOnboardingDriverResponse,
)
def approve_carrier_driver(
    carrier_id: str,
    driver_id: str,
    request: DriverReviewRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.approve_driver(
            carrier_id=carrier_id,
            driver_id=driver_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/drivers/{driver_id}/reject",
    response_model=CarrierOnboardingDriverResponse,
)
def reject_carrier_driver(
    carrier_id: str,
    driver_id: str,
    request: DriverRejectRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.reject_driver(
            carrier_id=carrier_id,
            driver_id=driver_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/documents",
    response_model=CarrierOnboardingDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_carrier_document(
    carrier_id: str,
    request: DocumentCreateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> Document:
    try:
        return service.create_document(
            carrier_id=carrier_id,
            operator_user_id=operator.user_id,
            data=_document_input_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carrier not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch(
    "/carriers/{carrier_id}/documents/{document_id}",
    response_model=CarrierOnboardingDocumentResponse,
)
def update_carrier_document(
    carrier_id: str,
    document_id: str,
    request: DocumentUpdateRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> Document:
    try:
        return service.update_document(
            carrier_id=carrier_id,
            document_id=document_id,
            operator_user_id=operator.user_id,
            data=_document_input_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/whatsapp-allowlist",
    response_model=list[WhatsappAllowlistContactResponse],
)
def list_whatsapp_allowlist_contacts(
    status: str | None = None,
    environment: str | None = None,
    provider: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    service: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> list[WhatsappAllowedContactSummary]:
    del operator
    return service.list_contacts(
        status=status,
        environment=environment,
        provider=provider,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/whatsapp-allowlist",
    response_model=WhatsappAllowlistContactResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_whatsapp_allowlist_contact(
    request: WhatsappAllowlistCreateRequest,
    service: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.create_contact(
            operator_user_id=operator.user_id,
            data=_allowlist_input_from_request(request),
        )
    except WhatsappAllowlistError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch(
    "/whatsapp-allowlist/{contact_id}",
    response_model=WhatsappAllowlistContactResponse,
)
def update_whatsapp_allowlist_contact(
    contact_id: str,
    request: WhatsappAllowlistUpdateRequest,
    service: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.update_contact(
            contact_id=contact_id,
            operator_user_id=operator.user_id,
            data=_allowlist_input_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allowlist contact not found") from exc
    except WhatsappAllowlistError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/whatsapp-allowlist/{contact_id}/block",
    response_model=WhatsappAllowlistContactResponse,
)
def block_whatsapp_allowlist_contact(
    contact_id: str,
    request: WhatsappAllowlistBlockRequest,
    service: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.block_contact(
            contact_id=contact_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allowlist contact not found") from exc
    except WhatsappAllowlistError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/whatsapp-allowlist/{contact_id}/reactivate",
    response_model=WhatsappAllowlistContactResponse,
)
def reactivate_whatsapp_allowlist_contact(
    contact_id: str,
    service: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.reactivate_contact(contact_id=contact_id, operator_user_id=operator.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allowlist contact not found") from exc


@router.post(
    "/whatsapp-allowlist/{contact_id}/disable",
    response_model=WhatsappAllowlistContactResponse,
)
def disable_whatsapp_allowlist_contact(
    contact_id: str,
    service: WhatsappAllowlistService = Depends(get_whatsapp_allowlist_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
):
    try:
        return service.disable_contact(contact_id=contact_id, operator_user_id=operator.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allowlist contact not found") from exc


@router.post(
    "/carriers/{carrier_id}/documents/{document_id}/approve",
    response_model=CarrierOnboardingDocumentResponse,
)
def approve_carrier_document(
    carrier_id: str,
    document_id: str,
    request: ApproveDocumentRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> Document:
    try:
        return service.approve_document(
            carrier_id=carrier_id,
            document_id=document_id,
            operator_user_id=operator.user_id,
            notes=request.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/carriers/{carrier_id}/documents/{document_id}/reject",
    response_model=CarrierOnboardingDocumentResponse,
)
def reject_carrier_document(
    carrier_id: str,
    document_id: str,
    request: RejectDocumentRequest,
    service: CarrierOnboardingService = Depends(get_carrier_onboarding_service),
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> Document:
    try:
        return service.reject_document(
            carrier_id=carrier_id,
            document_id=document_id,
            operator_user_id=operator.user_id,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except CarrierOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
