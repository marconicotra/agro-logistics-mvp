"""Recheck business eligibility while holding the same transaction lock as acceptance."""
from app.application.routing import key, OPEN_LOADS
from app.application.routing_factory import build_routing
from app.infrastructure.repositories.routing import SqlRoutingStore
from app.infrastructure.db.repositories import SqlShipmentRequestRepository, SqlCarrierRepository, SqlTripRepository, SqlDriverRepository


def route_message_allowed(session, message):
    m = message.metadata
    scope = m.get('qa_test_run_id')
    store = SqlRoutingStore(session)
    if scope and store.get(key('closed', scope)):
        return False
    if m.get('routing_guard'):
        shipment_id, carrier_id = m.get('shipment_request_id'), m.get('carrier_id')
        with store.lock('shipment:' + str(shipment_id)):
            shipment = SqlShipmentRequestRepository(session).get(shipment_id)
            carrier = SqlCarrierRepository(session).get(carrier_id)
            service = build_routing(session=session)
            if not shipment or shipment.status not in OPEN_LOADS or shipment.test_run_id != scope or not carrier or not service.dispatch_eligible(carrier, scope):
                return False
            origin = service.point(shipment.origin_location_id)['id']
            destination = service.point(shipment.destination_location_id)['id']
            if m.get('availability_id'):
                a = service.availabilities.get(m['availability_id'])
                return bool(a and service.compatible(a, shipment, origin, destination))
            return any((not shipment.required_equipment_type or shipment.required_equipment_type in p.data['equipment_types']) and p.status == 'ACTIVE' and p.data.get('opt_in') and service.segment(p.data['points'], origin, destination) and (shipment.cargo_category in p.data['cargo_categories'] or shipment.cargo_type in p.data['cargo_types']) for p in store.list('preference', scope, entity_id=carrier_id))
    if m.get('notification_type') == 'TRIP_TRACKING' and not m.get('producer_phone_number'):
        trip = SqlTripRepository(session).get(m.get('entity_id'))
        tracking = store.get(key('tracking', m.get('entity_id')))
        if not trip or trip.test_run_id != scope or trip.status not in {'IN_TRANSIT', 'DELIVERED'} or not tracking:
            return False
        driver = SqlDriverRepository(session).get(trip.driver_id)
        return bool(driver and driver.status == 'ACTIVE' and driver.validation_status == 'APPROVED' and driver.id == tracking.data.get('driver_id') and build_routing(session=session).phone(driver.phone) == tracking.data.get('driver_phone'))
    return True
