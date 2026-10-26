from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.api.dependencies import AppState
from app.application.notifications import NotificationService
from app.application.routing_factory import build_routing
from app.domain.models import Carrier, ConversationSession, Driver, Location, ShipmentRequest, Trip, TripOffer
from app.domain.route_availability import RouteAvailability
from app.infrastructure.adapters.google_routes import GoogleRoutes, RouteUnavailable, maps_url
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider

NOW = datetime(2030, 1, 10, 12, tzinfo=UTC)


class FakeMaps:
    def calculate(self, points):
        return {'distance_meters': 100000, 'duration_seconds': 3600, 'polyline': '_p~iF~ps|U_ulLnnqC_mqNvxq`@'}


@pytest.fixture
def routing(monkeypatch):
    monkeypatch.setenv('GOOGLE_ROUTES_API_KEY', '')
    state = AppState()
    provider = MockWhatsAppProvider()
    n = NotificationService(provider=provider, event_log=state.event_log, carriers=state.carriers, locations=state.locations)
    service = build_routing(state=state, notifications=n, provider=provider)
    service.clock = lambda: NOW
    service.maps = FakeMaps()
    c = state.carriers.add(Carrier(id='carrier', name='Empresa QA', contact_phone='+5491100000001', is_validated=True))
    state.drivers.add(Driver(id='driver', carrier_id=c.id, name='Chofer QA', phone='+5491100000002', validation_status='APPROVED'))
    o = state.locations.add(Location(original_text='Pergamino, Buenos Aires'))
    d = state.locations.add(Location(original_text='Rosario, Santa Fe'))
    ship = state.shipment_requests.add(ShipmentRequest(id='shipment', producer_phone_number='+5491100000003', origin_location_id=o.id, destination_location_id=d.id, date_window_start=NOW + timedelta(hours=2), cargo_type='novillos', cargo_category='LIVESTOCK', quantity_estimate=Decimal(20), quantity_unit='HEAD', status='PUBLISHED'))
    return state, service, provider, ship


def availability(state, ship, **extra):
    data = dict(carrier_id='carrier', origin='Pergamino, Buenos Aires', destination='Rosario, Santa Fe', window_start=NOW, window_end=NOW+timedelta(days=1), capacity=Decimal(25), capacity_unit='HEAD', cargo_types=['novillos'], equipment_types=['jaula'], status='ACTIVE', test_run_id=ship.test_run_id)
    data.update(extra)
    return state.route_availabilities.add(RouteAvailability(**data))


def preference(service, carrier='carrier', scope=None, **extra):
    data = dict(origin='Pergamino, Buenos Aires', destination='Rosario, Santa Fe', cargo_categories=['LIVESTOCK'], opt_in=True)
    data.update(extra)
    return service.save_preference(carrier, data, scope)


def start(state, service, ship):
    trip = state.trips.add(Trip(id='trip', shipment_request_id=ship.id, assignment_id='assignment', carrier_id='carrier', driver_id='driver', status='IN_TRANSIT'))
    service.confirm_driver(trip.id, None, 'operator')
    service.transit(trip)
    assert service.run_one() == 'DONE'
    return trip


def inbound(provider_id, location=None, reply=None, phone='+5491100000002'):
    return SimpleNamespace(provider='test', provider_message_id=provider_id, idempotency_key=provider_id, location=location or {'latitude': -33.8, 'longitude': -60.5}, reply_to_message_id=reply, phone_number=phone, occurred_at=NOW)


def test_no_declared_route_never_broadcasts(routing):
    state, service, provider, ship = routing
    assert service.publish(ship) == []
    assert all(m.conversation_id == ship.producer_phone_number for m in provider.sent_messages)
    assert service.store.list('dispatch', None, entity_id=ship.id)[0].status == 'EXCLUDED'


def test_qa_only_carrier_can_receive_only_inside_matching_open_scenario(routing):
    state, service, _, ship = routing
    carrier = state.carriers.get('carrier')
    carrier.validation_status = 'QA_ONLY'
    carrier.is_validated = True
    ship.test_run_id = 'qa_route_scope'
    availability(state, ship, test_run_id='qa_route_scope')

    assert service.publish(ship) == []

    state.conversation_sessions.add(ConversationSession(
        channel='whatsapp',
        participant_phone=carrier.contact_phone,
        normalized_phone_number=carrier.contact_phone,
        active_test_run_id='qa_route_scope',
        role_override='Producer',
    ))

    assert service.publish(ship) == ['carrier']
    decision = service.store.get(service.store.list('dispatch', 'qa_route_scope', entity_id=ship.id)[0].id)
    assert decision.status == 'ACCEPTED'
    assert decision.data['stage'] == 'AVAILABILITY'


