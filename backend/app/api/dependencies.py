from dataclasses import dataclass, field
import hmac
from typing import Iterator

from fastapi import Depends, Header, HTTPException, status
import jwt
from sqlalchemy.orm import Session

from app.application.routing_factory import build_routing
from app.infrastructure.repositories.routing import MemoryRoutingStore
from app.application.ai import AIExtractionClient, AIExtractionError
from app.application.admin_ops import AdminOpsService
from app.application.backoffice import BackofficeService
from app.application.carrier_onboarding import CarrierOnboardingService
from app.application.conversation_orchestrator import ConversationOrchestrator
from app.application.media import MediaService
from app.application.notifications import NotificationService
from app.application.notification_outbox_admin import NotificationOutboxAdminService
from app.application.producer_backoffice import ProducerBackofficeService
from app.application.transcription import SpeechToTextClient, TranscriptionService
from app.application.whatsapp_allowlist import WhatsappAllowlistService
from app.core.config import get_settings
from app.core.supabase_auth import SupabaseAuthConfigurationError, verify_supabase_access_token
from app.domain.events import EventLogService
from app.domain.route_availability import RouteAvailability
from app.domain.models import (
    Assignment,
    Carrier,
    CarrierOnboarding,
    ConversationSession,
    Document,
    Driver,
    Location,
    MediaAsset,
    Message,
    Producer,
    ShipmentRequest,
    Trip,
    TripOffer,
    User,
    Vehicle,
    WhatsappAllowedContact,
)
from app.infrastructure.adapters.kapso import KapsoProvider
from app.infrastructure.adapters.openai_ai import OpenAIExtractionClient
from app.infrastructure.adapters.openai_stt import OpenAITranscriptionClient
from app.infrastructure.adapters.whatsapp import MockWhatsAppProvider, WhatsAppProvider
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.catalogs import load_active_cargo_catalog, load_active_geography_catalog
from app.infrastructure.db.models import OperatorRoleRecord
from app.infrastructure.db.repositories import (
    SqlAssignmentRepository,
    SqlCarrierRepository,
    SqlCarrierOnboardingRepository,
    SqlConversationSessionRepository,
    SqlDocumentRepository,
    SqlDriverRepository,
    SqlLocationRepository,
    SqlMediaAssetRepository,
    SqlMessageRepository,
    SqlProducerRepository,
    SqlShipmentRequestRepository,
    SqlTripOfferRepository,
    SqlTripRepository,
    SqlVehicleRepository,
    SqlRouteAvailabilityRepository,
    SqlWhatsappAllowedContactRepository,
)
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.db.notification_outbox import SqlNotificationOutboxProvider
from app.infrastructure.db.notification_outbox_admin import SqlNotificationOutboxReadRepository
from app.infrastructure.db.unit_of_work import build_sql_admin_ops_service, build_sql_conversation_orchestrator
from app.infrastructure.repositories.memory import InMemoryRepository


