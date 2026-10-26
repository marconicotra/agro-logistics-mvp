"""Composition root shared by requests and the persistent route worker."""
from app.application.routing import RoutingService
from app.infrastructure.adapters.google_routes import GoogleRoutes
from app.infrastructure.repositories.routing import MemoryRoutingStore, SqlRoutingStore


def build_routing(*, session=None, state=None, notifications=None, provider=None):
    from app.core.config import get_settings
    settings = get_settings()
    if session is not None:
        from app.infrastructure.db import repositories as r
        from app.infrastructure.db.event_log import SqlEventLogService
        from app.infrastructure.db.catalogs import load_active_geography_catalog, load_active_cargo_catalog
        categories, types = load_active_cargo_catalog(session)
        return RoutingService(store=SqlRoutingStore(session), shipments=r.SqlShipmentRequestRepository(session),
            carriers=r.SqlCarrierRepository(session), availabilities=r.SqlRouteAvailabilityRepository(session),
            offers=r.SqlTripOfferRepository(session), trips=r.SqlTripRepository(session), drivers=r.SqlDriverRepository(session),
            locations=r.SqlLocationRepository(session), conversations=r.SqlConversationSessionRepository(session),
            events=SqlEventLogService(session), notifications=notifications, provider=provider or getattr(notifications, '_provider', None),
            geography=load_active_geography_catalog(session), cargo_catalog=types, category_catalog=categories, maps=GoogleRoutes(settings.google_routes_api_key), daily_route_limit=settings.google_routes_daily_limit)
    return RoutingService(store=state.routing_store, shipments=state.shipment_requests, carriers=state.carriers,
        availabilities=state.route_availabilities, offers=state.trip_offers, trips=state.trips, drivers=state.drivers,
        locations=state.locations, conversations=state.conversation_sessions, events=state.event_log,
        notifications=notifications, provider=provider or getattr(notifications, '_provider', None),
        maps=GoogleRoutes(settings.google_routes_api_key), daily_route_limit=settings.google_routes_daily_limit)
