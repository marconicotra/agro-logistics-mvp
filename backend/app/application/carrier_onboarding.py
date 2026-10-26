from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import re
from typing import Any, Generic, Protocol, TypeVar
import unicodedata

from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.domain.events import EventLog, EventLogService
from app.domain.equipment import normalize_equipment_or_declared
from app.domain.models import Carrier, CarrierOnboarding, Document, Driver, Trip, Vehicle, utc_now


class CarrierOnboardingError(ValueError):
    pass


T = TypeVar("T")


class Repository(Protocol, Generic[T]):
    def add(self, entity: T) -> T:
        pass

    def get(self, entity_id: str) -> T | None:
        pass

    def list(self, *, include_deleted: bool = False) -> list[T]:
        pass

    def save(self, entity: T) -> T:
        pass

    def soft_delete(self, entity_id: str) -> T:
        pass


class EventRecorder(Protocol):
    @property
    def events(self) -> tuple[EventLog, ...]:
        pass

    def record(
        self,
        *,
        event_type: str,
        actor_type: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        actor_id: str | None = None,
        related_entity_ids: dict[str, str] | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "system",
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> EventLog:
        pass


@dataclass(frozen=True)
class CarrierOnboardingPendingSummary:
    carrier_id: str
    onboarding_id: str | None
    name: str
    contact_phone: str | None
    phone: str | None
    email: str | None
    company_name: str | None
    cuit: str | None
    validation_status: str
    onboarding_status: str | None
    missing_fields: list[str]
    documents_count: int
    pending_documents_count: int
    created_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True)
class VehicleSummary:
    id: str
    vehicle_type: str | None
    capacity_estimate: object | None
    plate_number: str | None
    body_type: str | None
    status: str
    validation_status: str
    updated_at: datetime
    documents: tuple["DocumentSummary", ...] = ()


@dataclass(frozen=True)
class DriverSummary:
    id: str
    name: str
    phone: str | None
    license_category: str | None
    status: str
    validation_status: str
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    updated_at: datetime
    documents: tuple["DocumentSummary", ...] = ()


@dataclass(frozen=True)
class DocumentSummary:
    id: str
    entity_type: str
    entity_id: str
    document_type: str
    has_file: bool
    provider: str | None
    provider_media_id: str | None
    mime_type: str | None
    file_name: str | None
    uploaded_by_phone: str | None
    status: str
    notes: str | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    valid_from: date | None
    expires_at: date | None
    supersedes_document_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CarrierSummary:
    id: str
    name: str
    contact_phone: str | None
    phone: str | None
    email: str | None
    company_name: str | None
    cuit: str | None
    truck_count: int | None
    truck_types: list[str]
    truck_body_type: str | None
    is_validated: bool
    validation_status: str
    onboarding_status: str | None
    missing_fields: list[str]
    vehicles_count: int
    documents_count: int
    pending_documents_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CarrierCaptureProgress:
    step: str | None
    captured_vehicle_count: int
    declared_vehicle_count: int


@dataclass(frozen=True)
class CarrierOnboardingDetail:
    carrier: Carrier
    onboarding: CarrierOnboarding
    vehicles: tuple[VehicleSummary, ...]
    drivers: tuple[DriverSummary, ...]
    documents: tuple[DocumentSummary, ...]
    capture_progress: CarrierCaptureProgress
    events: tuple[EventLog, ...]


@dataclass(frozen=True)
class CarrierMutationInput:
    name: str
    phone: str | None = None
    email: str | None = None
    company_name: str | None = None
    cuit: str | None = None
    truck_count: int | None = None
    truck_types: list[str] | None = None
    truck_body_type: str | None = None


@dataclass(frozen=True)
class VehicleMutationInput:
    plate_number: str | None = None
    vehicle_type: str | None = None
    body_type: str | None = None
    capacity: Decimal | None = None
    status: str | None = None


@dataclass(frozen=True)
class DriverMutationInput:
    name: str
    phone: str | None = None
    license_category: str | None = None


@dataclass(frozen=True)
class DocumentMutationInput:
    document_type: str
    external_uri: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    notes: str | None = None
    storage_uri: str | None = None
    entity_type: str = "carrier"
    entity_id: str | None = None
    valid_from: date | None = None
    expires_at: date | None = None
    supersedes_document_id: str | None = None