def test_availability_first_then_preference_after_thirty_minutes(routing):
    state, service, provider, ship = routing
    availability(state, ship)
    state.carriers.add(Carrier(id='second', name='Segundo QA', contact_phone='+5491100000004', is_validated=True))
    preference(service, 'second')
    assert service.publish(ship) == ['carrier']
    assert service.publish(ship) == []
    service.clock = lambda: NOW+timedelta(minutes=31)
    assert service.run_one() == 'DONE'
    assert len(provider.sent_messages) == 2
    assert service.publish(ship, fallback=True) == []


@pytest.mark.parametrize('response,expected', [('INTERESTED', 1), ('NOT_AVAILABLE', 2), ('NEEDS_INFO', 2)])
def test_only_usable_interest_stops_expansion(routing, response, expected):
    state, service, provider, ship = routing
    availability(state, ship)
    state.carriers.add(Carrier(id='second', name='Segundo QA', contact_phone='+5491100000004', is_validated=True))
    preference(service, 'second')
    service.publish(ship)
    state.trip_offers.add(TripOffer(shipment_request_id=ship.id, carrier_id='carrier', response_type=response))
    service.clock = lambda: NOW+timedelta(minutes=31)
    service.run_one()
    assert len(provider.sent_messages) == expected


def test_preference_sends_immediately_but_optout_does_not(routing):
    state, service, provider, ship = routing
    p = preference(service, opt_in=False)
    assert service.publish(ship) == []
    preference(service)
    assert service.publish(ship) == ['carrier']
    assert not service.store.list('job', None)


@pytest.mark.parametrize('changes', [dict(origin='Rosario, Santa Fe', destination='Pergamino, Buenos Aires'), dict(capacity=Decimal(10)), dict(cargo_types=['soja']), dict(window_end=NOW-timedelta(minutes=1), window_start=NOW-timedelta(days=1))])
def test_incompatible_availabilities_excluded(routing, changes):
    state, service, provider, ship = routing
    availability(state, ship, **changes)
    assert service.publish(ship) == []


def test_ordered_intermediate_stop_matches(routing):
    state, service, provider, ship = routing
    availability(state, ship, origin='Corrientes, Corrientes', stops=['Pergamino, Buenos Aires'])
    assert service.publish(ship) == ['carrier']


def test_commit_prevents_second_shipment_and_stops_job(routing):
    state, service, _, ship = routing
    a = availability(state, ship)
    service.publish(ship)
    service.commit_availability(ship, 'carrier')
    assert state.route_availabilities.get(a.id).status == 'COMMITTED'
    assert service.store.list('job', None)[0].status == 'CANCELLED'
    service.commit_availability(ship, 'carrier')  # same booking is idempotent
    other = ShipmentRequest(**{**ship.__dict__, 'id': 'other'})
    state.shipment_requests.add(other)
    from app.domain.routing import RoutingEntry
    from app.application.routing import key
    service.store.put(RoutingEntry(kind='dispatch', entity_id=other.id, id=key('dispatch', other.id, 'carrier'), data={'availability_id': a.id}))
    with pytest.raises(ValueError, match='ya no está libre'):
        service.commit_availability(other, 'carrier')


def test_distinct_driver_receives_controls_and_location_does_not_deliver(routing):
    state, service, provider, ship = routing
    trip = start(state, service, ship)
    cp = service.store.list('checkpoint', None)[0]
    assert cp.data['phone'] == '+5491100000002'
    answer, actions = service.receive_location(inbound('loc-1', reply=cp.data['provider_message_id']), None)
    assert 'registrada' in answer and not actions
    assert state.trips.get(trip.id).status == 'IN_TRANSIT'
    assert service.tracking_view(trip.id, None)['reports'][0]['status'] == 'RECEIVED'
    assert 'ya quedó' in service.receive_location(inbound('loc-1'), None)[0]
    assert len(service.store.list('report', None)) == 1


def test_unquoted_point_requires_explicit_choice(routing):
    state, service, _, ship = routing
    start(state, service, ship)
    text, actions = service.receive_location(inbound('loc-1'), None)
    assert actions and 'Elegí' in text
    assert service.store.list('report', None)[0].status == 'AWAITING_SELECTION'
    assert 'registrada' in service.handle_text(actions[0].value, '+5491100000002', None)


def test_report_from_other_phone_cannot_attach(routing):
    state, service, _, ship = routing
    start(state, service, ship)
    cp = service.store.list('checkpoint', None)[0]
    text, actions = service.receive_location(inbound('foreign', reply=cp.data['provider_message_id'], phone='+5491100000009'), None)
    assert not actions
    assert cp.status == 'REQUESTED'


