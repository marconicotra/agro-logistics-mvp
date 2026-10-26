from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.application.notifications import NotificationService
from app.application.routing_factory import build_routing
from app.domain.models import Carrier, Location, ShipmentRequest
from app.infrastructure.db.base import Base
from app.infrastructure.db import models
from app.infrastructure.db.models import NotificationOutboxRecord
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.notification_outbox import SqlNotificationOutboxProvider, NotificationOutboxDispatcher
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlLocationRepository, SqlShipmentRequestRepository
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider


@pytest.mark.parametrize('close_before_send,expected', [(False,'ACCEPTED'),(True,'CANCELLED')])
def test_sql_outbox_rechecks_open_shipment_and_persists_dispatch(tmp_path,close_before_send,expected):
    engine=create_engine('sqlite+pysqlite:///'+str(tmp_path/'routing.db'))
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    provider=MockWhatsAppProvider()
    with factory() as session,session.begin():
        carrier=SqlCarrierRepository(session).add(Carrier(name='Transportista QA',contact_phone='+5491100000001',is_validated=True))
        origin=SqlLocationRepository(session).add(Location(original_text='Pergamino, Buenos Aires'))
        destination=SqlLocationRepository(session).add(Location(original_text='Rosario, Santa Fe'))
        shipment=SqlShipmentRequestRepository(session).add(ShipmentRequest(origin_location_id=origin.id,destination_location_id=destination.id,status='PUBLISHED',date_window_start=datetime.now(UTC),cargo_category='LIVESTOCK',cargo_type='novillos'))
        queued=SqlNotificationOutboxProvider(provider=provider,session=session)
        notifications=NotificationService(provider=queued,event_log=SqlEventLogService(session),carriers=SqlCarrierRepository(session),locations=SqlLocationRepository(session))
        service=build_routing(session=session,notifications=notifications)
        service.save_preference(carrier.id,{'origin':origin.original_text,'destination':destination.original_text,'cargo_categories':['LIVESTOCK'],'opt_in':True},None)
        assert service.publish(shipment)==[carrier.id]
    with factory() as session,session.begin():
        if close_before_send:
            stored=SqlShipmentRequestRepository(session).get(shipment.id);stored.status='ASSIGNED';SqlShipmentRequestRepository(session).save(stored)
    assert NotificationOutboxDispatcher(session_factory=factory,provider=provider).dispatch_one()==expected
    with factory() as session:
        row=session.scalar(select(NotificationOutboxRecord))
        assert row.status==expected
    assert len(provider.sent_messages)==(0 if close_before_send else 1)
    engine.dispose()