@dataclass
class AppState:
    routing_store: MemoryRoutingStore = field(default_factory=MemoryRoutingStore)
    event_log: EventLogService = field(default_factory=EventLogService)
    users: InMemoryRepository[User] = field(default_factory=InMemoryRepository)
    producers: InMemoryRepository[Producer] = field(default_factory=InMemoryRepository)
    carriers: InMemoryRepository[Carrier] = field(default_factory=InMemoryRepository)
    carrier_onboardings: InMemoryRepository[CarrierOnboarding] = field(default_factory=InMemoryRepository)
    vehicles: InMemoryRepository[Vehicle] = field(default_factory=InMemoryRepository)
    drivers: InMemoryRepository[Driver] = field(default_factory=InMemoryRepository)
    shipment_requests: InMemoryRepository[ShipmentRequest] = field(default_factory=InMemoryRepository)
    trip_offers: InMemoryRepository[TripOffer] = field(default_factory=InMemoryRepository)
    assignments: InMemoryRepository[Assignment] = field(default_factory=InMemoryRepository)
    trips: InMemoryRepository[Trip] = field(default_factory=InMemoryRepository)
    conversation_sessions: InMemoryRepository[ConversationSession] = field(default_factory=InMemoryRepository)
    messages: InMemoryRepository[Message] = field(default_factory=InMemoryRepository)
    media_assets: InMemoryRepository[MediaAsset] = field(default_factory=InMemoryRepository)
    locations: InMemoryRepository[Location] = field(default_factory=InMemoryRepository)
    route_availabilities: InMemoryRepository[RouteAvailability] = field(default_factory=InMemoryRepository)
    documents: InMemoryRepository[Document] = field(default_factory=InMemoryRepository)
    whatsapp_allowed_contacts: InMemoryRepository[WhatsappAllowedContact] = field(
        default_factory=InMemoryRepository
    )

    def admin_ops_service(self, notification_service: NotificationService | None = None) -> AdminOpsService:
        service = AdminOpsService(
            shipment_requests=self.shipment_requests,
            trip_offers=self.trip_offers,
            assignments=self.assignments,
            trips=self.trips,
            carriers=self.carriers,
            locations=self.locations,
            conversation_sessions=self.conversation_sessions,
            messages=self.messages,
            event_log=self.event_log,
            notification_service=notification_service,
            trip_readiness_guard=self.ensure_trip_start_ready,
            enable_test_role_switching=(
                get_settings().enable_test_role_switching and not get_settings().is_production
            ),
        )

        if get_settings().route_operations_enabled:
            service._routing = build_routing(state=self, notifications=notification_service)
        return service

    def ensure_trip_start_ready(self, trip_id: str) -> None:
        CarrierOnboardingService(
            carriers=self.carriers,
            vehicles=self.vehicles,
            drivers=self.drivers,
            trips=self.trips,
            documents=self.documents,
            onboardings=self.carrier_onboardings,
            event_log=self.event_log,
        ).ensure_trip_start_ready(trip_id)

    def conversation_orchestrator(
        self,
        ai_client: AIExtractionClient,
        *,
        notification_service: NotificationService | None = None,
        media_service: MediaService | None = None,
        transcription_service: TranscriptionService | None = None,
        enable_test_role_switching: bool = False,
    ) -> ConversationOrchestrator:
        return ConversationOrchestrator(
            ai_client=ai_client,
            conversation_sessions=self.conversation_sessions,
            messages=self.messages,
            shipment_requests=self.shipment_requests,
            locations=self.locations,
            event_log=self.event_log,
            route_availabilities=self.route_availabilities,
            admin_ops_service=self.admin_ops_service(notification_service),
            carriers=self.carriers,
            carrier_onboarding_service=CarrierOnboardingService(
                carriers=self.carriers,
                vehicles=self.vehicles,
                drivers=self.drivers,
                trips=self.trips,
                documents=self.documents,
                onboardings=self.carrier_onboardings,
                event_log=self.event_log,
            ),
            trip_offers=self.trip_offers,
            notification_service=notification_service,
            media_service=media_service,
            transcription_service=transcription_service,
            enable_test_role_switching=enable_test_role_switching,
        )


_state = AppState()


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    role: str


def get_app_state() -> AppState:
    return _state


def reset_app_state() -> AppState:
    global _state
    _state = AppState()
    return _state


class UnconfiguredAIExtractionClient:
    def extract_load_data(self, message_text: str):  # noqa: ANN201
        raise AIExtractionError("AI extraction client is not configured")


def get_ai_extraction_client() -> AIExtractionClient:
    settings = get_settings()
    if settings.ai_provider.strip().lower() == "openai" and settings.openai_api_key:
        return OpenAIExtractionClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
    return UnconfiguredAIExtractionClient()


def get_kapso_provider() -> KapsoProvider:
    settings = get_settings()
    return KapsoProvider(
        webhook_secret=settings.kapso_webhook_secret,
        replay_window_seconds=settings.kapso_timestamp_tolerance_seconds,
    )


def get_whatsapp_provider() -> WhatsAppProvider:
    settings = get_settings()
    provider = settings.whatsapp_provider.lower()
    if provider == "mock":
        return MockWhatsAppProvider()
    if provider != "kapso":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported WhatsApp provider: {settings.whatsapp_provider}",
        )
    if not settings.enable_real_whatsapp:
        return MockWhatsAppProvider()

    missing = []
    if not settings.kapso_api_key:
        missing.append("KAPSO_API_KEY")
    if not settings.kapso_base_url:
        missing.append("KAPSO_BASE_URL")
    if not settings.kapso_phone_number_id:
        missing.append("KAPSO_PHONE_NUMBER_ID")
    if not settings.kapso_webhook_secret:
        missing.append("KAPSO_WEBHOOK_SECRET")
    if missing:
        if settings.debug:
            return MockWhatsAppProvider()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Missing KAPSO configuration: {', '.join(missing)}",
        )

    if settings.enable_real_whatsapp:
        return KapsoProvider(
            webhook_secret=settings.kapso_webhook_secret,
            replay_window_seconds=settings.kapso_timestamp_tolerance_seconds,
            api_key=settings.kapso_api_key,
            base_url=settings.kapso_base_url,
            phone_number_id=settings.kapso_phone_number_id,
            send_message_path=settings.kapso_send_message_path,
            new_load_template_name=settings.effective_kapso_new_load_template_name,
            allow_test_run_freeform_new_loads=(settings.enable_test_role_switching and not settings.is_production),
            template_language_code=settings.kapso_template_language_code,
            interactive_enabled=settings.kapso_interactive_enabled,
            enable_real_outbound=True,
            allowlist=settings.whatsapp_allowlist,
            enforce_allowlist=not settings.is_production,
        )
    return MockWhatsAppProvider()


