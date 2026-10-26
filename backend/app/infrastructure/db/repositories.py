from collections.abc import Callable
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.events import EventLog
from app.domain.route_availability import RouteAvailability
from app.domain.models import (
    Assignment,
    Carrier,
    CarrierOnboarding,
    ConversationSession,
    Driver,
    Document,
    Location,
    MediaAsset,
    Message,
    PaymentTerms,
    Producer,
    RiskFlag,
    ShipmentRequest,
    Trip,
    TripOffer,
    User,
    Vehicle,
    WhatsappAllowedContact,
)
from app.infrastructure.db.models import (
    AssignmentRecord,
    CarrierRecord,
    CarrierOnboardingRecord,
    ConversationSessionRecord,
    DriverRecord,
    DocumentRecord,
    EventLogRecord,
    LocationRecord,
    MediaAssetRecord,
    MessageRecord,
    PaymentTermsRecord,
    ProducerRecord,
    RiskFlagRecord,
    RouteAvailabilityRecord,
    ShipmentRequestRecord,
    TripOfferRecord,
    TripRecord,
    UserRecord,
    VehicleRecord,
    WhatsappAllowedContactRecord,
)


DomainT = TypeVar("DomainT")
RecordT = TypeVar("RecordT")


class SqlRepository(Generic[DomainT, RecordT]):
    def __init__(
        self,
        session: Session,
        record_type: type[RecordT],
        to_record: Callable[[DomainT], RecordT],
        to_domain: Callable[[RecordT], DomainT],
    ) -> None:
        self._session = session
        self._record_type = record_type
        self._to_record = to_record
        self._to_domain = to_domain

    def add(self, entity: DomainT) -> DomainT:
        record = self._to_record(entity)
        self._session.add(record)
        self._session.flush()
        return entity

    def get(self, entity_id: str) -> DomainT | None:
        record = self._session.get(self._record_type, entity_id)
        if record is None:
            return None
        return self._to_domain(record)

    def list(self, *, include_deleted: bool = False) -> list[DomainT]:
        statement = select(self._record_type)
        if not include_deleted and hasattr(self._record_type, "deleted_at"):
            statement = statement.where(self._record_type.deleted_at.is_(None))  # type: ignore[attr-defined]
        return [self._to_domain(record) for record in self._session.scalars(statement).all()]

    def save(self, entity: DomainT) -> DomainT:
        record = self._to_record(entity)
        self._session.merge(record)
        self._session.flush()
        return entity

    def soft_delete(self, entity_id: str) -> DomainT:
        entity = self.get(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        if not hasattr(entity, "soft_delete"):
            raise TypeError(f"Entity does not support soft delete: {entity_id}")
        entity.soft_delete()  # type: ignore[attr-defined]
        return self.save(entity)


def _timestamps_from_record(record: object) -> dict[str, object]:
    return {
        "created_at": getattr(record, "created_at"),
        "updated_at": getattr(record, "updated_at"),
        "deleted_at": getattr(record, "deleted_at", None),
    }


def _record_values(record: object) -> dict[str, object]:
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}  # type: ignore[attr-defined]


def user_to_record(entity: User) -> UserRecord:
    return UserRecord(**entity.__dict__)


def user_to_domain(record: UserRecord) -> User:
    return User(**_record_values(record))


def producer_to_record(entity: Producer) -> ProducerRecord:
    return ProducerRecord(**entity.__dict__)


def producer_to_domain(record: ProducerRecord) -> Producer:
    return Producer(**_record_values(record))


def carrier_to_record(entity: Carrier) -> CarrierRecord:
    return CarrierRecord(**entity.__dict__)


def carrier_to_domain(record: CarrierRecord) -> Carrier:
    return Carrier(**_record_values(record))


def carrier_onboarding_to_record(entity: CarrierOnboarding) -> CarrierOnboardingRecord:
    return CarrierOnboardingRecord(**entity.__dict__)


def carrier_onboarding_to_domain(record: CarrierOnboardingRecord) -> CarrierOnboarding:
    return CarrierOnboarding(**_record_values(record))


