"""Synthetic, memory-only routing demo. No credentials or external requests."""
import os
from datetime import UTC, datetime
import run_local_demo as demo  # isolates cwd and disables external integrations
from app.application.routing_factory import build_routing
from app.domain.models import Driver


def seed():
    demo.seed_demo()
    state = demo.get_app_state()
    driver = state.drivers.add(Driver(name='Chofer ficticio QA',carrier_id=demo.DEMO_CARRIER_ID,phone='+5491100000002',validation_status='APPROVED'))
    trip = state.trips.get(demo.DEMO_TRIP_ID)
    trip.driver_id, trip.status = driver.id, 'IN_TRANSIT'
    state.trips.save(trip)
    service = build_routing(state=state)
    class SyntheticRoutes:
        def calculate(self, points):
            return {'distance_meters':300000,'duration_seconds':14400,'polyline':''}
    service.maps = SyntheticRoutes()
    service.confirm_driver(trip.id, trip.test_run_id, 'demo_operator')
    service.transit(trip)
    service.run_one()
    return state


if __name__ == '__main__':
    import uvicorn
    seed()
    print('AGRO recorridos QA: datos ficticios, memoria y proveedores simulados.')
    uvicorn.run(demo.app,host='127.0.0.1',port=int(os.environ.get('LOCAL_DEMO_API_PORT','58400')),log_level='warning')