def get_request_db_session() -> Iterator[Session | None]:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        yield None
        return
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )

    session_factory = get_session_factory(settings.database_url)
    with session_factory() as session:
        yield session


def get_notification_service(
    provider: WhatsAppProvider = Depends(get_whatsapp_provider),
    db_session: Session | None = Depends(get_request_db_session),
) -> NotificationService:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        return NotificationService(
            provider=provider,
            event_log=_state.event_log,
            carriers=_state.carriers,
            locations=_state.locations,
            conversation_sessions=_state.conversation_sessions,
            messages=_state.messages,
        )
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )
    return NotificationService(
        provider=SqlNotificationOutboxProvider(provider=provider, session=db_session),
        event_log=SqlEventLogService(db_session),
        carriers=SqlCarrierRepository(db_session),
        locations=SqlLocationRepository(db_session),
        conversation_sessions=SqlConversationSessionRepository(db_session),
        messages=SqlMessageRepository(db_session),
    )


def get_notification_outbox_admin_service(
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[NotificationOutboxAdminService]:
    settings = get_settings()
    if settings.storage_backend.lower() == "memory":
        yield NotificationOutboxAdminService(repository=None)
        return
    if settings.storage_backend.lower() != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )
    service = NotificationOutboxAdminService(repository=SqlNotificationOutboxReadRepository(db_session))
    if db_session.in_transaction():
        yield service
        return
    with db_session.begin():
        yield service


def get_admin_ops_service(
    notification_service: NotificationService = Depends(get_notification_service),
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[AdminOpsService]:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        yield _state.admin_ops_service(notification_service)
        return
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )

    with db_session.begin():
        yield build_sql_admin_ops_service(
            db_session,
            notification_service,
            enable_test_role_switching=settings.enable_test_role_switching and not settings.is_production,
        )


def get_media_service(
    db_session: Session | None = Depends(get_request_db_session),
) -> MediaService:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        return MediaService(
            media_assets=_state.media_assets,
            documents=_state.documents,
            messages=_state.messages,
            carriers=_state.carriers,
            drivers=_state.drivers,
            vehicles=_state.vehicles,
            event_log=_state.event_log,
            storage_dir=settings.media_storage_dir,
            download_enabled=settings.media_download_enabled,
            max_download_bytes=settings.media_max_download_bytes,
        )
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )
    return MediaService(
        media_assets=SqlMediaAssetRepository(db_session),
        documents=SqlDocumentRepository(db_session),
        messages=SqlMessageRepository(db_session),
        carriers=SqlCarrierRepository(db_session),
        drivers=SqlDriverRepository(db_session),
        vehicles=SqlVehicleRepository(db_session),
        event_log=SqlEventLogService(db_session),
        storage_dir=settings.media_storage_dir,
        download_enabled=settings.media_download_enabled,
        max_download_bytes=settings.media_max_download_bytes,
    )


def get_speech_to_text_client() -> SpeechToTextClient | None:
    settings = get_settings()
    if settings.stt_provider.strip().lower() != "openai":
        return None
    if not settings.openai_api_key:
        return None
    return OpenAITranscriptionClient(api_key=settings.openai_api_key)


def get_transcription_service(
    media_service: MediaService = Depends(get_media_service),
    stt_client: SpeechToTextClient | None = Depends(get_speech_to_text_client),
    db_session: Session | None = Depends(get_request_db_session),
) -> TranscriptionService:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        return TranscriptionService(
            media_assets=_state.media_assets,
            event_log=_state.event_log,
            media_file_resolver=media_service,
            stt_client=stt_client,
            enabled=settings.stt_enabled,
            provider=settings.stt_provider,
            model=settings.stt_model,
            timeout_seconds=settings.stt_timeout_seconds,
            max_audio_bytes=settings.stt_max_audio_bytes,
        )
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )
    return TranscriptionService(
        media_assets=SqlMediaAssetRepository(db_session),
        event_log=SqlEventLogService(db_session),
        media_file_resolver=media_service,
        stt_client=stt_client,
        enabled=settings.stt_enabled,
        provider=settings.stt_provider,
        model=settings.stt_model,
        timeout_seconds=settings.stt_timeout_seconds,
        max_audio_bytes=settings.stt_max_audio_bytes,
    )


