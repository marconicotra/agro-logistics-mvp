from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from app.api.dependencies import get_app_state, get_request_db_session, get_notification_service, get_backoffice_sandbox_location_provider, require_operator_user
from app.application.routing_factory import build_routing
from app.core.config import get_settings
from app.domain.routing import coordinates
from app.infrastructure.db.notification_outbox import SqlNotificationOutboxProvider

router = APIRouter(prefix="/api/v1/backoffice", tags=["Recorridos y seguimiento"])


def get_routing(db=Depends(get_request_db_session), notifications=Depends(get_notification_service)):
    service = build_routing(session=db, state=get_app_state(), notifications=notifications)
    if db is None:
        yield service
    elif db.in_transaction():
        yield service
        db.commit()
    else:
        with db.begin():
            yield service


class PreferenceInput(BaseModel):
    origin: str = Field(min_length=1, max_length=150)
    destination: str = Field(min_length=1, max_length=150)
    stops: list[str] = Field(default_factory=list, max_length=10)
    cargo_categories: list[Literal['LIVESTOCK', 'GRAIN']] = Field(default_factory=list)
    cargo_types: list[str] = Field(default_factory=list, max_length=30)
    equipment_types: list[str] = Field(default_factory=list, max_length=10)
    active: bool = True
    opt_in: bool = False


class PointInput(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


def bad_request(call):
    try:
        return call()
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from None


@router.get('/routing/config')
def routing_config(operator=Depends(require_operator_user)):
    return {"google_maps_browser_key": get_settings().google_maps_browser_key, "route_provider_configured": bool(get_settings().google_routes_api_key)}


@router.get('/carriers/{carrier_id}/route-preferences')
def preferences(carrier_id: str, test_run_id: str | None = None, limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0), service=Depends(get_routing), operator=Depends(require_operator_user)):
    rows = service.store.list('preference', test_run_id, entity_id=carrier_id)
    return {"items": [asdict(e) for e in rows[offset:offset+limit]], "total": len(rows)}


