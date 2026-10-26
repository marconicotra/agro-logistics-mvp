"""Opt-in only: migrations and concurrency in a dedicated disposable PostgreSQL."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.routing import key
from app.application.routing_factory import build_routing
from app.domain.models import Carrier, Location, ShipmentRequest
from app.domain.route_availability import RouteAvailability
from app.domain.routing import RoutingEntry
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlLocationRepository, SqlShipmentRequestRepository, SqlRouteAvailabilityRepository
from app.infrastructure.repositories.routing import SqlRoutingStore


@pytest.fixture
def factory():
    url = os.environ.get('AGRO_QA_POSTGRES_URL')
    if not url:
        pytest.skip('Requiere PostgreSQL descartable explícito')
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.host in {'127.0.0.1','localhost'} and parsed.database == 'agro_route_qa'
    engine = create_engine(url)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_postgres_two_acceptances_cannot_book_one_availability(factory):
    now = datetime.now(UTC)
    prefix = uuid4().hex[:8]
    with factory() as s, s.begin():
        c = SqlCarrierRepository(s).add(Carrier(id='car_'+prefix,name='QA',is_validated=True,contact_phone='+5491100000001'))
        o = SqlLocationRepository(s).add(Location(original_text='Pergamino, Buenos Aires'))
        d = SqlLocationRepository(s).add(Location(original_text='Rosario, Santa Fe'))
        a = SqlRouteAvailabilityRepository(s).add(RouteAvailability(carrier_id=c.id,origin=o.original_text,destination=d.original_text,window_start=now-timedelta(hours=1),window_end=now+timedelta(days=1),capacity=Decimal(30),capacity_unit='HEAD',cargo_types=['novillos'],equipment_types=['jaula'],status='ACTIVE'))
        ids = []
        for _ in range(2):
            ship = SqlShipmentRequestRepository(s).add(ShipmentRequest(origin_location_id=o.id,destination_location_id=d.id,date_window_start=now+timedelta(hours=1),cargo_category='LIVESTOCK',cargo_type='novillos',quantity_estimate=Decimal(25),quantity_unit='HEAD',status='MATCHING'))
            ids.append(ship.id)
            SqlRoutingStore(s).put(RoutingEntry(kind='dispatch',entity_id=ship.id,id=key('dispatch',ship.id,c.id),data={'availability_id':a.id}))
    gate = Barrier(2)
    def book(shipment_id):
        try:
            with factory() as s, s.begin():
                service = build_routing(session=s)
                gate.wait(timeout=10)
                service.commit_availability(service.shipments.get(shipment_id),c.id)
            return 'BOOKED'
        except ValueError:
            return 'UNAVAILABLE'
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(book,ids))
    assert sorted(result) == ['BOOKED','UNAVAILABLE']
    with factory() as s:
        assert SqlRouteAvailabilityRepository(s).get(a.id).committed_shipment_id in ids


def test_postgres_workers_claim_once_and_restart_sees_done(factory):
    prefix = uuid4().hex
    with factory() as s,s.begin():
        SqlRoutingStore(s).put(RoutingEntry(kind='job',entity_id='absent-'+prefix,id='job-'+prefix,status='PENDING',due_at=datetime.now(UTC),data={'action':'EXPAND'}))
    def run():
        with factory() as s,s.begin():
            return build_routing(session=s).run_one()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:run(),range(2)))
    assert results.count('DONE') == 1
    with factory() as s:
        assert SqlRoutingStore(s).get('job-'+prefix).status == 'DONE'