def get_conversation_orchestrator(
    ai_client: AIExtractionClient = Depends(get_ai_extraction_client),
    notification_service: NotificationService = Depends(get_notification_service),
    media_service: MediaService = Depends(get_media_service),
    transcription_service: TranscriptionService = Depends(get_transcription_service),
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[ConversationOrchestrator]:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        yield _state.conversation_orchestrator(
            ai_client,
            notification_service=notification_service,
            media_service=media_service,
            transcription_service=transcription_service,
            enable_test_role_switching=settings.enable_test_role_switching and not settings.is_production,
        )
        return
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )

    with db_session.begin():
        cargo_categories, cargo_types = load_active_cargo_catalog(db_session)
        geography_catalog = load_active_geography_catalog(db_session)
        if isinstance(ai_client, OpenAIExtractionClient):
            ai_client.configure_cargo_catalog(cargo_categories, cargo_types)
        admin_ops_service = build_sql_admin_ops_service(
            db_session,
            notification_service,
            enable_test_role_switching=settings.enable_test_role_switching and not settings.is_production,
        )
        yield build_sql_conversation_orchestrator(
            db_session,
            ai_client,
            notification_service=notification_service,
            media_service=media_service,
            transcription_service=transcription_service,
            admin_ops_service=admin_ops_service,
            enable_test_role_switching=settings.enable_test_role_switching and not settings.is_production,
            cargo_categories=cargo_categories,
            cargo_types=cargo_types,
            geography_catalog=geography_catalog,
        )


def get_backoffice_service(
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[BackofficeService]:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        yield BackofficeService(
            conversation_sessions=_state.conversation_sessions,
            messages=_state.messages,
            shipment_requests=_state.shipment_requests,
            trip_offers=_state.trip_offers,
            assignments=_state.assignments,
            trips=_state.trips,
            carriers=_state.carriers,
            carrier_onboardings=_state.carrier_onboardings,
            vehicles=_state.vehicles,
            documents=_state.documents,
            locations=_state.locations,
            event_logs=_state.event_log,
        )
        return
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )

    service = BackofficeService(
        conversation_sessions=SqlConversationSessionRepository(db_session),
        messages=SqlMessageRepository(db_session),
        shipment_requests=SqlShipmentRequestRepository(db_session),
        trip_offers=SqlTripOfferRepository(db_session),
        assignments=SqlAssignmentRepository(db_session),
        trips=SqlTripRepository(db_session),
        carriers=SqlCarrierRepository(db_session),
        carrier_onboardings=SqlCarrierOnboardingRepository(db_session),
        vehicles=SqlVehicleRepository(db_session),
        documents=SqlDocumentRepository(db_session),
        locations=SqlLocationRepository(db_session),
        event_logs=SqlEventLogService(db_session),
    )
    if db_session.in_transaction():
        yield service
        return

    with db_session.begin():
        yield service


def get_producer_backoffice_service(
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[ProducerBackofficeService]:
    settings = get_settings()
    if settings.storage_backend.lower() == "memory":
        yield ProducerBackofficeService(
            producers=_state.producers,
            shipments=_state.shipment_requests,
            offers=_state.trip_offers,
            assignments=_state.assignments,
            trips=_state.trips,
            conversations=_state.conversation_sessions,
            messages=_state.messages,
            locations=_state.locations,
            events=_state.event_log,
        )
        return
    if settings.storage_backend.lower() != "sql" or db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Producer backoffice requires configured memory or SQL storage",
        )

    service = ProducerBackofficeService(
        producers=SqlProducerRepository(db_session),
        shipments=SqlShipmentRequestRepository(db_session),
        offers=SqlTripOfferRepository(db_session),
        assignments=SqlAssignmentRepository(db_session),
        trips=SqlTripRepository(db_session),
        conversations=SqlConversationSessionRepository(db_session),
        messages=SqlMessageRepository(db_session),
        locations=SqlLocationRepository(db_session),
        events=SqlEventLogService(db_session),
    )
    if db_session.in_transaction():
        yield service
        return
    with db_session.begin():
        yield service