def test_three_requests_and_only_one_reminder(routing):
    state, service, provider, ship = routing
    start(state, service, ship)
    service.clock = lambda: NOW+timedelta(minutes=16)
    service.run_one()
    count = len(provider.sent_messages)
    assert service.run_one() is None
    assert len(provider.sent_messages) == count
    service.clock = lambda: NOW+timedelta(minutes=61)
    while service.run_one():
        pass
    stages = {c.data['stage'] for c in service.store.list('checkpoint', None)}
    assert stages == {'DEPARTURE', 'MIDDLE', 'ARRIVAL'}
    assert any(e.event_type == 'TRIP_LOCATION_OVERDUE' for e in state.event_log.events)


def test_arrival_does_not_confirm_delivery(routing):
    state, service, _, ship = routing
    trip = start(state, service, ship)
    assert 'entrega' in service.handle_text('/viaje trip llegue', '+5491100000002', None)
    assert trip.status == 'IN_TRANSIT'
    assert len([c for c in service.store.list('checkpoint', None) if c.data['stage'] == 'ARRIVAL']) == 1


def test_no_google_keeps_tracking_and_reports_missing_estimate(routing):
    state, service, provider, ship = routing
    service.maps = GoogleRoutes()
    trip = start(state, service, ship)
    assert service.tracking_view(trip.id, None)['tracking']['route_status'] == 'PENDING'
    assert len(service.store.list('checkpoint', None)) == 1


def test_cross_scenario_and_closed_run(routing):
    state, service, _, ship = routing
    trip = start(state, service, ship)
    with pytest.raises(ValueError):
        service.tracking_view(trip.id, 'other')
    service.close_run('closed')
    assert service.closed('closed')


def test_google_payload_is_drive_no_traffic_and_errors_redacted():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'routes':[{'distanceMeters':100, 'duration':'20s', 'polyline':{'encodedPolyline':'p'}}]})
    maps = GoogleRoutes('synthetic-key', httpx.Client(transport=httpx.MockTransport(handler)))
    route = maps.calculate([{'label':'Pergamino'}, {'latitude':-33.8, 'longitude':-60.5}])
    assert route['duration_seconds'] == 20
    import json
    payload = json.loads(seen[0].content)
    assert payload['travelMode'] == 'DRIVE' and payload['routingPreference'] == 'TRAFFIC_UNAWARE'
    maps.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text='secret-body')))
    with pytest.raises(RouteUnavailable) as e:
        maps.calculate([{'label':'A'}, {'label':'B'}])
    assert 'secret' not in str(e.value)
    assert 'api=1' in maps_url({'label':'A'}, {'label':'B'})