@router.post('/carriers/{carrier_id}/route-preferences')
def create_preference(carrier_id: str, body: PreferenceInput, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    return bad_request(lambda: asdict(service.save_preference(carrier_id, body.model_dump(), test_run_id, actor=operator.user_id)))


@router.put('/carriers/{carrier_id}/route-preferences/{preference_id}')
def edit_preference(carrier_id: str, preference_id: str, body: PreferenceInput, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    return bad_request(lambda: asdict(service.save_preference(carrier_id, body.model_dump(), test_run_id, preference_id, operator.user_id)))


@router.get('/shipments/{shipment_id}/dispatch')
def dispatch_status(shipment_id: str, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    shipment = service.shipments.get(shipment_id)
    if not shipment or shipment.test_run_id != test_run_id:
        raise HTTPException(404, detail='Carga no encontrada en este contexto')
    decisions = [asdict(e) for e in service.store.list('dispatch', test_run_id, entity_id=shipment_id)]
    if hasattr(service.store, 'session'):
        from sqlalchemy import select
        from app.infrastructure.db.models import NotificationOutboxRecord
        rows = service.store.session.scalars(select(NotificationOutboxRecord).where(NotificationOutboxRecord.entity_id == shipment_id, NotificationOutboxRecord.test_run_id == test_run_id)).all()
        for decision in decisions:
            outbox = next((r for r in rows if r.message_payload.get('metadata', {}).get('carrier_id') == decision['data'].get('carrier_id')), None)
            if outbox:
                decision['status'] = {'PENDING':'QUEUED','PROCESSING':'QUEUED','RETRY':'QUEUED'}.get(outbox.status,outbox.status)
    return {"equipment_type": shipment.required_equipment_type, "decisions": decisions, "jobs": [asdict(e) for e in service.store.list('job', test_run_id, entity_id=shipment_id)]}


@router.get('/trips/{trip_id}/tracking')
def tracking(trip_id: str, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    result = bad_request(lambda: service.tracking_view(trip_id, test_run_id))
    service.events.record(event_type='TRIP_TRACKING_ACCESSED', actor_type='Operator', actor_id=operator.user_id,
        entity_type='Trip', entity_id=trip_id, test_run_id=test_run_id, summary='Operador consultó seguimiento del viaje', source='backoffice')
    return result


@router.post('/trips/{trip_id}/tracking/confirm-driver')
def confirm_driver(trip_id: str, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    entry = bad_request(lambda: service.confirm_driver(trip_id, test_run_id, operator.user_id))
    trip = service.trip(trip_id, test_run_id)
    if trip.status == 'IN_TRANSIT':
        service.transit(trip)
    return {"confirmed": True, "driver_id": entry.data['driver_id']}


@router.post('/trips/{trip_id}/tracking/request-location')
def request_location(trip_id: str, test_run_id: str | None = None, service=Depends(get_routing),
                     db=Depends(get_request_db_session), sandbox_provider=Depends(get_backoffice_sandbox_location_provider),
                     operator=Depends(require_operator_user)):
    if sandbox_provider is not None:
        if db is None:
            raise HTTPException(status_code=503, detail='Los pedidos Sandbox requieren persistencia SQL')
        # Keep the rest of the local backoffice on its mock provider. Only this
        # explicit QA action queues with the same Kapso account as the worker.
        service.provider = SqlNotificationOutboxProvider(provider=sandbox_provider, session=db)
    return bad_request(lambda: asdict(service.request_checkpoint(trip_id, test_run_id, request_key=str(uuid4()))))


@router.put('/shipments/{shipment_id}/locations/{side}')
def set_point(shipment_id: str, side: Literal['origin','destination'], body: PointInput, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    shipment = service.shipments.get(shipment_id)
    if not shipment or shipment.test_run_id != test_run_id:
        raise HTTPException(404, detail='Carga no encontrada en este contexto')
    loc = service.locations.get(getattr(shipment, side + '_location_id'))
    if not loc:
        raise HTTPException(409, detail='Falta la localidad de la carga')
    loc.latitude, loc.longitude = coordinates(body.latitude, body.longitude)
    loc.coordinate_source, loc.coordinate_precision = 'OPERATOR_CONFIRMED', 'CONFIRMED_ACCESS'
    service.locations.save(loc)
    service.events.record(event_type='SHIPMENT_LOCATION_CONFIRMED', actor_type='Operator', actor_id=operator.user_id,
        entity_type='ShipmentRequest', entity_id=shipment_id, test_run_id=test_run_id, summary='Acceso de carga confirmado en mapa', payload={'side':side}, source='backoffice')
    return {"confirmed": True}


@router.post('/trips/{trip_id}/tracking/route')
def refresh_route(trip_id: str, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    def calculate():
        from app.application.routing import key
        from app.domain.routing import aware
        from datetime import timedelta
        trip = service.trip(trip_id, test_run_id)
        tracking = service.store.get(key('tracking', trip.id))
        if not tracking:
            raise ValueError('Confirmá primero el WhatsApp del chofer asignado')
        points = service._route_points(trip)
        tracking.data['points'] = points
        route = service.calculate(tracking, points)
        if trip.status == 'IN_TRANSIT':
            start = datetime.fromisoformat(tracking.data.get('began_at', service.clock().isoformat()))
            service.schedule(trip.id, test_run_id, 'CHECKPOINT', aware(start)+timedelta(seconds=route['duration_seconds']/2), suffix='MIDDLE', stage='MIDDLE')
            service.schedule(trip.id, test_run_id, 'CHECKPOINT', aware(start)+timedelta(seconds=route['duration_seconds']), suffix='ARRIVAL', stage='ARRIVAL')
        return {'calculated': True}
    return bad_request(calculate)


class EquipmentRequirement(BaseModel):
    equipment_type: str | None = Field(default=None, max_length=100)


@router.put('/shipments/{shipment_id}/route-requirements')
def route_requirements(shipment_id: str, body: EquipmentRequirement, test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    from app.domain.equipment import normalize_equipment_or_declared
    shipment = service.shipments.get(shipment_id)
    if not shipment or shipment.test_run_id != test_run_id:
        raise HTTPException(404, detail='Carga no encontrada en este contexto')
    if shipment.status not in {'DRAFT','INCOMPLETE','VALIDATED','PUBLISHED','MATCHING'}:
        raise HTTPException(409, detail='La carga asignada requiere revisión de soporte para cambiar requisitos')
    shipment.required_equipment_type = normalize_equipment_or_declared(body.equipment_type)
    service.shipments.save(shipment)
    service.events.record(event_type='SHIPMENT_EQUIPMENT_REQUIREMENT_UPDATED', actor_type='Operator', actor_id=operator.user_id,entity_type='ShipmentRequest',entity_id=shipment.id,test_run_id=test_run_id,summary='Equipo requerido actualizado para la carga',source='backoffice')
    return {'equipment_type':shipment.required_equipment_type}


@router.get('/routing/status')
def routing_status(test_run_id: str | None = None, service=Depends(get_routing), operator=Depends(require_operator_user)):
    jobs = service.store.list('job', test_run_id)
    controls = service.store.list('checkpoint', test_run_id)
    return {'pending_jobs':sum(j.status == 'PENDING' for j in jobs), 'jobs_requiring_review':sum(j.status == 'REVIEW' for j in jobs), 'overdue_location_controls':sum(c.status == 'OVERDUE' for c in controls)}