def route_availability_to_record(entity: RouteAvailability) -> RouteAvailabilityRecord:
    return RouteAvailabilityRecord(**entity.__dict__)


def route_availability_to_domain(record: RouteAvailabilityRecord) -> RouteAvailability:
    return RouteAvailability(**_record_values(record))


def whatsapp_allowed_contact_to_record(entity: WhatsappAllowedContact) -> WhatsappAllowedContactRecord:
    return WhatsappAllowedContactRecord(**entity.__dict__)


def whatsapp_allowed_contact_to_domain(
    record: WhatsappAllowedContactRecord,
) -> WhatsappAllowedContact:
    return WhatsappAllowedContact(**_record_values(record))


def vehicle_to_record(entity: Vehicle) -> VehicleRecord:
    return VehicleRecord(**entity.__dict__)


def vehicle_to_domain(record: VehicleRecord) -> Vehicle:
    return Vehicle(**_record_values(record))


def driver_to_record(entity: Driver) -> DriverRecord:
    return DriverRecord(**entity.__dict__)


def driver_to_domain(record: DriverRecord) -> Driver:
    return Driver(**_record_values(record))


def location_to_record(entity: Location) -> LocationRecord:
    return LocationRecord(**entity.__dict__)


def location_to_domain(record: LocationRecord) -> Location:
    return Location(**_record_values(record))


def conversation_to_record(entity: ConversationSession) -> ConversationSessionRecord:
    return ConversationSessionRecord(**entity.__dict__)


def conversation_to_domain(record: ConversationSessionRecord) -> ConversationSession:
    return ConversationSession(**_record_values(record))


def message_to_record(entity: Message) -> MessageRecord:
    return MessageRecord(**entity.__dict__)


def message_to_domain(record: MessageRecord) -> Message:
    return Message(**_record_values(record))


def media_asset_to_record(entity: MediaAsset) -> MediaAssetRecord:
    return MediaAssetRecord(**entity.__dict__)


def media_asset_to_domain(record: MediaAssetRecord) -> MediaAsset:
    return MediaAsset(**_record_values(record))


def shipment_to_record(entity: ShipmentRequest) -> ShipmentRequestRecord:
    return ShipmentRequestRecord(**entity.__dict__)


def shipment_to_domain(record: ShipmentRequestRecord) -> ShipmentRequest:
    return ShipmentRequest(**_record_values(record))


def offer_to_record(entity: TripOffer) -> TripOfferRecord:
    return TripOfferRecord(**entity.__dict__)


def offer_to_domain(record: TripOfferRecord) -> TripOffer:
    return TripOffer(**_record_values(record))


def assignment_to_record(entity: Assignment) -> AssignmentRecord:
    return AssignmentRecord(**entity.__dict__)


def assignment_to_domain(record: AssignmentRecord) -> Assignment:
    return Assignment(**_record_values(record))


def trip_to_record(entity: Trip) -> TripRecord:
    return TripRecord(**entity.__dict__)


def trip_to_domain(record: TripRecord) -> Trip:
    return Trip(**_record_values(record))


def document_to_record(entity: Document) -> DocumentRecord:
    return DocumentRecord(**entity.__dict__)


def document_to_domain(record: DocumentRecord) -> Document:
    return Document(**_record_values(record))


def payment_terms_to_record(entity: PaymentTerms) -> PaymentTermsRecord:
    return PaymentTermsRecord(**entity.__dict__)


def payment_terms_to_domain(record: PaymentTermsRecord) -> PaymentTerms:
    return PaymentTerms(**_record_values(record))


def risk_flag_to_record(entity: RiskFlag) -> RiskFlagRecord:
    return RiskFlagRecord(**entity.__dict__)


def risk_flag_to_domain(record: RiskFlagRecord) -> RiskFlag:
    return RiskFlag(**_record_values(record))


def event_to_record(event: EventLog) -> EventLogRecord:
    return EventLogRecord(
        event_id=event.event_id,
        test_run_id=event.test_run_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        related_entity_ids=event.related_entity_ids,
        previous_state=event.previous_state,
        new_state=event.new_state,
        summary=event.summary,
        payload=event.payload,
        source=event.source,
        correlation_id=event.correlation_id,
        idempotency_key=event.idempotency_key,
    )