def test_backoffice_auth_scope_and_preference_roundtrip(routing):
    from fastapi.testclient import TestClient
    from app.api.routes.routing import get_routing
    from app.main import app
    _, service, _, ship = routing
    app.dependency_overrides[get_routing] = lambda: service
    headers = {'x-operator-user-id':'qa_operator', 'x-operator-role':'operator'}
    try:
        client = TestClient(app)
        assert client.get('/api/v1/backoffice/carriers/carrier/route-preferences').status_code == 401
        saved = client.post('/api/v1/backoffice/carriers/carrier/route-preferences', headers=headers, json={'origin':'Pergamino, Buenos Aires','destination':'Rosario, Santa Fe','cargo_categories':['LIVESTOCK'],'opt_in':True})
        assert saved.status_code == 200
        row = saved.json()
        assert row['data']['points'][0]['id'] != row['data']['points'][1]['id']
        assert client.get('/api/v1/backoffice/carriers/carrier/route-preferences?test_run_id=another', headers=headers).json()['items'] == []
        assert client.get('/api/v1/backoffice/shipments/shipment/dispatch?test_run_id=another', headers=headers).status_code == 404
        assert client.put('/api/v1/backoffice/shipments/shipment/locations/origin',headers=headers,json={'latitude':-33.8,'longitude':-60.5}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_location_payload_native_request_and_invalid_coordinates():
    from app.infrastructure.adapters.kapso import KapsoProvider, WebhookPayloadError
    from app.infrastructure.adapters.whatsapp import OutboundMessage
    provider = KapsoProvider(webhook_secret='synthetic-qa')
    payload = {'event_type':'message.received', 'message': {'id':'wamid.qa','from':'5491100000002','type':'location','location':{'latitude':-33.8,'longitude':-60.5},'context':{'id':'wamid.request'}}}
    normalized = provider.normalize_inbound(payload=payload,headers={})
    assert normalized.location['latitude'] == -33.8 and normalized.reply_to_message_id == 'wamid.request'
    native = provider._whatsapp_payload(OutboundMessage(conversation_id='+5491100000002',body='📍 Compartí ubicación',message_type='location_request'))
    assert native['interactive']['type'] == 'location_request_message'
    assert native['interactive']['action']['name'] == 'send_location'
    payload['message']['id'] = 'wamid.bad'
    payload['message']['location']['latitude'] = 999
    with pytest.raises(WebhookPayloadError):
        provider.normalize_inbound(payload=payload,headers={})


def test_preference_capture_and_pause_is_separate_from_availability(routing):
    from app.domain.models import ConversationSession
    state, service, _, ship = routing
    session = state.conversation_sessions.add(ConversationSession(channel='test'))
    carrier = state.carriers.get('carrier')
    for text in ['agregar recorrido habitual', 'Pergamino, Buenos Aires', 'Rosario, Santa Fe', 'sin paradas', 'hacienda', 'jaula', 'sí']:
        answer = service.capture_preference(session,carrier,text)
        assert answer
    assert answer[1][0].label == '✅ Confirmar'
    service.capture_preference(session,carrier,'confirmar')
    pref = service.store.list('preference',None)[0]
    assert not state.route_availabilities.list()
    service.capture_preference(session,carrier,f'/recorrido {pref.id} pausar')
    assert service.store.get(pref.id).status == 'PAUSED'


def test_location_from_previous_scenario_preserved_without_affecting_current(routing):
    state, service, _, ship = routing
    start(state,service,ship)
    cp = service.store.list('checkpoint',None)[0]
    cp.test_run_id = 'old-run';service.store.put(cp)
    service.close_run('old-run')
    answer, _ = service.receive_location(inbound('late',reply=cp.data['provider_message_id']), 'new-run')
    assert 'anterior' in answer
    assert service.store.list('report','old-run')[0].status == 'LATE'
    assert service.store.list('report','new-run') == []


def test_producer_can_confirm_access_from_whatsapp(routing):
    state, service, _, ship = routing
    text = service.handle_text('/ubicacion origen shipment',ship.producer_phone_number,None)
    assert 'ubicación' in text
    cp = service.store.list('checkpoint',None)[0]
    answer,_ = service.receive_location(inbound('access',reply=cp.data['provider_message_id'],phone=ship.producer_phone_number),None)
    assert 'acceso guardado' in answer
    point = state.locations.get(ship.origin_location_id)
    assert point.coordinate_precision == 'CONFIRMED_ACCESS'


def test_webhook_to_backoffice_complete_directed_tracking_flow(routing, monkeypatch):
    """Real request boundaries, signed fake webhooks, backend rules and channel mock."""
    import json, hmac, hashlib
    from fastapi.testclient import TestClient
    from app.api.dependencies import reset_app_state, get_whatsapp_provider, get_ai_extraction_client
    from app.core.config import get_settings
    from app.domain.models import Vehicle
    from app.main import app
    state, service, provider, ship = routing
    target = reset_app_state()
    target.__dict__.update(state.__dict__)
    availability(state,ship)
    ship.status = 'VALIDATED'
    state.vehicles.add(Vehicle(id='vehicle',carrier_id='carrier',status='ACTIVE',validation_status='APPROVED'))
    monkeypatch.setenv('KAPSO_WEBHOOK_SECRET','synthetic-qa-secret')
    monkeypatch.setenv('WHATSAPP_ALLOWLIST_SOURCE','env')
    monkeypatch.setenv('WHATSAPP_DEV_ALLOWLIST',','.join(['+5491100000001','+5491100000002','+5491100000003']))
    monkeypatch.setattr('app.application.routing_factory.GoogleRoutes',lambda *args:FakeMaps())
    get_settings.cache_clear()
    app.dependency_overrides[get_whatsapp_provider] = lambda:provider
    app.dependency_overrides[get_ai_extraction_client] = lambda: object()  # these commands must not call AI
    headers = {'x-operator-user-id':'qa_operator','x-operator-role':'operator'}
    client = TestClient(app)
    def message(phone, text='', location=None, reply=None, ident=None):
        ident = ident or 'qa-' + str(len(state.messages.list()))
        payload={'event_type':'message.received','idempotency_key':ident,'provider_message_id':ident,'conversation_id':phone,'phone_number':phone,'occurred_at':datetime.now(UTC).isoformat(),'payload':{'text':text}}
        if location:
            payload['location']=location
        if reply:
            payload['context']={'id':reply}
        raw=json.dumps(payload,separators=(',',':')).encode()
        signature=hmac.new(b'synthetic-qa-secret',raw,hashlib.sha256).hexdigest()
        result=client.post('/api/v1/webhooks/kapso',content=raw,headers={'X-Webhook-Signature':'sha256='+signature})
        assert result.status_code==200, result.text
        return result
    try:
        published = client.post('/api/v1/shipment-requests/shipment/publish',headers=headers,json={'carrier_ids':[]})
        assert published.status_code==200
        assert any(m.metadata.get('notification_type')=='NEW_LOAD_ALERT' for m in provider.sent_messages)
        message('+5491100000001','me interesa')
        assert len(state.trip_offers.list())==1
        message('+5491100000003','ver interesados')
        message('+5491100000003','aceptar oferta 1')
        message('+5491100000003','confirmar')
        assert len(state.trips.list())==1
        trip=state.trips.list()[0]
        assert state.route_availabilities.list()[0].status=='COMMITTED'
        assert client.post(f'/api/v1/backoffice/trips/{trip.id}/crew',headers=headers,json={'driver_id':'driver','vehicle_id':'vehicle'}).status_code==200
        assert client.post(f'/api/v1/backoffice/trips/{trip.id}/tracking/confirm-driver',headers=headers).status_code==200
        assert client.post(f'/api/v1/backoffice/trips/{trip.id}/mark-in-transit',headers=headers,json={}).status_code==200
        service.clock = lambda: datetime.now(UTC)
        assert service.run_one()=='DONE'
        cp=service.store.list('checkpoint',None)[0]
        message('+5491100000002',location={'latitude':-33.8,'longitude':-60.5},reply=cp.data['provider_message_id'],ident='qa-location')
        view=client.get(f'/api/v1/backoffice/trips/{trip.id}/tracking',headers=headers).json()
        assert view['reports'][0]['status']=='RECEIVED'
        assert view['status']=='IN_TRANSIT'
        message('+5491100000002',location={'latitude':-33.8,'longitude':-60.5},reply=cp.data['provider_message_id'],ident='qa-location')
        assert len(service.store.list('report',None))==1
        message('+5491100000002',f'/viaje {trip.id} llegue')
        assert state.trips.get(trip.id).status=='IN_TRANSIT'
        assert any(e.event_type=='TRIP_ARRIVAL_REPORTED' for e in state.event_log.events)
    finally:
        app.dependency_overrides.clear()


def test_required_equipment_is_not_inferred_and_filters_when_declared(routing):
    state,service,_,ship=routing
    availability(state,ship)
    ship.required_equipment_type='granelero'
    assert service.publish(ship)==[]
    ship.required_equipment_type='jaula'
    assert service.publish(ship)==['carrier']


def test_homonymous_locality_requires_province(routing):
    from collections import defaultdict
    from app.application.routing import georef_rows
    _,service,_,_=routing
    names=defaultdict(set)
    for row in georef_rows():
        if row.get('categoria') != 'Entidad':
            names[row['nombre']].add(row['provincia_nombre'])
    ambiguous=next(name for name,provinces in names.items() if len(provinces)>1)
    with pytest.raises(ValueError):
        service.node(ambiguous)


def test_driver_button_checks_ownership_and_scope(routing):
    state,service,_,ship=routing
    start(state,service,ship)
    assert service.action_command('trip-arrival:trip','+5491100000002',None)=='/viaje trip llegue'
    with pytest.raises(ValueError):
        service.action_command('trip-arrival:trip','+5491100000001',None)
    with pytest.raises(ValueError):
        service.action_command('trip-arrival:trip','+5491100000002','another')


def test_changed_driver_does_not_accept_the_previous_phone_report(routing):
    state,service,_,ship=routing
    start(state,service,ship)
    cp=service.store.list('checkpoint',None)[0]
    state.drivers.get('driver').phone='+5491100000099'
    with pytest.raises(ValueError,match='chofer'):
        service.receive_location(inbound('old-driver',reply=cp.data['provider_message_id']),None)
    assert not any(r.status=='RECEIVED' for r in service.store.list('report',None))
    assert service.store.get(cp.id).status=='REQUESTED'


def test_disabled_cargo_catalog_is_not_replaced_by_static_fallback(routing):
    _,service,_,ship=routing
    service.cargo_catalog=[];service.category_catalog=[]
    with pytest.raises(ValueError):
        preference(service)
    assert service.publish(ship)==[]


def test_disabled_geographic_catalog_is_not_replaced_by_snapshot(routing):
    _,service,_,_=routing
    service.geography=[]
    with pytest.raises(ValueError):
        service.node('Pergamino, Buenos Aires')
