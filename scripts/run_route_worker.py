#!/usr/bin/env python3
"""Persistent route tasks; never run as an in-process API timer."""
import argparse
from pathlib import Path
import sys
import time
import logging
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.config import get_settings
from app.api.dependencies import get_whatsapp_provider
from app.application.notifications import NotificationService
from app.application.routing_factory import build_routing
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.db.notification_outbox import SqlNotificationOutboxProvider
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.repositories import SqlCarrierRepository, SqlLocationRepository, SqlConversationSessionRepository, SqlMessageRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=2)
    args = parser.parse_args()
    if args.poll_seconds < .2:
        parser.error('El intervalo mínimo es 0.2 segundos')
    settings = get_settings()
    if settings.storage_backend != 'sql' or not settings.route_operations_enabled:
        parser.error('Se requiere STORAGE_BACKEND=sql y ROUTE_OPERATIONS_ENABLED=true')
    factory = get_session_factory(settings.database_url)
    provider = get_whatsapp_provider()
    logging.basicConfig(level=logging.INFO)
    while True:
        with factory() as session, session.begin():
            queued = SqlNotificationOutboxProvider(provider=provider, session=session)
            notifications = NotificationService(provider=queued, event_log=SqlEventLogService(session), carriers=SqlCarrierRepository(session), locations=SqlLocationRepository(session), conversation_sessions=SqlConversationSessionRepository(session), messages=SqlMessageRepository(session))
            outcome = build_routing(session=session, notifications=notifications, provider=queued).run_one()
        if outcome:
            logging.info('route_job outcome=%s', outcome)
        elif args.once:
            return 0
        else:
            time.sleep(args.poll_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