def event_to_domain(record: EventLogRecord) -> EventLog:
    return EventLog(
        event_id=record.event_id,
        test_run_id=record.test_run_id,
        event_type=record.event_type,
        occurred_at=record.occurred_at,
        actor_type=record.actor_type,
        actor_id=record.actor_id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        related_entity_ids=record.related_entity_ids,
        previous_state=record.previous_state,
        new_state=record.new_state,
        summary=record.summary,
        payload=record.payload,
        source=record.source,
        correlation_id=record.correlation_id,
        idempotency_key=record.idempotency_key,
    )


class SqlUserRepository(SqlRepository[User, UserRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, UserRecord, user_to_record, user_to_domain)


class SqlProducerRepository(SqlRepository[Producer, ProducerRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ProducerRecord, producer_to_record, producer_to_domain)


class SqlCarrierRepository(SqlRepository[Carrier, CarrierRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, CarrierRecord, carrier_to_record, carrier_to_domain)


class SqlCarrierOnboardingRepository(SqlRepository[CarrierOnboarding, CarrierOnboardingRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            CarrierOnboardingRecord,
            carrier_onboarding_to_record,
            carrier_onboarding_to_domain,
        )


class SqlRouteAvailabilityRepository(SqlRepository[RouteAvailability, RouteAvailabilityRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, RouteAvailabilityRecord, route_availability_to_record, route_availability_to_domain)


class SqlWhatsappAllowedContactRepository(
    SqlRepository[WhatsappAllowedContact, WhatsappAllowedContactRecord]
):
    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            WhatsappAllowedContactRecord,
            whatsapp_allowed_contact_to_record,
            whatsapp_allowed_contact_to_domain,
        )


class SqlVehicleRepository(SqlRepository[Vehicle, VehicleRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, VehicleRecord, vehicle_to_record, vehicle_to_domain)


class SqlDriverRepository(SqlRepository[Driver, DriverRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DriverRecord, driver_to_record, driver_to_domain)


class SqlLocationRepository(SqlRepository[Location, LocationRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, LocationRecord, location_to_record, location_to_domain)


class SqlConversationSessionRepository(SqlRepository[ConversationSession, ConversationSessionRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ConversationSessionRecord, conversation_to_record, conversation_to_domain)


class SqlMessageRepository(SqlRepository[Message, MessageRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MessageRecord, message_to_record, message_to_domain)


class SqlMediaAssetRepository(SqlRepository[MediaAsset, MediaAssetRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MediaAssetRecord, media_asset_to_record, media_asset_to_domain)


class SqlShipmentRequestRepository(SqlRepository[ShipmentRequest, ShipmentRequestRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ShipmentRequestRecord, shipment_to_record, shipment_to_domain)


class SqlTripOfferRepository(SqlRepository[TripOffer, TripOfferRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TripOfferRecord, offer_to_record, offer_to_domain)


class SqlAssignmentRepository(SqlRepository[Assignment, AssignmentRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AssignmentRecord, assignment_to_record, assignment_to_domain)


class SqlTripRepository(SqlRepository[Trip, TripRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TripRecord, trip_to_record, trip_to_domain)


class SqlDocumentRepository(SqlRepository[Document, DocumentRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DocumentRecord, document_to_record, document_to_domain)


class SqlPaymentTermsRepository(SqlRepository[PaymentTerms, PaymentTermsRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, PaymentTermsRecord, payment_terms_to_record, payment_terms_to_domain)


class SqlRiskFlagRepository(SqlRepository[RiskFlag, RiskFlagRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, RiskFlagRecord, risk_flag_to_record, risk_flag_to_domain)


class SqlEventLogRepository(SqlRepository[EventLog, EventLogRecord]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EventLogRecord, event_to_record, event_to_domain)

    def get_by_idempotency_key(self, idempotency_key: str) -> EventLog | None:
        record = self._session.scalar(
            select(EventLogRecord).where(EventLogRecord.idempotency_key == idempotency_key)
        )
        if record is None:
            return None
        return event_to_domain(record)