class CarrierOnboardingService:
    REQUIRED_FIELDS = ("contact_phone", "cuit", "vehicle", "document")
    PENDING_STATUSES = {"DRAFT", "WAITING_DATA", "WAITING_DOCUMENTS", "PENDING_REVIEW", "REJECTED"}

    def __init__(
        self,
        *,
        carriers: Repository[Carrier],
        vehicles: Repository[Vehicle],
        drivers: Repository[Driver],
        trips: Repository[Trip],
        documents: Repository[Document],
        onboardings: Repository[CarrierOnboarding],
        event_log: EventRecorder | EventLogService,
    ) -> None:
        self._carriers = carriers
        self._vehicles = vehicles
        self._drivers = drivers
        self._trips = trips
        self._documents = documents
        self._onboardings = onboardings
        self._event_log = event_log

    def get_or_create_onboarding(self, carrier_id: str) -> CarrierOnboarding:
        carrier = self._require_carrier(carrier_id)
        existing = self._find_onboarding(carrier_id)
        if existing is not None:
            self._refresh_onboarding(existing, carrier)
            return self._onboardings.save(existing)

        onboarding = CarrierOnboarding(
            carrier_id=carrier.id,
            status=self._initial_onboarding_status(carrier),
            required_fields=list(self.REQUIRED_FIELDS),
            missing_fields=self.calculate_missing_fields(carrier),
        )
        onboarding = self._onboardings.add(onboarding)
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_CREATED",
            actor_type="SYSTEM",
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Homologacion de transportista creada",
            related_entity_ids={"carrierId": carrier.id},
            new_state=onboarding.status,
            payload={"missing_fields": onboarding.missing_fields},
            source="carrier_onboarding",
        )
        return onboarding

    def start_whatsapp_capture(self, *, phone: str, normalized_phone: str) -> tuple[Carrier, CarrierOnboarding, bool]:
        carrier = next(
            (
                item for item in self._carriers.list()
                if item.normalized_phone_number == normalized_phone
                or self._normalized_text(item.contact_phone) == phone
            ),
            None,
        )
        created = carrier is None
        if carrier is None:
            carrier = self._carriers.add(
                Carrier(
                    name="Alta WhatsApp pendiente",
                    contact_phone=phone,
                    normalized_phone_number=normalized_phone,
                    validation_status="DRAFT",
                )
            )
        if self._effective_validation_status(carrier) == "APPROVED":
            return carrier, self.get_or_create_onboarding(carrier.id), created

        onboarding = self.get_or_create_onboarding(carrier.id)
        if not onboarding.capture_context.get("step"):
            onboarding.capture_context = {"step": "carrier_name"}
            onboarding.mark_updated()
            self._onboardings.save(onboarding)
            self._event_log.record(
                event_type="CARRIER_ONBOARDING_STARTED_FROM_WHATSAPP",
                actor_type="CARRIER",
                actor_id=carrier.id,
                entity_type="CarrierOnboarding",
                entity_id=onboarding.id,
                summary="Solicitud de homologacion iniciada por WhatsApp",
                related_entity_ids={"carrierId": carrier.id},
                new_state=onboarding.status,
                payload={"created_profile": created},
                source="whatsapp",
            )
        return carrier, onboarding, created

    def capture_context(self, carrier_id: str) -> dict[str, str]:
        onboarding = self._find_onboarding(carrier_id)
        return dict(onboarding.capture_context) if onboarding is not None else {}

    def whatsapp_capture_prompt(self, carrier_id: str) -> str | None:
        onboarding = self._find_onboarding(carrier_id)
        if onboarding is None:
            return None
        if onboarding.capture_context.get("step") == "review_confirmation":
            return self._whatsapp_capture_summary(carrier_id, onboarding)
        if onboarding.capture_context.get("step") == "edit_field":
            return self._edit_field_prompt(onboarding)
        if onboarding.capture_context.get("step") == "edit_value":
            target = onboarding.capture_context.get("edit_target", "dato seleccionado")
            return f"Pasame el nuevo valor para {self._capture_edit_label(target)}."
        if onboarding.capture_context.get("step") == "complete":
            return self._capture_complete_message(carrier_id)
        return None

    def process_whatsapp_capture_response(
        self, *, carrier_id: str, text: str, correlation_id: str | None = None
    ) -> tuple[str, bool]:
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        step = onboarding.capture_context.get("step")
        value = text.strip()
        normalized = " ".join(value.lower().split())
        skip = normalized in {"no", "no tengo", "no corresponde", "ninguno", "ninguna", "-"}
        response_by_next_step = {
            "carrier_name": "¿Cuál es tu nombre y apellido o razón social?",
            "email": "¿Qué email podemos usar? Si no tenés, respondé «no tengo».",
            "company_name": "¿Tenés empresa? Decime el nombre o respondé «no corresponde».",
            "cuit": "Pasame el CUIT de 11 dígitos, sin puntos ni guiones.",
            "truck_count": "¿Cuántas unidades tenés? Respondé con un número.",
            "vehicle_plate": "Pasame la patente de una unidad para empezar.",
            "vehicle_type": "¿Qué tipo de camión es?",
            "vehicle_body_type": "¿Qué carrocería tiene? Por ejemplo, jaula o baranda.",
            "driver_name": "¿Quién va a manejar esa unidad? Indicá nombre y apellido.",
            "driver_phone": "Pasame el teléfono del conductor. Si usa este mismo número, respondé «mismo». ",
            "license_category": "¿Qué categoría figura en su licencia de conducir?",
            "driver_license_upload": "Ahora enviá una foto o archivo de la licencia de ese conductor.",
            "add_another_vehicle": "¿Querés cargar otra unidad y su conductor ahora? Respondé sí o no. Si preferís, soporte puede continuar el alta después.",
        }
        next_step: str | None = None
        if step == "carrier_name":
            if len(value) < 2:
                return response_by_next_step[step], False
            carrier.name = value
            self._carriers.save(carrier)
            next_step = "email"
        elif step == "email":
            if not skip and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
                return "Ese email no parece completo. Probá otra vez o respondé «no tengo».", False
            carrier.email = None if skip else value
            self._carriers.save(carrier)
            next_step = "company_name"
        elif step == "company_name":
            carrier.company_name = None if skip else value
            self._carriers.save(carrier)
            next_step = "cuit"
        elif step == "cuit":
            digits = "".join(character for character in value if character.isdigit())
            if len(digits) != 11:
                return response_by_next_step[step], False
            carrier.cuit = digits
            self._carriers.save(carrier)
            next_step = "truck_count"
        elif step == "truck_count":
            try:
                count = int(value)
            except ValueError:
                return response_by_next_step[step], False
            if count < 1 or count > 500:
                return response_by_next_step[step], False
            carrier.truck_count = count
            self._carriers.save(carrier)
            onboarding.capture_context["declared_vehicle_count"] = str(count)
            onboarding.capture_context["captured_vehicle_count"] = "0"
            next_step = "vehicle_plate"
        elif step == "vehicle_plate":
            plate = value.upper().replace(" ", "")
            vehicle = Vehicle(carrier_id=carrier_id, plate=plate, status="ACTIVE")
            self._vehicles.add(vehicle)
            onboarding.capture_context["vehicle_id"] = vehicle.id
            vehicle_ids = self._capture_context_ids(onboarding, "vehicle_ids")
            vehicle_ids.append(vehicle.id)
            onboarding.capture_context["vehicle_ids"] = ",".join(vehicle_ids)
            captured_count = int(onboarding.capture_context.get("captured_vehicle_count", "0")) + 1
            onboarding.capture_context["captured_vehicle_count"] = str(captured_count)
            self._event_log.record(
                event_type="CARRIER_VEHICLE_CAPTURED_FROM_WHATSAPP",
                actor_type="CARRIER",
                actor_id=carrier_id,
                entity_type="Vehicle",
                entity_id=vehicle.id,
                summary="Unidad declarada por WhatsApp; pendiente de revision",
                related_entity_ids={"carrierId": carrier_id},
                new_state=vehicle.validation_status,
                payload={"has_plate": bool(plate)},
                source="whatsapp",
                correlation_id=correlation_id,
            )
            next_step = "vehicle_type"
        elif step in {"vehicle_type", "vehicle_body_type"}:
            vehicle_id = onboarding.capture_context.get("vehicle_id")
            vehicle = self._vehicles.get(vehicle_id) if vehicle_id else None
            if vehicle is None or vehicle.carrier_id != carrier_id:
                onboarding.capture_context = {"step": "vehicle_plate"}
                self._onboardings.save(onboarding)
                return response_by_next_step["vehicle_plate"], False
            if step == "vehicle_type":
                vehicle.vehicle_type = normalize_equipment_or_declared(value)
                if vehicle.vehicle_type and vehicle.vehicle_type not in carrier.truck_types:
                    carrier.truck_types = [*carrier.truck_types, vehicle.vehicle_type]
                    self._carriers.save(carrier)
                next_step = "vehicle_body_type"
            else:
                vehicle.validation_flags = {
                    **vehicle.validation_flags,
                    "body_type": normalize_equipment_or_declared(value),
                }
                next_step = "driver_name"
            vehicle.validation_status = "PENDING_REVIEW"
            vehicle.mark_updated()
            self._vehicles.save(vehicle)
        elif step == "driver_name":
            if len(value) < 2:
                return response_by_next_step[step], False
            driver = Driver(carrier_id=carrier_id, name=value)
            self._drivers.add(driver)
            onboarding.capture_context["driver_id"] = driver.id
            driver_ids = self._capture_context_ids(onboarding, "driver_ids")
            driver_ids.append(driver.id)
            onboarding.capture_context["driver_ids"] = ",".join(driver_ids)
            self._event_log.record(
                event_type="CARRIER_DRIVER_CAPTURED_FROM_WHATSAPP",
                actor_type="CARRIER",
                actor_id=carrier_id,
                entity_type="Driver",
                entity_id=driver.id,
                summary="Conductor declarado por WhatsApp; pendiente de revision",
                related_entity_ids={"carrierId": carrier_id},
                new_state=driver.validation_status,
                payload={"has_phone": bool(driver.phone)},
                source="whatsapp",
                correlation_id=correlation_id,
            )
            next_step = "driver_phone"
        elif step == "driver_phone":
            driver_id = onboarding.capture_context.get("driver_id")
            driver = self._drivers.get(driver_id) if driver_id else None
            if driver is None or driver.carrier_id != carrier_id:
                onboarding.capture_context["step"] = "driver_name"
                self._onboardings.save(onboarding)
                return response_by_next_step["driver_name"], False
            if normalized in {"mismo", "este mismo numero", "este mismo número", "usa este", "igual"}:
                driver.phone = carrier.contact_phone
            else:
                phone_digits = "".join(character for character in value if character.isdigit())
                if not 8 <= len(phone_digits) <= 15:
                    return "Ese teléfono no parece válido. Pasalo con código de país o respondé «mismo».", False
                try:
                    driver.phone = normalize_phone_number(value)
                except PhoneNormalizationError:
                    return "Ese teléfono no parece válido. Pasalo con código de país o respondé «mismo».", False
            self._drivers.save(driver)
            next_step = "license_category"
        elif step == "license_category":
            driver_id = onboarding.capture_context.get("driver_id")
            driver = self._drivers.get(driver_id) if driver_id else None
            if driver is None or driver.carrier_id != carrier_id:
                onboarding.capture_context["step"] = "driver_name"
                self._onboardings.save(onboarding)
                return response_by_next_step["driver_name"], False
            driver.license_category = value
            driver.mark_updated()
            self._drivers.save(driver)
            next_step = "driver_license_upload"
        elif step == "driver_license_upload":
            return response_by_next_step[step], False
        elif step == "add_another_vehicle":
            answer = normalized.strip(" .!¡¿?")
            if answer in {"si", "sí", "dale", "otra", "agregar otra"}:
                onboarding.capture_context.pop("vehicle_id", None)
                onboarding.capture_context.pop("driver_id", None)
                next_step = "vehicle_plate"
            elif answer in {"no", "no gracias", "despues", "después", "soporte"}:
                onboarding.capture_context["step"] = "review_confirmation"
                onboarding.mark_updated()
                self._onboardings.save(onboarding)
                self._event_log.record(
                    event_type="CARRIER_ONBOARDING_READY_FOR_CONFIRMATION",
                    actor_type="CARRIER",
                    actor_id=carrier_id,
                    entity_type="CarrierOnboarding",
                    entity_id=onboarding.id,
                    summary="Captura parcial lista para confirmar; falta completar la flota declarada",
                    related_entity_ids={"carrierId": carrier_id},
                    payload={
                        "captured_vehicle_count": onboarding.capture_context.get("captured_vehicle_count", "0"),
                        "declared_vehicle_count": onboarding.capture_context.get("declared_vehicle_count", "0"),
                    },
                    source="whatsapp",
                    correlation_id=correlation_id,
                )
                self.recalculate_onboarding(carrier_id, actor_type="CARRIER", actor_id=carrier_id, source="whatsapp")
                return self._whatsapp_capture_summary(carrier_id, onboarding), False
            else:
                return response_by_next_step[step], False
        elif step == "review_confirmation":
            answer = self._normalize_capture_text(value).strip(" .!¡¿?")
            if answer in {"confirmar", "confirmo", "1", "si", "correcto", "enviar"}:
                onboarding.capture_context["step"] = "complete"
                onboarding.mark_updated()
                self._onboardings.save(onboarding)
                self._record_whatsapp_capture_complete(carrier_id, onboarding)
                return self._capture_complete_message(carrier_id), False
            if answer in {"editar", "2", "corregir"}:
                onboarding.capture_context["step"] = "edit_field"
                onboarding.mark_updated()
                self._onboardings.save(onboarding)
                return self._edit_field_prompt(onboarding), False
            return self._whatsapp_capture_summary(carrier_id, onboarding), False
        elif step == "edit_field":
            target = self._resolve_capture_edit_target(onboarding, value)
            if target is None:
                return self._edit_field_prompt(onboarding), False
            onboarding.capture_context["edit_target"] = target
            onboarding.capture_context["step"] = "edit_value"
            onboarding.mark_updated()
            self._onboardings.save(onboarding)
            return f"Pasame el nuevo valor para {self._capture_edit_label(target)}.", False
        elif step == "edit_value":
            target = onboarding.capture_context.get("edit_target")
            if not target:
                onboarding.capture_context["step"] = "edit_field"
                self._onboardings.save(onboarding)
                return self._edit_field_prompt(onboarding), False
            validation_error = self._apply_capture_edit(carrier, onboarding, target, value)
            if validation_error:
                return validation_error, False
            onboarding.capture_context.pop("edit_target", None)
            onboarding.capture_context["step"] = "review_confirmation"
            onboarding.mark_updated()
            self._onboardings.save(onboarding)
            self._event_log.record(
                event_type="CARRIER_ONBOARDING_FIELD_CORRECTED",
                actor_type="CARRIER",
                actor_id=carrier_id,
                entity_type="CarrierOnboarding",
                entity_id=onboarding.id,
                summary="Dato de homologacion corregido desde WhatsApp",
                related_entity_ids={"carrierId": carrier_id},
                payload={"field": self._capture_edit_label(target)},
                source="whatsapp",
                correlation_id=correlation_id,
            )
            self.recalculate_onboarding(carrier_id, actor_type="CARRIER", actor_id=carrier_id, source="whatsapp")
            return self._whatsapp_capture_summary(carrier_id, onboarding), False
        elif step == "complete":
            return self._capture_complete_message(carrier_id), False
        else:
            onboarding.capture_context = {"step": "carrier_name"}
            next_step = "carrier_name"

        if next_step:
            onboarding.capture_context["step"] = next_step
            onboarding.mark_updated()
            self._onboardings.save(onboarding)
            self._event_log.record(
                event_type="CARRIER_ONBOARDING_FIELD_CAPTURED",
                actor_type="CARRIER",
                actor_id=carrier_id,
                entity_type="CarrierOnboarding",
                entity_id=onboarding.id,
                summary="Dato de homologacion guardado desde WhatsApp",
                related_entity_ids={"carrierId": carrier_id},
                payload={"field": step or "unknown"},
                source="whatsapp",
                correlation_id=correlation_id,
            )
            self.recalculate_onboarding(carrier_id, actor_type="CARRIER", actor_id=carrier_id, source="whatsapp")
        return response_by_next_step.get(next_step or "", "No pude continuar con el alta. Soporte revisará la solicitud."), False

    def complete_whatsapp_document_capture(self, *, carrier_id: str, driver_id: str) -> str | None:
        driver = self._require_carrier_driver(carrier_id, driver_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        if onboarding.capture_context.get("step") != "driver_license_upload":
            return None
        if onboarding.capture_context.get("driver_id") != driver.id:
            return None
        captured_count = int(onboarding.capture_context.get("captured_vehicle_count", "1"))
        declared_count = int(onboarding.capture_context.get("declared_vehicle_count", "1"))
        onboarding.capture_context["step"] = (
            "add_another_vehicle" if captured_count < declared_count else "review_confirmation"
        )
        onboarding.mark_updated()
        self._onboardings.save(onboarding)
        if onboarding.capture_context["step"] == "review_confirmation":
            self._event_log.record(
                event_type="CARRIER_ONBOARDING_READY_FOR_CONFIRMATION",
                actor_type="CARRIER",
                actor_id=carrier_id,
                entity_type="CarrierOnboarding",
                entity_id=onboarding.id,
                summary="Captura lista para confirmar por WhatsApp",
                related_entity_ids={"carrierId": carrier_id},
                payload={"captured_vehicle_count": captured_count, "declared_vehicle_count": declared_count},
                source="whatsapp",
            )
            self.recalculate_onboarding(carrier_id, actor_type="CARRIER", actor_id=carrier_id, source="whatsapp")
            return self._whatsapp_capture_summary(carrier_id, onboarding)

        self._event_log.record(
            event_type="CARRIER_ONBOARDING_DRIVER_LICENSE_RECEIVED",
            actor_type="CARRIER",
            actor_id=carrier_id,
            entity_type="Driver",
            entity_id=driver.id,
            summary="Licencia recibida; pendiente de revision de soporte",
            related_entity_ids={"carrierId": carrier_id, "driverId": driver.id},
            payload={"captured_vehicle_count": captured_count, "declared_vehicle_count": declared_count},
            source="whatsapp",
        )
        self.recalculate_onboarding(carrier_id, actor_type="CARRIER", actor_id=carrier_id, source="whatsapp")
        return (
            f"Unidad {captured_count} de {declared_count} y licencia recibidas; quedan pendientes de revisión. "
            "¿Querés cargar otra unidad y su conductor ahora? Respondé sí o no."
        )

    def _record_whatsapp_capture_complete(self, carrier_id: str, onboarding: CarrierOnboarding) -> None:
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_DATA_CAPTURED",
            actor_type="CARRIER",
            actor_id=carrier_id,
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Datos y licencias recibidos; requieren revision de soporte",
            related_entity_ids={"carrierId": carrier_id},
            payload={"captured_vehicle_count": onboarding.capture_context.get("captured_vehicle_count", "0")},
            source="whatsapp",
        )
        self.recalculate_onboarding(carrier_id, actor_type="CARRIER", actor_id=carrier_id, source="whatsapp")

    def _capture_complete_message(self, carrier_id: str) -> str:
        onboarding = self.get_or_create_onboarding(carrier_id)
        captured = onboarding.capture_context.get("captured_vehicle_count", "0")
        declared = onboarding.capture_context.get("declared_vehicle_count", "0")
        continuation = (
            f" Se cargaron {captured} de {declared} unidades declaradas; soporte deberá completar el resto."
            if captured != declared
            else f" Se cargaron las {captured} unidades declaradas."
        )
        return (
            "Listo, guardé los datos declarados y las licencias de los conductores."
            f"{continuation} Soporte revisará la información y te indicará si falta algo. "
            "Todavía no estás homologado ni habilitado para recibir cargas o iniciar viajes."
        )

    def _whatsapp_capture_summary(
        self, carrier_id: str, onboarding: CarrierOnboarding | None = None
    ) -> str:
        carrier = self._require_carrier(carrier_id)
        onboarding = onboarding or self.get_or_create_onboarding(carrier_id)
        context = onboarding.capture_context
        vehicle_ids = self._capture_context_ids(onboarding, "vehicle_ids")
        driver_ids = self._capture_context_ids(onboarding, "driver_ids")
        lines = [
            "Revisá los datos que registré para tu alta como transportista:",
            f"• Nombre / razón social: {carrier.name}",
            f"• Teléfono de contacto: {carrier.contact_phone or 'sin informar'}",
            f"• Email: {carrier.email or 'sin informar'}",
            f"• Empresa: {carrier.company_name or 'no corresponde'}",
            f"• CUIT declarado: {carrier.cuit or 'sin informar'}",
            f"• Unidades declaradas: {carrier.truck_count or 0}",
        ]
        if not vehicle_ids:
            lines.append("• No quedó ninguna unidad registrada")
        for index, vehicle_id in enumerate(vehicle_ids, start=1):
            vehicle = self._vehicles.get(vehicle_id)
            if vehicle is None or vehicle.carrier_id != carrier_id:
                continue
            driver = None
            if index <= len(driver_ids):
                candidate = self._drivers.get(driver_ids[index - 1])
                if candidate is not None and candidate.carrier_id == carrier_id:
                    driver = candidate
            lines.append(
                f"• Unidad {index}: {vehicle.plate or 'patente pendiente'}; "
                f"{vehicle.vehicle_type or 'tipo pendiente'}; "
                f"{vehicle.validation_flags.get('body_type', 'carrocería pendiente')}"
            )
            if driver is None:
                lines.append(f"  Conductor {index}: pendiente")
            else:
                license_doc_received = any(
                    document.entity_type.lower() == "driver"
                    and document.entity_id == driver.id
                    and document.document_type.lower() == "licencia"
                    for document in self._documents.list()
                )
                lines.append(
                    f"  Conductor {index}: {driver.name}; {driver.phone or 'teléfono pendiente'}; "
                    f"licencia {driver.license_category or 'sin categoría'}; "
                    f"archivo {'recibido' if license_doc_received else 'pendiente'}"
                )
        captured_count = context.get("captured_vehicle_count", "0")
        declared_count = context.get("declared_vehicle_count", "0")
        if captured_count != declared_count:
            lines.append(f"• Flota incompleta: registradas {captured_count} de {declared_count}; soporte puede cargar el resto")
        lines.append("¿Confirmás estos datos o querés editar algo? Respondé CONFIRMAR o EDITAR.")
        return "\n".join(lines)

    def _edit_field_prompt(self, onboarding: CarrierOnboarding) -> str:
        units = len(self._capture_context_ids(onboarding, "vehicle_ids"))
        choices = ["nombre", "email", "empresa", "CUIT", "cantidad de unidades"]
        for index in range(1, units + 1):
            choices.extend(
                (
                    f"patente unidad {index}",
                    f"tipo unidad {index}",
                    f"carrocería unidad {index}",
                    f"nombre conductor {index}",
                    f"teléfono conductor {index}",
                    f"categoría licencia conductor {index}",
                )
            )
        return "¿Qué dato querés cambiar? Escribí uno de estos: " + "; ".join(choices) + "."

    def _resolve_capture_edit_target(self, onboarding: CarrierOnboarding, raw_value: str) -> str | None:
        value = self._normalize_capture_text(raw_value).strip(" .!¡¿?")
        simple_targets = {
            "nombre": "carrier:name",
            "nombre razon social": "carrier:name",
            "razon social": "carrier:name",
            "email": "carrier:email",
            "empresa": "carrier:company_name",
            "cuit": "carrier:cuit",
            "cantidad de unidades": "carrier:truck_count",
            "camiones": "carrier:truck_count",
        }
        if value in simple_targets:
            return simple_targets[value]
        patterns = (
            (r"patente (?:de )?(?:unidad )?(\d+)", "vehicle", "plate"),
            (r"tipo (?:de )?(?:camion|unidad )?(\d+)", "vehicle", "vehicle_type"),
            (r"carroceria (?:de )?(?:unidad )?(\d+)", "vehicle", "body_type"),
            (r"nombre (?:del )?conductor (\d+)", "driver", "name"),
            (r"telefono (?:del )?conductor (\d+)", "driver", "phone"),
            (r"(?:categoria )?licencia (?:del )?conductor (\d+)", "driver", "license_category"),
        )
        for pattern, entity_type, field_name in patterns:
            match = re.fullmatch(pattern, value)
            if match is None:
                continue
            index = int(match.group(1)) - 1
            ids = self._capture_context_ids(onboarding, f"{entity_type}_ids")
            if index < 0 or index >= len(ids):
                return None
            return f"{entity_type}:{ids[index]}:{field_name}"
        return None

    def _capture_edit_label(self, target: str) -> str:
        parts = target.split(":")
        if parts[0] == "carrier":
            return {
                "name": "nombre",
                "email": "email",
                "company_name": "empresa",
                "cuit": "CUIT",
                "truck_count": "cantidad de unidades",
            }.get(parts[1], parts[1])
        entity_type, _, field_name = parts
        labels = {
            "plate": "patente",
            "vehicle_type": "tipo de unidad",
            "body_type": "carroceria",
            "name": "nombre del conductor",
            "phone": "telefono del conductor",
            "license_category": "categoria de licencia",
        }
        return f"{labels.get(field_name, field_name)} ({entity_type})"

    def _apply_capture_edit(
        self, carrier: Carrier, onboarding: CarrierOnboarding, target: str, value: str
    ) -> str | None:
        parts = target.split(":")
        if parts[0] == "carrier":
            field_name = parts[1]
            if field_name == "name":
                if len(value.strip()) < 2:
                    return "El nombre debe tener al menos dos caracteres. Probá otra vez."
                carrier.name = value.strip()
            elif field_name == "email":
                normalized = self._normalize_capture_text(value)
                if normalized not in {"no tengo", "ninguno", ""} and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
                    return "Ese email no parece completo. Probá otra vez o respondé «no tengo»."
                carrier.email = None if normalized in {"no tengo", "ninguno", ""} else value.strip()
            elif field_name == "company_name":
                carrier.company_name = None if self._normalize_capture_text(value) in {"no corresponde", "no tengo", "ninguno"} else value.strip()
            elif field_name == "cuit":
                digits = "".join(character for character in value if character.isdigit())
                if len(digits) != 11:
                    return "El CUIT debe tener 11 dígitos. Probá otra vez."
                carrier.cuit = digits
            elif field_name == "truck_count":
                try:
                    count = int(value)
                except ValueError:
                    return "La cantidad de unidades debe ser un número. Probá otra vez."
                captured = int(onboarding.capture_context.get("captured_vehicle_count", "0"))
                if count < max(1, captured) or count > 500:
                    return f"La cantidad debe ser al menos {max(1, captured)} y no superar 500. Probá otra vez."
                carrier.truck_count = count
                onboarding.capture_context["declared_vehicle_count"] = str(count)
                onboarding.mark_updated()
                self._onboardings.save(onboarding)
            self._carriers.save(carrier)
            return None

        entity_type, entity_id, field_name = parts
        if entity_type == "vehicle":
            entity = self._vehicles.get(entity_id)
            if entity is None or entity.carrier_id != carrier.id:
                return "No encontré esa unidad de tu alta. Elegí otra vez el dato a cambiar."
            if field_name == "plate":
                entity.plate = value.upper().replace(" ", "")
            elif field_name == "vehicle_type":
                entity.vehicle_type = normalize_equipment_or_declared(value)
            elif field_name == "body_type":
                entity.validation_flags = {
                    **entity.validation_flags,
                    "body_type": normalize_equipment_or_declared(value),
                }
            entity.validation_status = "PENDING_REVIEW"
            entity.mark_updated()
            self._vehicles.save(entity)
            return None

        entity = self._drivers.get(entity_id)
        if entity is None or entity.carrier_id != carrier.id:
            return "No encontré ese conductor de tu alta. Elegí otra vez el dato a cambiar."
        if field_name == "name":
            if len(value.strip()) < 2:
                return "El nombre debe tener al menos dos caracteres. Probá otra vez."
            entity.name = value.strip()
        elif field_name == "phone":
            if self._normalize_capture_text(value) in {"mismo", "este mismo numero", "usa este"}:
                entity.phone = carrier.contact_phone
            else:
                digits = "".join(character for character in value if character.isdigit())
                if not 8 <= len(digits) <= 15:
                    return "Ese teléfono no parece válido. Pasalo con código de país o respondé «mismo»."
                try:
                    entity.phone = normalize_phone_number(value)
                except PhoneNormalizationError:
                    return "Ese teléfono no parece válido. Pasalo con código de país o respondé «mismo»."
        elif field_name == "license_category":
            entity.license_category = value.strip()
        entity.mark_updated()
        self._drivers.save(entity)
        return None

    def _capture_context_ids(self, onboarding: CarrierOnboarding, key: str) -> list[str]:
        return [value for value in onboarding.capture_context.get(key, "").split(",") if value]

    def _normalize_capture_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.lower())
        return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())

    def list_carriers(
        self,
        *,
        validation_status: str | None = None,
        pending_only: bool = False,
        onboarding_pending_only: bool = False,
        is_validated: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CarrierSummary]:
        normalized_search = (search or "").strip().lower()
        rows: list[CarrierSummary] = []
        for carrier in self._carriers.list():
            effective_status = self._effective_validation_status(carrier)
            if pending_only and effective_status in {"APPROVED", "REJECTED", "SUSPENDED"}:
                continue
            if validation_status and effective_status != validation_status:
                continue
            if is_validated is not None and carrier.is_validated is not is_validated:
                continue
            vehicles = self._carrier_vehicles(carrier.id)
            documents = self._carrier_documents(carrier.id)
            onboarding = self._onboarding_snapshot(carrier)
            if onboarding_pending_only and onboarding.status != "PENDING_REVIEW":
                continue
            if normalized_search and not self._matches_carrier_search(
                carrier,
                vehicles,
                normalized_search,
            ):
                continue
            rows.append(
                CarrierSummary(
                    id=carrier.id,
                    name=carrier.name,
                    contact_phone=carrier.contact_phone,
                    phone=carrier.normalized_phone_number or carrier.contact_phone,
                    email=carrier.email,
                    company_name=carrier.company_name,
                    cuit=carrier.cuit,
                    truck_count=carrier.truck_count,
                    truck_types=list(carrier.truck_types),
                    truck_body_type=carrier.truck_body_type,
                    is_validated=carrier.is_validated,
                    validation_status=effective_status,
                    onboarding_status=onboarding.status,
                    missing_fields=list(onboarding.missing_fields),
                    vehicles_count=len(vehicles),
                    documents_count=len(documents),
                    pending_documents_count=sum(1 for document in documents if document.status == "PENDING"),
                    created_at=carrier.created_at,
                    updated_at=carrier.updated_at,
                )
            )
        rows.sort(key=lambda item: item.created_at, reverse=True)
        start = max(offset, 0)
        return rows[start : start + max(min(limit, 200), 1)]

    def create_carrier(
        self,
        *,
        operator_user_id: str,
        data: CarrierMutationInput,
    ) -> CarrierOnboardingDetail:
        carrier = Carrier(
            name=data.name.strip(),
            contact_phone=self._normalized_text(data.phone),
            normalized_phone_number=self._normalized_text(data.phone),
            email=self._normalized_text(data.email),
            company_name=self._normalized_text(data.company_name),
            cuit=self._normalized_text(data.cuit),
            truck_count=data.truck_count,
            truck_types=self._normalized_equipment_list(data.truck_types),
            truck_body_type=normalize_equipment_or_declared(data.truck_body_type),
            validation_status="DRAFT",
            is_validated=False,
        )
        self._carriers.add(carrier)
        onboarding = self.get_or_create_onboarding(carrier.id)
        self._event_log.record(
            event_type="CARRIER_CREATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Transportista creado manualmente",
            related_entity_ids={"carrierOnboardingId": onboarding.id},
            new_state=carrier.validation_status,
            payload=self._carrier_payload(carrier),
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier.id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self.detail(carrier.id)

    def update_carrier(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        data: CarrierMutationInput,
    ) -> CarrierOnboardingDetail:
        carrier = self._require_carrier(carrier_id)
        before = self._carrier_payload(carrier)
        previous_status = self._effective_validation_status(carrier)
        carrier.name = data.name.strip()
        carrier.contact_phone = self._normalized_text(data.phone)
        carrier.normalized_phone_number = self._normalized_text(data.phone)
        carrier.email = self._normalized_text(data.email)
        carrier.company_name = self._normalized_text(data.company_name)
        carrier.cuit = self._normalized_text(data.cuit)
        carrier.truck_count = data.truck_count
        carrier.truck_types = self._normalized_equipment_list(data.truck_types)
        carrier.truck_body_type = normalize_equipment_or_declared(data.truck_body_type)
        carrier.mark_updated()
        self._carriers.save(carrier)
        after = self._carrier_payload(carrier)
        changed_fields = self._changed_fields(before, after)
        self._event_log.record(
            event_type="CARRIER_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Datos de transportista actualizados",
            previous_state=previous_status,
            new_state=self._effective_validation_status(carrier),
            payload={
                "changed_fields": changed_fields,
                "previous_values": {key: before[key] for key in changed_fields},
                "new_values": {key: after[key] for key in changed_fields},
            },
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier.id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self.detail(carrier.id)

    def suspend_carrier(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        reason: str,
    ) -> CarrierOnboardingDetail:
        if not reason.strip():
            raise CarrierOnboardingError("reason is required")
        carrier = self._require_carrier(carrier_id)
        previous_status = self._effective_validation_status(carrier)
        carrier.is_validated = False
        carrier.validation_status = "SUSPENDED"
        carrier.reviewed_by_user_id = operator_user_id
        carrier.validated_at = None
        carrier.rejected_at = utc_now()
        carrier.rejection_reason = reason.strip()
        carrier.mark_updated()
        self._carriers.save(carrier)
        self._event_log.record(
            event_type="CARRIER_SUSPENDED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Transportista suspendido",
            previous_state=previous_status,
            new_state=carrier.validation_status,
            payload={"reason": reason.strip()},
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier.id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self.detail(carrier.id)

    def mark_in_review(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        notes: str | None = None,
    ) -> CarrierOnboardingDetail:
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        previous_status = self._effective_validation_status(carrier)
        previous_onboarding_status = onboarding.status
        carrier.is_validated = False
        carrier.validation_status = "PENDING_REVIEW"
        carrier.reviewed_by_user_id = operator_user_id
        carrier.rejected_at = None
        carrier.rejection_reason = None
        carrier.mark_updated()
        self._carriers.save(carrier)
        onboarding.status = self._status_for_missing_fields(self.calculate_missing_fields(carrier))
        onboarding.reviewed_by_user_id = None
        onboarding.reviewed_at = None
        onboarding.rejection_reason = None
        onboarding.submitted_at = utc_now()
        onboarding.mark_updated()
        self._onboardings.save(onboarding)
        self._event_log.record(
            event_type="CARRIER_MARKED_IN_REVIEW",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Transportista marcado para revision",
            related_entity_ids={"carrierOnboardingId": onboarding.id},
            previous_state=previous_status,
            new_state=carrier.validation_status,
            payload={"notes": self._normalized_text(notes)},
            source="backoffice",
        )
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_STATUS_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Estado de homologacion actualizado",
            related_entity_ids={"carrierId": carrier.id},
            previous_state=previous_onboarding_status,
            new_state=onboarding.status,
            payload={"notes": self._normalized_text(notes)},
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier.id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self.detail(carrier.id)

    def create_vehicle(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        data: VehicleMutationInput,
    ) -> VehicleSummary:
        self._require_carrier(carrier_id)
        vehicle = Vehicle(
            carrier_id=carrier_id,
            plate=self._normalized_text(data.plate_number),
            vehicle_type=normalize_equipment_or_declared(data.vehicle_type),
            capacity_estimate=data.capacity,
            status=(data.status or "ACTIVE").strip().upper(),
            validation_flags=self._vehicle_flags(body_type=data.body_type),
        )
        self._vehicles.add(vehicle)
        self._event_log.record(
            event_type="CARRIER_VEHICLE_CREATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Vehicle",
            entity_id=vehicle.id,
            summary="Vehiculo de transportista creado",
            related_entity_ids={"carrierId": carrier_id},
            new_state=vehicle.status,
            payload=self._vehicle_payload(vehicle),
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier_id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self._vehicle_summary(vehicle)

    def update_vehicle(
        self,
        *,
        carrier_id: str,
        vehicle_id: str,
        operator_user_id: str,
        data: VehicleMutationInput,
    ) -> VehicleSummary:
        vehicle = self._require_carrier_vehicle(carrier_id, vehicle_id)
        before = self._vehicle_payload(vehicle)
        if data.plate_number is not None:
            vehicle.plate = self._normalized_text(data.plate_number)
        if data.vehicle_type is not None:
            vehicle.vehicle_type = normalize_equipment_or_declared(data.vehicle_type)
        if data.capacity is not None:
            vehicle.capacity_estimate = data.capacity
        if data.status is not None:
            vehicle.status = data.status.strip().upper()
        if data.body_type is not None:
            flags = dict(vehicle.validation_flags)
            body_type = normalize_equipment_or_declared(data.body_type)
            if body_type:
                flags["body_type"] = body_type
            else:
                flags.pop("body_type", None)
            vehicle.validation_flags = flags
        after = self._vehicle_payload(vehicle)
        changed_fields = self._changed_fields(before, after)
        if changed_fields:
            vehicle.validation_status = "PENDING_REVIEW"
            vehicle.reviewed_by_user_id = None
            vehicle.reviewed_at = None
        vehicle.mark_updated()
        self._vehicles.save(vehicle)
        self._event_log.record(
            event_type="CARRIER_VEHICLE_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Vehicle",
            entity_id=vehicle.id,
            summary="Vehiculo de transportista actualizado",
            related_entity_ids={"carrierId": carrier_id},
            previous_state=before["status"],
            new_state=after["status"],
            payload={
                "changed_fields": changed_fields,
                "previous_values": {key: before[key] for key in changed_fields},
                "new_values": {key: after[key] for key in changed_fields},
            },
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier_id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self._vehicle_summary(vehicle)

    def approve_vehicle(
        self,
        *,
        carrier_id: str,
        vehicle_id: str,
        operator_user_id: str,
        notes: str | None = None,
    ) -> VehicleSummary:
        if not notes or not notes.strip():
            raise CarrierOnboardingError("Review notes are required to approve a vehicle")
        vehicle = self._require_carrier_vehicle(carrier_id, vehicle_id)
        if vehicle.status == "INACTIVE":
            raise CarrierOnboardingError("Cannot approve an inactive vehicle")
        previous_status = vehicle.validation_status
        vehicle.validation_status = "APPROVED"
        vehicle.reviewed_by_user_id = operator_user_id
        vehicle.reviewed_at = utc_now()
        vehicle.mark_updated()
        self._vehicles.save(vehicle)
        self._event_log.record(
            event_type="CARRIER_VEHICLE_APPROVED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Vehicle",
            entity_id=vehicle.id,
            summary="Unidad revisada por soporte",
            related_entity_ids={"carrierId": carrier_id},
            previous_state=previous_status,
            new_state=vehicle.validation_status,
            payload={"notes": self._normalized_text(notes)},
            source="backoffice",
        )
        return self._vehicle_summary(vehicle)

    def list_drivers(self, carrier_id: str) -> list[DriverSummary]:
        self._require_carrier(carrier_id)
        return [
            self._driver_summary(driver, include_documents=True)
            for driver in sorted(
                (item for item in self._drivers.list() if item.carrier_id == carrier_id),
                key=lambda item: item.created_at,
                reverse=True,
            )
        ]

    def list_documents(self, carrier_id: str) -> list[DocumentSummary]:
        self._require_carrier(carrier_id)
        documents = [
            document for document in self._documents.list()
            if self._document_belongs_to_carrier(document, carrier_id)
        ]
        documents.sort(key=lambda item: item.created_at, reverse=True)
        return [self._document_summary(document) for document in documents]

    def create_driver(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        data: DriverMutationInput,
    ) -> DriverSummary:
        self._require_carrier(carrier_id)
        name = self._normalized_text(data.name)
        if not name:
            raise CarrierOnboardingError("Driver name is required")
        driver = Driver(
            carrier_id=carrier_id,
            name=name,
            phone=self._normalized_text(data.phone),
            license_category=self._normalized_text(data.license_category),
        )
        self._drivers.add(driver)
        self._event_log.record(
            event_type="CARRIER_DRIVER_CREATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Driver",
            entity_id=driver.id,
            summary="Conductor agregado al transportista",
            related_entity_ids={"carrierId": carrier_id},
            new_state=driver.validation_status,
            payload={"license_category": driver.license_category},
            source="backoffice",
        )
        return self._driver_summary(driver)

    def approve_driver(
        self,
        *,
        carrier_id: str,
        driver_id: str,
        operator_user_id: str,
        notes: str | None = None,
    ) -> DriverSummary:
        if not notes or not notes.strip():
            raise CarrierOnboardingError("Review notes are required to approve a driver")
        driver = self._require_carrier_driver(carrier_id, driver_id)
        if driver.status != "ACTIVE":
            raise CarrierOnboardingError("Cannot approve an inactive driver")
        if not driver.license_category:
            raise CarrierOnboardingError("Driver license category must be recorded before review")
        previous_status = driver.validation_status
        driver.validation_status = "APPROVED"
        driver.reviewed_by_user_id = operator_user_id
        driver.reviewed_at = utc_now()
        driver.rejection_reason = None
        driver.mark_updated()
        self._drivers.save(driver)
        self._event_log.record(
            event_type="CARRIER_DRIVER_APPROVED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Driver",
            entity_id=driver.id,
            summary="Conductor revisado por soporte",
            related_entity_ids={"carrierId": carrier_id},
            previous_state=previous_status,
            new_state=driver.validation_status,
            payload={"notes": self._normalized_text(notes)},
            source="backoffice",
        )
        return self._driver_summary(driver)

    def reject_driver(
        self,
        *,
        carrier_id: str,
        driver_id: str,
        operator_user_id: str,
        reason: str,
    ) -> DriverSummary:
        if not reason.strip():
            raise CarrierOnboardingError("reason is required")
        driver = self._require_carrier_driver(carrier_id, driver_id)
        previous_status = driver.validation_status
        driver.validation_status = "REJECTED"
        driver.reviewed_by_user_id = operator_user_id
        driver.reviewed_at = utc_now()
        driver.rejection_reason = reason.strip()
        driver.mark_updated()
        self._drivers.save(driver)
        self._event_log.record(
            event_type="CARRIER_DRIVER_REJECTED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Driver",
            entity_id=driver.id,
            summary="Conductor rechazado por soporte",
            related_entity_ids={"carrierId": carrier_id},
            previous_state=previous_status,
            new_state=driver.validation_status,
            payload={"reason": driver.rejection_reason},
            source="backoffice",
        )
        return self._driver_summary(driver)

    def assign_trip_crew(
        self,
        *,
        trip_id: str,
        driver_id: str,
        vehicle_id: str,
        operator_user_id: str,
    ) -> Trip:
        trip = self._trips.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        if trip.status != "PLANNED":
            raise CarrierOnboardingError("Crew can only be assigned to a planned trip")
        driver = self._require_carrier_driver(trip.carrier_id, driver_id)
        vehicle = self._require_carrier_vehicle(trip.carrier_id, vehicle_id)
        trip.driver_id = driver.id
        trip.vehicle_id = vehicle.id
        trip.mark_updated()
        self._trips.save(trip)
        self._event_log.record(
            event_type="TRIP_CREW_ASSIGNED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Trip",
            entity_id=trip.id,
            summary="Conductor y unidad asignados al viaje",
            related_entity_ids={
                "carrierId": trip.carrier_id,
                "driverId": driver.id,
                "vehicleId": vehicle.id,
            },
            payload={},
            source="backoffice",
        )
        return trip

    def ensure_trip_start_ready(self, trip_id: str) -> None:
        trip = self._trips.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        carrier = self._require_carrier(trip.carrier_id)
        if self._effective_validation_status(carrier) != "APPROVED":
            raise CarrierOnboardingError("Carrier must be approved before trip start")
        if not trip.driver_id or not trip.vehicle_id:
            raise CarrierOnboardingError("Assign a reviewed driver and vehicle before trip start")
        driver = self._require_carrier_driver(trip.carrier_id, trip.driver_id)
        vehicle = self._require_carrier_vehicle(trip.carrier_id, trip.vehicle_id)
        if driver.status != "ACTIVE" or driver.validation_status != "APPROVED":
            raise CarrierOnboardingError("Assigned driver is not approved for operation")
        if vehicle.status != "ACTIVE" or vehicle.validation_status != "APPROVED":
            raise CarrierOnboardingError("Assigned vehicle is not approved for operation")
        today = utc_now().date()
        for entity_type, entity_id in (("driver", driver.id), ("vehicle", vehicle.id)):
            invalid_now = next((
                document for document in self._documents.list()
                if document.entity_type.lower() == entity_type
                and document.entity_id == entity_id
                and document.status == "APPROVED"
                and (
                    (document.valid_from is not None and document.valid_from > today)
                    or (document.expires_at is not None and document.expires_at < today)
                )
            ), None)
            if invalid_now is not None:
                raise CarrierOnboardingError(
                    f"Assigned {entity_type} has a not-yet-valid or expired {invalid_now.document_type} document"
                )

    def delete_vehicle(
        self,
        *,
        carrier_id: str,
        vehicle_id: str,
        operator_user_id: str,
    ) -> VehicleSummary:
        vehicle = self._require_carrier_vehicle(carrier_id, vehicle_id)
        previous_status = vehicle.status
        vehicle.status = "INACTIVE"
        vehicle.mark_updated()
        self._vehicles.save(vehicle)
        self._vehicles.soft_delete(vehicle.id)
        self._event_log.record(
            event_type="CARRIER_VEHICLE_DISABLED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Vehicle",
            entity_id=vehicle.id,
            summary="Vehiculo de transportista desactivado",
            related_entity_ids={"carrierId": carrier_id},
            previous_state=previous_status,
            new_state="INACTIVE",
            payload=self._vehicle_payload(vehicle),
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier_id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return self._vehicle_summary(vehicle)

    def create_document(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        data: DocumentMutationInput,
    ) -> Document:
        entity_type = (data.entity_type or "carrier").strip().lower()
        entity_id = data.entity_id or carrier_id
        self._require_document_owner(carrier_id, entity_type, entity_id)
        if data.valid_from and data.expires_at and data.valid_from > data.expires_at:
            raise CarrierOnboardingError("Document validity start must not be after expiry")
        self._validate_superseded_document(
            data.supersedes_document_id, entity_type, entity_id, data.document_type.strip()
        )
        document = Document(
            entity_type=entity_type,
            entity_id=entity_id,
            document_type=data.document_type.strip(),
            external_uri=self._normalized_text(data.external_uri),
            storage_uri=self._normalized_text(data.storage_uri),
            provider="manual",
            mime_type=self._normalized_text(data.mime_type),
            file_name=self._normalized_text(data.file_name),
            notes=self._normalized_text(data.notes),
            status="PENDING",
            valid_from=data.valid_from,
            expires_at=data.expires_at,
            supersedes_document_id=data.supersedes_document_id,
        )
        self._documents.add(document)
        self._event_log.record(
            event_type="CARRIER_DOCUMENT_CREATED_MANUAL",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Document",
            entity_id=document.id,
            summary="Documento manual de transportista creado",
            related_entity_ids={"carrierId": carrier_id, f"{entity_type}Id": entity_id},
            new_state=document.status,
            payload=self._document_payload(document),
            source="backoffice",
        )
        if entity_type == "carrier":
            self.recalculate_onboarding(carrier_id, actor_type="OPERATOR", actor_id=operator_user_id, source="backoffice")
        return document

    def update_document(
        self,
        *,
        carrier_id: str,
        document_id: str,
        operator_user_id: str,
        data: DocumentMutationInput,
    ) -> Document:
        document = self._require_carrier_document(carrier_id, document_id)
        requested_type = (data.entity_type or "carrier").strip().lower()
        if requested_type != document.entity_type.lower() or (
            data.entity_id is not None and data.entity_id != document.entity_id
        ):
            raise CarrierOnboardingError("Document owner cannot be changed")
        before = self._document_payload(document)
        document.document_type = data.document_type.strip()
        if data.valid_from is not None or data.expires_at is not None:
            document.valid_from = data.valid_from
            document.expires_at = data.expires_at
        if data.supersedes_document_id is not None:
            if data.supersedes_document_id == document.id:
                raise CarrierOnboardingError("Document cannot supersede itself")
            self._validate_superseded_document(
                data.supersedes_document_id,
                document.entity_type,
                document.entity_id,
                data.document_type.strip(),
            )
            document.supersedes_document_id = data.supersedes_document_id
        if document.valid_from and document.expires_at and document.valid_from > document.expires_at:
            raise CarrierOnboardingError("Document validity start must not be after expiry")
        if data.external_uri is not None:
            document.external_uri = self._normalized_text(data.external_uri)
        if data.storage_uri is not None:
            document.storage_uri = self._normalized_text(data.storage_uri)
        document.mime_type = self._normalized_text(data.mime_type)
        document.file_name = self._normalized_text(data.file_name)
        document.notes = self._normalized_text(data.notes)
        document.mark_updated()
        self._documents.save(document)
        after = self._document_payload(document)
        changed_fields = self._changed_fields(before, after)
        self._event_log.record(
            event_type="CARRIER_DOCUMENT_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Document",
            entity_id=document.id,
            summary="Documento de transportista actualizado",
            related_entity_ids={"carrierId": carrier_id, f"{document.entity_type.lower()}Id": document.entity_id},
            previous_state=before["status"],
            new_state=after["status"],
            payload={
                "changed_fields": changed_fields,
                "previous_values": {key: before[key] for key in changed_fields},
                "new_values": {key: after[key] for key in changed_fields},
            },
            source="backoffice",
        )
        self.recalculate_onboarding(
            carrier_id,
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            source="backoffice",
        )
        return document

    def calculate_missing_fields(self, carrier: Carrier) -> list[str]:
        missing: list[str] = []
        if not (carrier.normalized_phone_number or carrier.contact_phone):
            missing.append("contact_phone")
        if not carrier.cuit:
            missing.append("cuit")
        if not self._carrier_vehicles(carrier.id):
            missing.append("vehicle")
        if not self._attached_carrier_documents(carrier.id):
            missing.append("document")
        return missing

    def recalculate_onboarding(
        self,
        carrier_id: str,
        *,
        actor_type: str,
        actor_id: str | None = None,
        source: str = "carrier_onboarding",
    ) -> CarrierOnboarding:
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        previous_missing_fields = list(onboarding.missing_fields)
        previous_status = onboarding.status
        self._refresh_onboarding(onboarding, carrier)
        onboarding = self._onboardings.save(onboarding)
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_RECALCULATED",
            actor_type=actor_type,
            actor_id=actor_id,
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Faltantes y estado de homologacion recalculados",
            related_entity_ids={"carrierId": carrier.id},
            previous_state=previous_status,
            new_state=onboarding.status,
            payload={
                "previous_missing_fields": previous_missing_fields,
                "missing_fields": list(onboarding.missing_fields),
                "required_fields": list(onboarding.required_fields),
            },
            source=source,
        )
        return onboarding

    def submit_for_review(self, carrier_id: str) -> CarrierOnboarding:
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        missing_fields = self.calculate_missing_fields(carrier)
        onboarding.missing_fields = missing_fields
        previous_status = onboarding.status
        if missing_fields:
            onboarding.status = "WAITING_DATA"
        else:
            onboarding.status = "PENDING_REVIEW"
            onboarding.submitted_at = onboarding.submitted_at or utc_now()
        onboarding.mark_updated()
        self._onboardings.save(onboarding)
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_SUBMITTED",
            actor_type="SYSTEM",
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Homologacion enviada a revision",
            related_entity_ids={"carrierId": carrier.id},
            previous_state=previous_status,
            new_state=onboarding.status,
            payload={"missing_fields": missing_fields},
            source="carrier_onboarding",
        )
        return onboarding

    def approve_carrier(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        notes: str | None = None,
    ) -> CarrierOnboardingDetail:
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        missing_fields = self.calculate_missing_fields(carrier)
        if missing_fields:
            onboarding.missing_fields = missing_fields
            onboarding.status = "WAITING_DATA"
            self._onboardings.save(onboarding)
            raise CarrierOnboardingError(
                f"Cannot approve carrier with missing fields: {', '.join(missing_fields)}"
            )

        now = utc_now()
        previous_carrier_status = self._effective_validation_status(carrier)
        previous_onboarding_status = onboarding.status
        carrier.is_validated = True
        carrier.validation_status = "APPROVED"
        carrier.validated_at = now
        carrier.rejected_at = None
        carrier.rejection_reason = None
        carrier.reviewed_by_user_id = operator_user_id
        carrier.mark_updated()
        self._carriers.save(carrier)

        onboarding.status = "APPROVED"
        onboarding.missing_fields = []
        onboarding.reviewed_by_user_id = operator_user_id
        onboarding.reviewed_at = now
        onboarding.rejection_reason = None
        onboarding.mark_updated()
        self._onboardings.save(onboarding)

        self._event_log.record(
            event_type="CARRIER_APPROVED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Transportista homologado",
            related_entity_ids={"carrierOnboardingId": onboarding.id},
            previous_state=previous_carrier_status,
            new_state=carrier.validation_status,
            payload={"notes": notes},
            source="backoffice",
        )
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_STATUS_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Estado de homologacion actualizado",
            related_entity_ids={"carrierId": carrier.id},
            previous_state=previous_onboarding_status,
            new_state=onboarding.status,
            payload={"notes": notes},
            source="backoffice",
        )
        return self.detail(carrier.id)

    def reject_carrier(
        self,
        *,
        carrier_id: str,
        operator_user_id: str,
        reason: str,
    ) -> CarrierOnboardingDetail:
        if not reason.strip():
            raise CarrierOnboardingError("reason is required")
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        now = utc_now()
        previous_carrier_status = self._effective_validation_status(carrier)
        previous_onboarding_status = onboarding.status

        carrier.is_validated = False
        carrier.validation_status = "REJECTED"
        carrier.rejected_at = now
        carrier.rejection_reason = reason
        carrier.reviewed_by_user_id = operator_user_id
        carrier.mark_updated()
        self._carriers.save(carrier)

        onboarding.status = "REJECTED"
        onboarding.reviewed_by_user_id = operator_user_id
        onboarding.reviewed_at = now
        onboarding.rejection_reason = reason
        onboarding.missing_fields = self.calculate_missing_fields(carrier)
        onboarding.mark_updated()
        self._onboardings.save(onboarding)

        self._event_log.record(
            event_type="CARRIER_REJECTED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Homologacion de transportista rechazada",
            related_entity_ids={"carrierOnboardingId": onboarding.id},
            previous_state=previous_carrier_status,
            new_state=carrier.validation_status,
            payload={"reason": reason},
            source="backoffice",
        )
        self._event_log.record(
            event_type="CARRIER_ONBOARDING_STATUS_UPDATED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="CarrierOnboarding",
            entity_id=onboarding.id,
            summary="Estado de homologacion actualizado",
            related_entity_ids={"carrierId": carrier.id},
            previous_state=previous_onboarding_status,
            new_state=onboarding.status,
            payload={"reason": reason},
            source="backoffice",
        )
        return self.detail(carrier.id)

    def approve_document(
        self,
        *,
        carrier_id: str,
        document_id: str,
        operator_user_id: str,
        notes: str | None = None,
    ) -> Document:
        document = self._require_carrier_document(carrier_id, document_id)
        previous_status = document.status
        document.status = "APPROVED"
        document.reviewed_by_user_id = operator_user_id
        document.reviewed_at = utc_now()
        document.rejection_reason = None
        if notes is not None:
            document.notes = notes
        document.mark_updated()
        self._documents.save(document)
        self._event_log.record(
            event_type="CARRIER_DOCUMENT_APPROVED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Document",
            entity_id=document.id,
            summary="Documento de transportista aprobado",
            related_entity_ids={"carrierId": carrier_id, f"{document.entity_type.lower()}Id": document.entity_id},
            previous_state=previous_status,
            new_state=document.status,
            payload={"notes": notes},
            source="backoffice",
        )
        if document.entity_type.lower() == "carrier":
            self.submit_for_review(carrier_id)
        return document

    def reject_document(
        self,
        *,
        carrier_id: str,
        document_id: str,
        operator_user_id: str,
        reason: str,
    ) -> Document:
        if not reason.strip():
            raise CarrierOnboardingError("reason is required")
        document = self._require_carrier_document(carrier_id, document_id)
        previous_status = document.status
        document.status = "REJECTED"
        document.reviewed_by_user_id = operator_user_id
        document.reviewed_at = utc_now()
        document.rejection_reason = reason
        document.mark_updated()
        self._documents.save(document)
        self._event_log.record(
            event_type="CARRIER_DOCUMENT_REJECTED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Document",
            entity_id=document.id,
            summary="Documento de transportista rechazado",
            related_entity_ids={"carrierId": carrier_id},
            previous_state=previous_status,
            new_state=document.status,
            payload={"reason": reason},
            source="backoffice",
        )
        if document.entity_type.lower() == "carrier":
            self.submit_for_review(carrier_id)
        return document

    def list_pending(self) -> list[CarrierOnboardingPendingSummary]:
        rows: list[CarrierOnboardingPendingSummary] = []
        for carrier in self._carriers.list():
            effective_status = self._effective_validation_status(carrier)
            onboarding = self._find_onboarding(carrier.id)
            if effective_status == "APPROVED" and (
                onboarding is None or onboarding.status == "APPROVED"
            ):
                continue
            onboarding = self.get_or_create_onboarding(carrier.id)
            documents = self._carrier_documents(carrier.id)
            rows.append(
                CarrierOnboardingPendingSummary(
                    carrier_id=carrier.id,
                    onboarding_id=onboarding.id,
                    name=carrier.name,
                    contact_phone=carrier.contact_phone,
                    phone=carrier.normalized_phone_number or carrier.contact_phone,
                    email=carrier.email,
                    company_name=carrier.company_name,
                    cuit=carrier.cuit,
                    validation_status=effective_status,
                    onboarding_status=onboarding.status,
                    missing_fields=list(onboarding.missing_fields),
                    documents_count=len(documents),
                    pending_documents_count=sum(
                        1 for document in documents if document.status == "PENDING"
                    ),
                    created_at=carrier.created_at,
                    submitted_at=onboarding.submitted_at,
                )
            )
        rows.sort(key=lambda item: item.created_at, reverse=True)
        return rows

    def detail(self, carrier_id: str) -> CarrierOnboardingDetail:
        carrier = self._require_carrier(carrier_id)
        onboarding = self.get_or_create_onboarding(carrier_id)
        events = tuple(
            event
            for event in self._event_log.events
            if event.entity_id in {carrier.id, onboarding.id}
            or event.related_entity_ids.get("carrierId") == carrier.id
            or event.related_entity_ids.get("carrierOnboardingId") == onboarding.id
        )
        vehicles = self._carrier_vehicles(carrier.id)
        drivers = [driver for driver in self._drivers.list() if driver.carrier_id == carrier.id]
        return CarrierOnboardingDetail(
            carrier=carrier,
            onboarding=onboarding,
            vehicles=tuple(
                VehicleSummary(
                    id=vehicle.id,
                    vehicle_type=vehicle.vehicle_type,
                    capacity_estimate=vehicle.capacity_estimate,
                    plate_number=vehicle.plate,
                    body_type=self._vehicle_body_type(vehicle),
                    status=vehicle.status,
                    validation_status=vehicle.validation_status,
                    updated_at=vehicle.updated_at,
                    documents=tuple(self._document_summary(item) for item in self._entity_documents("vehicle", vehicle.id)),
                )
                for vehicle in vehicles
            ),
            drivers=tuple(
                self._driver_summary(driver, include_documents=True)
                for driver in sorted(drivers, key=lambda item: item.created_at, reverse=True)
            ),
            documents=tuple(
                self._document_summary(document)
                for document in self._carrier_documents(carrier.id)
            ),
            capture_progress=CarrierCaptureProgress(
                step=onboarding.capture_context.get("step"),
                captured_vehicle_count=int(onboarding.capture_context.get("captured_vehicle_count", "0")),
                declared_vehicle_count=int(onboarding.capture_context.get("declared_vehicle_count", "0")),
            ),
            events=events,
        )

    def resolve_carrier_document_file(
        self,
        *,
        carrier_id: str,
        document_id: str,
        storage_root: str | Path,
        operator_user_id: str,
    ) -> tuple[Path, Document]:
        """Resolve a private local carrier document without trusting stored paths."""
        document = self._require_carrier_document(carrier_id, document_id)
        if not document.storage_uri:
            raise FileNotFoundError(document_id)

        root = Path(storage_root).resolve()
        stored_path = Path(document.storage_uri)
        candidates = [stored_path] if stored_path.is_absolute() else [stored_path, root / stored_path]
        resolved = None
        for candidate in candidates:
            try:
                possible = candidate.resolve(strict=True)
                possible.relative_to(root)
            except (OSError, ValueError):
                continue
            resolved = possible
            break
        if resolved is None:
            raise FileNotFoundError(document_id)
        if not resolved.is_file():
            raise FileNotFoundError(document_id)

        self._event_log.record(
            event_type="CARRIER_DOCUMENT_ACCESSED",
            actor_type="OPERATOR",
            actor_id=operator_user_id,
            entity_type="Document",
            entity_id=document.id,
            summary="Documento privado consultado por un operador",
            related_entity_ids={"carrierId": carrier_id, f"{document.entity_type.lower()}Id": document.entity_id},
            payload={"document_type": document.document_type},
            source="backoffice",
        )
        return resolved, document

    def _refresh_onboarding(self, onboarding: CarrierOnboarding, carrier: Carrier) -> None:
        onboarding.required_fields = list(self.REQUIRED_FIELDS)
        onboarding.missing_fields = self.calculate_missing_fields(carrier)
        if self._effective_validation_status(carrier) == "APPROVED":
            onboarding.status = "APPROVED"
        elif onboarding.status not in {"REJECTED", "PENDING_REVIEW"}:
            onboarding.status = self._status_for_missing_fields(onboarding.missing_fields)
        onboarding.mark_updated()

    def _initial_onboarding_status(self, carrier: Carrier) -> str:
        if self._effective_validation_status(carrier) == "APPROVED":
            return "APPROVED"
        return self._status_for_missing_fields(self.calculate_missing_fields(carrier))

    def _status_for_missing_fields(self, missing_fields: list[str]) -> str:
        if not missing_fields:
            return "PENDING_REVIEW"
        if missing_fields == ["document"]:
            return "WAITING_DOCUMENTS"
        return "WAITING_DATA"

    def _effective_validation_status(self, carrier: Carrier) -> str:
        if carrier.is_validated:
            return "APPROVED"
        return carrier.validation_status or "DRAFT"

    def _find_onboarding(self, carrier_id: str) -> CarrierOnboarding | None:
        onboardings = [
            onboarding
            for onboarding in self._onboardings.list()
            if onboarding.carrier_id == carrier_id
        ]
        if not onboardings:
            return None
        onboardings.sort(key=lambda item: item.created_at, reverse=True)
        return onboardings[0]

    def _require_carrier(self, carrier_id: str) -> Carrier:
        carrier = self._carriers.get(carrier_id)
        if carrier is None:
            raise KeyError(carrier_id)
        return carrier

    def _require_carrier_document(self, carrier_id: str, document_id: str) -> Document:
        self._require_carrier(carrier_id)
        document = self._documents.get(document_id)
        if document is None:
            raise KeyError(document_id)
        if not self._document_belongs_to_carrier(document, carrier_id):
            raise CarrierOnboardingError("Document does not belong to carrier")
        return document

    def _validate_superseded_document(
        self,
        supersedes_document_id: str | None,
        entity_type: str,
        entity_id: str,
        document_type: str,
    ) -> None:
        if supersedes_document_id is None:
            return
        previous = self._documents.get(supersedes_document_id)
        if previous is None:
            raise CarrierOnboardingError("Renewed document reference does not exist")
        if previous.entity_type.lower() != entity_type.lower() or previous.entity_id != entity_id:
            raise CarrierOnboardingError("Renewed document must belong to the same entity")
        if previous.document_type.strip().casefold() != document_type.strip().casefold():
            raise CarrierOnboardingError("Renewed document must have the same document type")

    def _require_document_owner(self, carrier_id: str, entity_type: str, entity_id: str) -> None:
        self._require_carrier(carrier_id)
        if entity_type == "carrier":
            if entity_id != carrier_id:
                raise CarrierOnboardingError("Document does not belong to carrier")
            return
        if entity_type == "driver":
            self._require_carrier_driver(carrier_id, entity_id)
            return
        if entity_type == "vehicle":
            self._require_carrier_vehicle(carrier_id, entity_id)
            return
        raise CarrierOnboardingError("Document owner must be carrier, driver, or vehicle")

    def _document_belongs_to_carrier(self, document: Document, carrier_id: str) -> bool:
        entity_type = document.entity_type.lower()
        if entity_type == "carrier":
            return document.entity_id == carrier_id
        try:
            self._require_document_owner(carrier_id, entity_type, document.entity_id)
        except (KeyError, CarrierOnboardingError):
            return False
        return True

    def _entity_documents(self, entity_type: str, entity_id: str) -> list[Document]:
        return [
            item for item in self._documents.list()
            if item.entity_type.lower() == entity_type and item.entity_id == entity_id
        ]

    @staticmethod
    def _document_summary(document: Document) -> DocumentSummary:
        return DocumentSummary(
            id=document.id,
            entity_type=document.entity_type.lower(),
            entity_id=document.entity_id,
            document_type=document.document_type,
            has_file=bool(document.storage_uri),
            provider=document.provider,
            provider_media_id=document.provider_media_id,
            mime_type=document.mime_type,
            file_name=document.file_name,
            uploaded_by_phone=document.uploaded_by_phone,
            status=document.status,
            notes=document.notes,
            reviewed_by_user_id=document.reviewed_by_user_id,
            reviewed_at=document.reviewed_at,
            rejection_reason=document.rejection_reason,
            valid_from=document.valid_from,
            expires_at=document.expires_at,
            supersedes_document_id=document.supersedes_document_id,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    def _require_carrier_vehicle(self, carrier_id: str, vehicle_id: str) -> Vehicle:
        self._require_carrier(carrier_id)
        vehicle = self._vehicles.get(vehicle_id)
        if vehicle is None:
            raise KeyError(vehicle_id)
        if vehicle.carrier_id != carrier_id:
            raise CarrierOnboardingError("Vehicle does not belong to carrier")
        return vehicle

    def _require_carrier_driver(self, carrier_id: str, driver_id: str) -> Driver:
        self._require_carrier(carrier_id)
        driver = self._drivers.get(driver_id)
        if driver is None:
            raise KeyError(driver_id)
        if driver.carrier_id != carrier_id:
            raise CarrierOnboardingError("Driver does not belong to carrier")
        return driver

    def _carrier_vehicles(self, carrier_id: str) -> list[Vehicle]:
        return [
            vehicle
            for vehicle in self._vehicles.list()
            if vehicle.carrier_id == carrier_id and vehicle.status != "INACTIVE"
        ]

    def _carrier_documents(self, carrier_id: str) -> list[Document]:
        return [
            document
            for document in self._documents.list()
            if document.entity_type.lower() == "carrier" and document.entity_id == carrier_id
        ]

    def _attached_carrier_documents(self, carrier_id: str) -> list[Document]:
        return [
            document
            for document in self._carrier_documents(carrier_id)
            if document.external_uri or document.storage_uri
        ]

    def _onboarding_snapshot(self, carrier: Carrier) -> CarrierOnboarding:
        onboarding = self._find_onboarding(carrier.id)
        if onboarding is not None:
            copy = CarrierOnboarding(**onboarding.__dict__)
            self._refresh_onboarding(copy, carrier)
            return copy
        return CarrierOnboarding(
            carrier_id=carrier.id,
            status=self._initial_onboarding_status(carrier),
            required_fields=list(self.REQUIRED_FIELDS),
            missing_fields=self.calculate_missing_fields(carrier),
        )

    def _matches_carrier_search(
        self,
        carrier: Carrier,
        vehicles: list[Vehicle],
        search: str,
    ) -> bool:
        haystack = [
            carrier.id,
            carrier.name,
            carrier.contact_phone,
            carrier.normalized_phone_number,
            carrier.email,
            carrier.company_name,
            carrier.cuit,
            carrier.truck_body_type,
            *carrier.truck_types,
            *(vehicle.plate for vehicle in vehicles if vehicle.plate),
        ]
        return any(search in (value or "").lower() for value in haystack)

    def _vehicle_summary(self, vehicle: Vehicle) -> VehicleSummary:
        return VehicleSummary(
            id=vehicle.id,
            vehicle_type=vehicle.vehicle_type,
            capacity_estimate=vehicle.capacity_estimate,
            plate_number=vehicle.plate,
            body_type=self._vehicle_body_type(vehicle),
            status=vehicle.status,
            validation_status=vehicle.validation_status,
            updated_at=vehicle.updated_at,
            documents=tuple(self._document_summary(item) for item in self._entity_documents("vehicle", vehicle.id)),
        )

    def _driver_summary(self, driver: Driver, *, include_documents: bool = False) -> DriverSummary:
        return DriverSummary(
            id=driver.id,
            name=driver.name,
            phone=driver.phone,
            license_category=driver.license_category,
            status=driver.status,
            validation_status=driver.validation_status,
            reviewed_by_user_id=driver.reviewed_by_user_id,
            reviewed_at=driver.reviewed_at,
            rejection_reason=driver.rejection_reason,
            updated_at=driver.updated_at,
            documents=tuple(self._document_summary(item) for item in self._entity_documents("driver", driver.id))
            if include_documents else (),
        )

    def _carrier_payload(self, carrier: Carrier) -> dict[str, Any]:
        return self._json_safe(
            {
            "name": carrier.name,
            "phone": carrier.normalized_phone_number or carrier.contact_phone,
            "email": carrier.email,
            "company_name": carrier.company_name,
            "cuit": carrier.cuit,
            "truck_count": carrier.truck_count,
            "truck_types": list(carrier.truck_types),
            "truck_body_type": carrier.truck_body_type,
            "validation_status": self._effective_validation_status(carrier),
            "is_validated": carrier.is_validated,
            }
        )

    def _vehicle_payload(self, vehicle: Vehicle) -> dict[str, Any]:
        return self._json_safe(
            {
            "plate_number": vehicle.plate,
            "vehicle_type": vehicle.vehicle_type,
            "body_type": self._vehicle_body_type(vehicle),
            "capacity": vehicle.capacity_estimate,
            "status": vehicle.status,
            }
        )

    def _document_payload(self, document: Document) -> dict[str, Any]:
        return self._json_safe(
            {
            "document_type": document.document_type,
            "has_external_link": bool(document.external_uri),
            "has_file": bool(document.storage_uri),
            "file_name": document.file_name,
            "mime_type": document.mime_type,
            "notes": document.notes,
            "status": document.status,
            "provider": document.provider,
            "valid_from": document.valid_from,
            "expires_at": document.expires_at,
            "supersedes_document_id": document.supersedes_document_id,
            }
        )

    def _changed_fields(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> list[str]:
        return [key for key, value in after.items() if before.get(key) != value]

    def _normalized_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _normalized_list(self, values: list[str] | None) -> list[str]:
        if not values:
            return []
        normalized: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned:
                normalized.append(cleaned)
        return normalized

    def _normalized_equipment_list(self, values: list[str] | None) -> list[str]:
        if not values:
            return []
        normalized: list[str] = []
        for value in values:
            item = normalize_equipment_or_declared(value)
            if item and item not in normalized:
                normalized.append(item)
        return normalized

    def _vehicle_flags(self, *, body_type: str | None) -> dict[str, Any]:
        flags: dict[str, Any] = {}
        normalized_body_type = normalize_equipment_or_declared(body_type)
        if normalized_body_type:
            flags["body_type"] = normalized_body_type
        return flags

    def _vehicle_body_type(self, vehicle: Vehicle) -> str | None:
        value = vehicle.validation_flags.get("body_type")
        if value is None:
            return None
        return str(value)

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        return value
