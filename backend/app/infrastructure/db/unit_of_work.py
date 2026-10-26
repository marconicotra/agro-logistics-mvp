from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.application.routing_factory import build_routing
from app.core.config import get_settings
from app.application.admin_ops import AdminOpsService, AssignmentConfirmationResult
from app.application.ai import AIExtractionClient
from app.application.carrier_onboarding import CarrierOnboardingService
from app.application.conversation_orchestrator import ConversationOrchestrator
from app.application.media import MediaService
from app.application.notifications import NotificationService
from app.application.transcription import TranscriptionService
from app.domain.cargo import CargoCategoryDefinition, CargoTypeDefinition
from app.domain.location_catalog import GeographicCatalogEntry
from app.infrastructure.db.event_log import SqlEventLogService
from app.infrastructure.db.notification_outbox import cancel_unstarted_test_run_notifications
from app.infrastructure.db.repositories import (
    SqlAssignmentRepository,
    SqlCarrierOnboardingRepository,
    SqlCarrierRepository,
    SqlConversationSessionRepository,
    SqlDocumentRepository,
    SqlDriverRepository,
    SqlLocationRepository,
    SqlMessageRepository,
    SqlShipmentRequestRepository,
    SqlTripOfferRepository,
    SqlTripRepository,
    SqlVehicleRepository,
    SqlRouteAvailabilityRepository,
)


def build_sql_admin_ops_service(
    session: Session,
    notification_service: NotificationService | None = None,
    *,
    enable_test_role_switching: bool = False,
) -> AdminOpsService:
    def trip_readiness_guard(trip_id: str) -> None:
        CarrierOnboardingService(
            carriers=SqlCarrierRepository(session),
            vehicles=SqlVehicleRepository(session),
            drivers=SqlDriverRepository(session),
            trips=SqlTripRepository(session),
            documents=SqlDocumentRepository(session),
            onboardings=SqlCarrierOnboardingRepository(session),
            event_log=SqlEventLogService(session),
        ).ensure_trip_start_ready(trip_id)

    service = AdminOpsService(
        shipment_requests=SqlShipmentRequestRepository(session),
        trip_offers=SqlTripOfferRepository(session),
        assignments=SqlAssignmentRepository(session),
        trips=SqlTripRepository(session),
        carriers=SqlCarrierRepository(session),
        locations=SqlLocationRepository(session),
        conversation_sessions=SqlConversationSessionRepository(session),
        messages=SqlMessageRepository(session),
        event_log=SqlEventLogService(session),
        notification_service=notification_service,
        trip_readiness_guard=trip_readiness_guard,
        enable_test_role_switching=enable_test_role_switching,
    )

    if get_settings().route_operations_enabled:
        service._routing = build_routing(session=session, notifications=notification_service)
    return service


def build_sql_conversation_orchestrator(
    session: Session,
    ai_client: AIExtractionClient,
    *,
    admin_ops_service: AdminOpsService | None = None,
    notification_service: NotificationService | None = None,
    media_service: MediaService | None = None,
    transcription_service: TranscriptionService | None = None,
    enable_test_role_switching: bool = False,
    cargo_categories: list[CargoCategoryDefinition] | None = None,
    cargo_types: list[CargoTypeDefinition] | None = None,
    geography_catalog: list[GeographicCatalogEntry] | None = None,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        ai_client=ai_client,
        conversation_sessions=SqlConversationSessionRepository(session),
        messages=SqlMessageRepository(session),
        shipment_requests=SqlShipmentRequestRepository(session),
        locations=SqlLocationRepository(session),
        event_log=SqlEventLogService(session),
        route_availabilities=SqlRouteAvailabilityRepository(session),
        carriers=SqlCarrierRepository(session),
        carrier_onboarding_service=CarrierOnboardingService(
            carriers=SqlCarrierRepository(session),
            vehicles=SqlVehicleRepository(session),
            drivers=SqlDriverRepository(session),
            trips=SqlTripRepository(session),
            documents=SqlDocumentRepository(session),
            onboardings=SqlCarrierOnboardingRepository(session),
            event_log=SqlEventLogService(session),
        ),
        trip_offers=SqlTripOfferRepository(session),
        notification_service=notification_service,
        admin_ops_service=admin_ops_service,
        media_service=media_service,
        transcription_service=transcription_service,
        enable_test_role_switching=enable_test_role_switching,
        test_run_close_hook=lambda test_run_id: cancel_unstarted_test_run_notifications(session, test_run_id),
        cargo_categories=cargo_categories,
        cargo_types=cargo_types,
        geography_catalog=geography_catalog,
    )


class SqlUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session

    @contextmanager
    def transaction(self) -> Iterator[AdminOpsService]:
        with self._session.begin():
            yield build_sql_admin_ops_service(self._session)

    def confirm_assignment(
        self,
        *,
        assignment_id: str,
        operator_user_id: str,
        confirmation_notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> AssignmentConfirmationResult:
        with self.transaction() as service:
            return service.confirm_assignment(
                assignment_id=assignment_id,
                operator_user_id=operator_user_id,
                confirmation_notes=confirmation_notes,
                idempotency_key=idempotency_key,
            )