def get_carrier_onboarding_service(
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[CarrierOnboardingService]:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        yield CarrierOnboardingService(
            carriers=_state.carriers,
            vehicles=_state.vehicles,
            drivers=_state.drivers,
            trips=_state.trips,
            documents=_state.documents,
            onboardings=_state.carrier_onboardings,
            event_log=_state.event_log,
        )
        return
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )

    service = CarrierOnboardingService(
        carriers=SqlCarrierRepository(db_session),
        vehicles=SqlVehicleRepository(db_session),
        drivers=SqlDriverRepository(db_session),
        trips=SqlTripRepository(db_session),
        documents=SqlDocumentRepository(db_session),
        onboardings=SqlCarrierOnboardingRepository(db_session),
        event_log=SqlEventLogService(db_session),
    )
    if db_session.in_transaction():
        yield service
        return
    with db_session.begin():
        yield service


def get_whatsapp_allowlist_service(
    db_session: Session | None = Depends(get_request_db_session),
) -> Iterator[WhatsappAllowlistService]:
    settings = get_settings()
    kwargs = {
        "environment": settings.app_env.lower(),
        "source": settings.effective_whatsapp_allowlist_source,
        "default_allow": settings.effective_whatsapp_allowlist_default_allow,
        "env_allowlist": settings.whatsapp_allowlist,
    }
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        yield WhatsappAllowlistService(
            contacts=_state.whatsapp_allowed_contacts,
            event_log=_state.event_log,
            **kwargs,
        )
        return
    if storage_backend != "sql":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported storage backend: {settings.storage_backend}",
        )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SQL storage backend requires a database session",
        )

    service = WhatsappAllowlistService(
        contacts=SqlWhatsappAllowedContactRepository(db_session),
        event_log=SqlEventLogService(db_session),
        **kwargs,
    )
    if db_session.in_transaction():
        yield service
        return

    with db_session.begin():
        yield service


def get_route_availability_repository(
    db_session: Session | None = Depends(get_request_db_session),
):
    settings = get_settings()
    if settings.storage_backend.lower() == "memory":
        yield _state.route_availabilities
        return
    if settings.storage_backend.lower() != "sql" or db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Route availability requires configured memory or SQL storage",
        )
    repository = SqlRouteAvailabilityRepository(db_session)
    if db_session.in_transaction():
        yield repository
        return
    with db_session.begin():
        yield repository


def get_event_log_service(db_session: Session | None = Depends(get_request_db_session)):
    settings = get_settings()
    if settings.storage_backend.lower() == "memory":
        yield _state.event_log
        return
    if settings.storage_backend.lower() != "sql" or db_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Event log requires configured memory or SQL storage",
        )
    service = SqlEventLogService(db_session)
    if db_session.in_transaction():
        yield service
        return
    with db_session.begin():
        yield service


def require_operator_user(
    x_operator_user_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
    x_internal_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    """Resolve a local test user, a backend service, or a verified Supabase user."""

    settings = get_settings()
    expected_key = settings.internal_api_key
    if not settings.debug:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            try:
                claims = verify_supabase_access_token(token.strip(), settings)
            except SupabaseAuthConfigurationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Supabase Auth is not configured",
                ) from exc
            except jwt.PyJWTError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired access token",
                ) from exc
            except Exception as exc:  # JWKS network/configuration errors fail closed.
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Could not verify Supabase signing keys",
                ) from exc

            user_id = str(claims["sub"])
            if user_id == settings.supabase_bootstrap_admin_user_id:
                return AuthenticatedUser(user_id=user_id, role="admin")
            if settings.storage_backend.lower() != "sql":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Server-managed operator roles require SQL storage",
                )
            try:
                with get_session_factory(settings.database_url)() as role_session:
                    role_record = role_session.get(OperatorRoleRecord, user_id)
                    role = role_record.role if role_record and role_record.deleted_at is None else None
            except Exception as exc:  # A role lookup failure must never grant access.
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Could not verify backoffice role",
                ) from exc
            if role not in {"operator", "admin"}:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Backoffice access not granted")
            return AuthenticatedUser(user_id=user_id, role=role)

        if expected_key and hmac.compare_digest(x_internal_api_key or "", expected_key):
            # The key is held by the backend integration, never by the browser.
            return AuthenticatedUser(user_id="service:agro-backend-client", role="operator")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A verified Supabase session or internal service key is required",
        )
    if not x_operator_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator authentication required",
        )
    role = (x_operator_role or "operator").lower()
    if role not in {"operator", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator role required",
        )
    return AuthenticatedUser(user_id=x_operator_user_id, role=role)


def require_admin_user(
    operator: AuthenticatedUser = Depends(require_operator_user),
) -> AuthenticatedUser:
    if operator.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return operator
