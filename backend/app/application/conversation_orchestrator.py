from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging
import re
from typing import Callable, Protocol
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.application.ai import AIExtractionClient, AIExtractionError, LoadDataExtraction
from app.application.admin_ops import AdminOpsError, AdminOpsService
from app.application.carrier_onboarding import CarrierOnboardingService
from app.application.chat_shipment_parser import ParsedChatShipment, normalize_for_simple_parse, parse_chat_shipment_text
from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.application.media import MediaService
from app.application.notifications import NotificationService
from app.application.transcription import TranscriptionService
from app.domain.events import EventLog, EventLogService, current_test_run_id
from app.domain.cargo import (
    CargoCategoryDefinition,
    CargoTypeDefinition,
    extract_explicit_quantity_unit,
    normalize_cargo_category,
    normalize_cargo_type,
    normalize_quantity_unit,
    quantity_unit_label,
)
from app.domain.location_catalog import GeographicCatalogEntry, resolve_argentine_locality, resolve_catalog_locality
from app.domain.route_availability import RouteAvailability
from app.domain.models import Carrier, ConversationSession, Location, MediaAsset, Message, ShipmentRequest, TripOffer
from app.domain.state_machine import StateTransitionService
from app.infrastructure.repositories.memory import InMemoryRepository
from app.infrastructure.adapters.whatsapp import InboundActionSelection, InboundMedia, OutboundAction


logger = logging.getLogger(__name__)

SHIPMENT_ID_PATTERN = re.compile(r"\b(sr_[a-z0-9]+)\b", re.IGNORECASE)


class CarrierRepository(Protocol):
    def get(self, entity_id: str) -> Carrier | None:
        pass

    def list(self, *, include_deleted: bool = False) -> list[Carrier]:
        pass

    def save(self, entity: Carrier) -> Carrier:
        pass


class ShipmentRequestRepository(Protocol):
    def add(self, entity: ShipmentRequest) -> ShipmentRequest:
        pass

    def get(self, entity_id: str) -> ShipmentRequest | None:
        pass

    def list(self, *, include_deleted: bool = False) -> list[ShipmentRequest]:
        pass

    def save(self, entity: ShipmentRequest) -> ShipmentRequest:
        pass


class TripOfferRepository(Protocol):
    def add(self, entity: TripOffer) -> TripOffer:
        pass

    def list(self, *, include_deleted: bool = False) -> list[TripOffer]:
        pass


class RouteAvailabilityRepository(Protocol):
    def add(self, entity: RouteAvailability) -> RouteAvailability:
        pass

    def list(self, *, include_deleted: bool = False) -> list[RouteAvailability]:
        pass


@dataclass(frozen=True)
class InboundConversationMessage:
    provider: str
    idempotency_key: str
    correlation_id: str
    conversation_id: str | None = None
    workflow_execution_id: str | None = None
    provider_contact_id: str | None = None
    provider_message_id: str | None = None
    phone_number: str | None = None
    occurred_at: datetime | None = None
    location: dict | None = None
    reply_to_message_id: str | None = None
    text: str | None = None
    media: InboundMedia | None = None
    action_selection: InboundActionSelection | None = None


@dataclass(frozen=True)
class ConversationResult:
    conversation_session: ConversationSession
    message: Message
    shipment_request: ShipmentRequest | None
    response_text: str | None
    handoff_required: bool
    trip_offer: TripOffer | None = None
    events: tuple[EventLog, ...] = field(default_factory=tuple)
    actions: tuple[OutboundAction, ...] = field(default_factory=tuple)


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        ai_client: AIExtractionClient,
        conversation_sessions: InMemoryRepository[ConversationSession],
        messages: InMemoryRepository[Message],
        shipment_requests: ShipmentRequestRepository,
        locations: InMemoryRepository[Location],
        event_log: EventLogService,
        route_availabilities: RouteAvailabilityRepository | None = None,
        carriers: CarrierRepository | None = None,
        trip_offers: TripOfferRepository | None = None,
        notification_service: NotificationService | None = None,
        media_service: MediaService | None = None,
        transcription_service: TranscriptionService | None = None,
        admin_ops_service: AdminOpsService | None = None,
        carrier_onboarding_service: CarrierOnboardingService | None = None,
        enable_test_role_switching: bool = False,
        test_run_close_hook: Callable[[str], None] | None = None,
        cargo_categories: list[CargoCategoryDefinition] | None = None,
        cargo_types: list[CargoTypeDefinition] | None = None,
        geography_catalog: list[GeographicCatalogEntry] | None = None,
    ) -> None:
        self._ai_client = ai_client
        self._conversation_sessions = conversation_sessions
        self._messages = messages
        self._shipment_requests = shipment_requests
        self._locations = locations
        self._event_log = event_log
        self._route_availabilities = route_availabilities
        self._carriers = carriers
        self._trip_offers = trip_offers
        self._notification_service = notification_service
        self._media_service = media_service
        self._transcription_service = transcription_service
        self._routing = getattr(admin_ops_service, "_routing", None)
        self._admin_ops_service = admin_ops_service
        self._carrier_onboarding_service = carrier_onboarding_service
        self._enable_test_role_switching = enable_test_role_switching
        self._test_run_close_hook = test_run_close_hook or (lambda _test_run_id: None)
        self._cargo_categories = cargo_categories
        self._cargo_types = cargo_types
        self._geography_catalog = geography_catalog
        self._transitions = StateTransitionService(event_log)

    def handle_inbound_message(self, inbound: InboundConversationMessage) -> ConversationResult:
        session = self._get_or_create_session(inbound)
        active_test_run_id = session.active_test_run_id if self._enable_test_role_switching else None
        token = current_test_run_id.set(active_test_run_id)
        try:
            return self._process_inbound_message(inbound, session)
        finally:
            current_test_run_id.reset(token)

    def _process_inbound_message(
        self,
        inbound: InboundConversationMessage,
        session: ConversationSession,
    ) -> ConversationResult:
        existing_message = self._find_message_by_idempotency_key(inbound.idempotency_key)
        if existing_message is not None:
            return ConversationResult(
                conversation_session=session,
                message=existing_message,
                shipment_request=None,
                response_text=None,
                handoff_required=False,
                events=(),
            )

        text = (inbound.text or "").strip()
        test_run_command = self._detect_test_run_command(text)
        if test_run_command is not None and self._enable_test_role_switching:
            return self._handle_test_run_command(
                command=test_run_command,
                inbound=inbound,
                session=session,
            )

        role_command = self._detect_role_override_command(text)
        if role_command is not None and self._enable_test_role_switching:
            if session.active_test_run_id is None:
                message = self._record_message(session, inbound, sender_type="User")
                events = [self._record_message_received(message, inbound)]
                events.append(
                    self._event_log.record(
                        event_type="TEST_ROLE_SWITCH_REJECTED",
                        actor_type="User",
                        entity_type="ConversationSession",
                        entity_id=session.id,
                        summary="Cambio de rol QA rechazado fuera de un escenario activo",
                        related_entity_ids={"messageId": message.id, "conversationSessionId": session.id},
                        source=inbound.provider,
                        correlation_id=inbound.correlation_id,
                        idempotency_key=f"{inbound.idempotency_key}:test_role_switch_rejected",
                    )
                )
                return ConversationResult(
                    conversation_session=session,
                    message=message,
                    shipment_request=None,
                    response_text="Para cambiar de rol, primero iniciá un escenario con /test iniciar.",
                    handoff_required=False,
                    events=tuple(events),
                )
            sender_type = (
                role_command
                if role_command in {"Producer", "Carrier", "Operator"}
                else session.role_override or "User"
            )
            message = self._record_message(session, inbound, sender_type=sender_type)
            events = [self._record_message_received(message, inbound)]
            if role_command == "STATUS":
                carrier = self._resolve_carrier(inbound)
                events.append(
                    self._record_session_role_status_requested(
                        session=session,
                        message=message,
                        inbound=inbound,
                        carrier=carrier,
                    )
                )
                return ConversationResult(
                    conversation_session=session,
                    message=message,
                    shipment_request=None,
                    response_text=self._build_session_status_response(
                        session=session,
                        inbound=inbound,
                        carrier=carrier,
                    ),
                    handoff_required=False,
                    events=tuple(events),
                )
            events.append(
                self._apply_role_override_command(
                    session=session,
                    message=message,
                    inbound=inbound,
                    command=role_command,
                )
            )
            response_text = (
                "Modo automático activado."
                if role_command == "CLEAR"
                else f"Modo de prueba activo: {self._role_label(role_command)}."
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text=response_text,
                handoff_required=False,
                events=tuple(events),
            )

        role_override = session.role_override if self._enable_test_role_switching else None
        if (
            self._carrier_onboarding_service is not None
            and role_override not in {"Producer", "Operator"}
            and self._is_carrier_onboarding_intent(text)
        ):
            raw_phone = inbound.phone_number or session.participant_phone
            normalized_phone = self._safe_normalize_phone_number(raw_phone)
            if not raw_phone or not normalized_phone:
                message = self._record_message(session, inbound, sender_type="User")
                events = [self._record_message_received(message, inbound)]
                return self._conversation_result(
                    session, message, events,
                    "Para iniciar el alta necesito que escribas desde un número de WhatsApp válido.",
                )
            carrier, onboarding, _ = self._carrier_onboarding_service.start_whatsapp_capture(
                phone=raw_phone, normalized_phone=normalized_phone,
            )
            message = self._record_message(session, inbound, sender_type="Carrier")
            events = [self._record_message_received(message, inbound)]
            prompt = self._carrier_onboarding_service.whatsapp_capture_prompt(carrier.id)
            if prompt is None:
                prompt = (
                    self._onboarding_prompt(onboarding.capture_context.get("step", "carrier_name"))
                    if onboarding.capture_context.get("step")
                    else "Tu perfil ya está activo. Si necesitás actualizar datos, escribí a soporte."
                )
            return self._conversation_result(session, message, events, prompt)

        carrier = None if role_override in {"Producer", "Operator"} else self._resolve_carrier(inbound)
        has_active_carrier_capture = bool(
            carrier is not None
            and self._carrier_onboarding_service is not None
            and self._carrier_onboarding_service.capture_context(carrier.id).get("step")
            not in {None, "complete"}
        )
        if carrier is not None and not has_active_carrier_capture and role_override is None and self._should_route_known_contact_as_producer(
            inbound=inbound,
            session=session,
            carrier=carrier,
            text=text,
        ):
            carrier = None
        sender_type = role_override or ("Carrier" if carrier else "Producer")
        message = self._record_message(session, inbound, sender_type=sender_type)
        events = [self._record_message_received(message, inbound)]
        action_selection = self._resolve_inbound_action_selection(
            inbound=inbound,
            session=session,
            message=message,
            carrier=carrier,
            text=text,
        )
        if action_selection is not None:
            events.append(
                self._record_interactive_action_selected(
                    message=message,
                    inbound=inbound,
                    session=session,
                    carrier=carrier,
                    action_selection=action_selection,
                )
            )

        # WhatsApp button replies contain the button id, while text fallback
        # replies contain the visible label or a number. Route both through
        # the same domain command after resolving the sent action metadata.
        if action_selection is not None:
            text = (
                action_selection.label or action_selection.value
                if sender_type == "Carrier"
                else action_selection.value
            )

        if self._routing is not None:
            try:
                if carrier is None and role_override is None and self._is_greeting_or_menu(text):
                    driver_menu = self._routing.driver_menu(inbound.phone_number, session.active_test_run_id)
                    if driver_menu:
                        response, actions = driver_menu
                        return self._conversation_result(session, message, events, response, actions=actions)
                if inbound.location is not None:
                    response, actions = self._routing.receive_location(inbound, session.active_test_run_id)
                    return self._conversation_result(session, message, events, response, actions=actions)
                route_command = action_selection.value if action_selection else text
                if inbound.action_selection is not None and action_selection is None:
                    route_command = self._routing.action_command(inbound.action_selection.id, inbound.phone_number, session.active_test_run_id) or route_command
                response = self._routing.handle_text(route_command, inbound.phone_number, session.active_test_run_id)
                if response:
                    return self._conversation_result(session, message, events, response)
            except (ValueError, TypeError, KeyError) as exc:
                return self._conversation_result(session, message, events, f"⚠️ {exc}")

        if inbound.media is not None:
            return self._handle_inbound_media(
                inbound=inbound,
                session=session,
                message=message,
                events=events,
                carrier=carrier,
                role_override=role_override,
            )
        return self._handle_recorded_text_message(
            inbound=inbound,
            session=session,
            message=message,
            text=text,
            events=events,
            carrier=carrier,
            role_override=role_override,
        )

    def _handle_inbound_media(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        events: list[EventLog],
        carrier: Carrier | None,
        role_override: str | None,
    ) -> ConversationResult:
        if self._media_service is None:
            events.append(
                self._record_human_review_requested(
                    message,
                    inbound,
                    "Media recibida sin servicio de procesamiento configurado",
                )
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="Recibí el archivo, pero no pude procesarlo bien. Por favor reenviámelo o escribí qué documento es.",
                handoff_required=True,
                events=tuple(events),
            )

        assert inbound.media is not None
        document_owner_type = None
        document_owner_id = None
        if (
            carrier is not None
            and self._carrier_onboarding_service is not None
            and role_override not in {"Producer", "Operator"}
        ):
            capture_context = self._carrier_onboarding_service.capture_context(carrier.id)
            if capture_context.get("step") == "driver_license_upload":
                document_owner_type = "driver"
                document_owner_id = capture_context.get("driver_id")
        result = self._media_service.process_inbound_media(
            provider=inbound.provider,
            media=inbound.media,
            message=message,
            phone_number=inbound.phone_number or session.participant_phone,
            carrier_id=carrier.id if carrier is not None else None,
            document_owner_type=document_owner_type,
            document_owner_id=document_owner_id,
            caption=inbound.text or inbound.media.caption,
            correlation_id=inbound.correlation_id,
            idempotency_key=inbound.idempotency_key,
        )
        events.extend(result.events)
        if inbound.media.media_type == "audio":
            return self._handle_inbound_audio(
                inbound=inbound,
                session=session,
                message=message,
                media_asset=result.media_asset,
                events=events,
                carrier=carrier,
                role_override=role_override,
            )
        if result.document is not None:
            completion_response = None
            if (
                document_owner_type == "driver"
                and document_owner_id
                and carrier is not None
                and self._carrier_onboarding_service is not None
            ):
                completion_response = self._carrier_onboarding_service.complete_whatsapp_document_capture(
                    carrier_id=carrier.id,
                    driver_id=document_owner_id,
                )
            response_text = completion_response or "Recibí el documento. Lo dejamos pendiente de revisión por soporte."
            handoff_required = False
        else:
            response_text = (
                "Recibí el archivo. Un operador lo revisa porque no pude asociarlo a un transportista."
            )
            handoff_required = True
        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=None,
            response_text=response_text,
            handoff_required=handoff_required,
            events=tuple(events),
        )

    def _handle_inbound_audio(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        media_asset: MediaAsset,
        events: list[EventLog],
        carrier: Carrier | None,
        role_override: str | None,
    ) -> ConversationResult:
        if self._transcription_service is None:
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="Recibí tu audio. Por ahora necesito que me escribas el mensaje para poder procesarlo.",
                handoff_required=False,
                events=tuple(events),
            )

        transcription = self._transcription_service.transcribe_media_asset(
            media_asset=media_asset,
            correlation_id=inbound.correlation_id,
            idempotency_key=inbound.idempotency_key,
            related_entity_ids={
                "messageId": message.id,
                "conversationSessionId": session.id,
            },
        )
        events.extend(transcription.events)
        if transcription.status == "SUCCEEDED" and transcription.text:
            message.normalized_content = transcription.text
            self._messages.save(message)
            return self._handle_recorded_text_message(
                inbound=inbound,
                session=session,
                message=message,
                text=transcription.text,
                events=events,
                carrier=carrier,
                role_override=role_override,
            )
        if transcription.status == "SKIPPED":
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="Recibí tu audio. Por ahora necesito que me escribas el mensaje para poder procesarlo.",
                handoff_required=False,
                events=tuple(events),
            )
        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=None,
            response_text="Recibí tu audio, pero no pude transcribirlo bien. ¿Me lo reenviás o me escribís el mensaje?",
            handoff_required=False,
            events=tuple(events),
        )

    def _handle_recorded_text_message(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        text: str,
        events: list[EventLog],
        carrier: Carrier | None,
        role_override: str | None,
    ) -> ConversationResult:
        if not text:
            events.append(self._record_human_review_requested(message, inbound, "Mensaje sin texto"))
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="No pude leer el mensaje. Un operador lo revisa.",
                handoff_required=True,
                events=tuple(events),
            )

        if role_override == "Operator":
            events.append(
                self._record_operator_command_routed_to_kapso(
                    message=message,
                    inbound=inbound,
                    session=session,
                    carrier=carrier,
                    text=text,
                )
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text=None,
                handoff_required=False,
                events=tuple(events),
            )

        has_active_carrier_capture = bool(
            carrier is not None
            and self._carrier_onboarding_service is not None
            and self._carrier_onboarding_service.capture_context(carrier.id).get("step")
            not in {None, "complete"}
        )

        if carrier is not None:
            if self._is_greeting_or_menu(text):
                if has_active_carrier_capture and self._carrier_onboarding_service is not None:
                    capture_step = self._carrier_onboarding_service.capture_context(carrier.id).get("step")
                    prompt = self._carrier_onboarding_service.whatsapp_capture_prompt(carrier.id)
                    return self._conversation_result(
                        session, message, events,
                        prompt or self._onboarding_prompt(capture_step or "carrier_name"),
                    )
                if session.route_availability_capture:
                    return self._conversation_result(
                        session, message, events,
                        "👋 ¡Hola! Hay un registro de recorrido pendiente. Enviá el dato que te pidió el bot o escribí «cancelar» para descartarlo.",
                    )
                return ConversationResult(
                    conversation_session=session,
                    message=message,
                    shipment_request=None,
                    response_text=self._carrier_menu_text(),
                    handoff_required=False,
                    events=tuple(events),
                    actions=self._carrier_menu_actions(),
                )
            if self._routing is not None:
                try:
                    preference_result = self._routing.capture_preference(session, carrier, text)
                    if preference_result:
                        response, actions = preference_result
                        return self._conversation_result(session, message, events, response, actions=actions)
                except ValueError as exc:
                    return self._conversation_result(session, message, events, f"⚠️ {exc}")
            if self._carrier_onboarding_service is not None:
                capture_context = self._carrier_onboarding_service.capture_context(carrier.id)
                capture_step = capture_context.get("step")
                if capture_step and capture_step != "complete":
                    if capture_step == "driver_license_upload":
                        return self._conversation_result(
                            session, message, events, self._onboarding_prompt(capture_step),
                        )
                    response, handoff = self._carrier_onboarding_service.process_whatsapp_capture_response(
                        carrier_id=carrier.id,
                        text=text,
                        correlation_id=inbound.correlation_id,
                    )
                    return self._conversation_result(session, message, events, response, handoff=handoff)
            if session.route_availability_capture:
                capture_result = self._handle_route_availability_capture(
                    inbound=inbound, session=session, message=message,
                    carrier=carrier, text=text, events=events,
                )
                if capture_result is not None:
                    return capture_result
            if self._is_route_availability_intent(text):
                session.route_availability_capture = {
                    "step": "origin",
                    "test_run_id": session.active_test_run_id,
                }
                session.mark_updated()
                self._conversation_sessions.save(session)
                self._event_log.record(
                    event_type="ROUTE_AVAILABILITY_CAPTURE_STARTED",
                    actor_type="Carrier", actor_id=carrier.id,
                    entity_type="ConversationSession", entity_id=session.id,
                    summary="Transportista inició el registro de un recorrido disponible",
                    related_entity_ids={"carrierId": carrier.id, "conversationSessionId": session.id},
                    source=inbound.provider, correlation_id=inbound.correlation_id,
                    idempotency_key=f"{inbound.idempotency_key}:route_capture_started",
                )
                return self._conversation_result(
                    session, message, events,
                    "🛣️ Vamos a registrar tu recorrido disponible. ¿Desde qué localidad salís? Escribí *cancelar* para salir.",
                )
            if self._normalize_response_text(text) in {
                "ver carga recibida",
                "ver la carga recibida",
                "ultima carga recibida",
            }:
                shipment = self._latest_notified_shipment_for_carrier(carrier)
                return ConversationResult(
                    conversation_session=session,
                    message=message,
                    shipment_request=shipment,
                    response_text=self._format_carrier_shipment(shipment),
                    handoff_required=False,
                    events=tuple(events),
                )
            if self._normalize_response_text(text) in {"estado", "mis cargas", "ver oportunidades", "oportunidades"}:
                active = self._active_notified_shipments_for_carrier(carrier)
                if not active:
                    return self._conversation_result(
                        session, message, events, "No tenés cargas recibidas activas por ahora."
                    )
                return self._conversation_result(
                    session,
                    message,
                    events,
                    f"Tenés {len(active)} carga(s) recibida(s). Respondé «ver carga recibida» para ver la última.",
                )
            return self._handle_carrier_response(
                inbound=inbound,
                session=session,
                message=message,
                carrier=carrier,
                text=text,
                events=events,
            )

        confirmation_result = self._handle_producer_confirmation_if_possible(
            inbound=inbound,
            session=session,
            message=message,
            text=text,
            events=events,
        )
        if confirmation_result is not None:
            return confirmation_result

        self_service_result = self._handle_producer_self_service_command(
            inbound=inbound,
            session=session,
            message=message,
            text=text,
            events=events,
        )
        if self_service_result is not None:
            return self_service_result

        extraction_text = text
        prior_load_messages = self._producer_load_messages_for_session(
            session,
            current_message=message,
        )
        # A complete new request starts a fresh draft. Combining it with older
        # requests can resurrect fields from a load that was already confirmed.
        # Only append genuinely partial corrections to the pending request.
        if (
            prior_load_messages
            and self._looks_like_partial_chat_shipment_update(text)
            and not self._looks_like_chat_shipment_request(text)
        ):
            extraction_text = self._combine_load_message_texts([*prior_load_messages, message])
        try:
            extraction = self._ai_client.extract_load_data(extraction_text)
        except AIExtractionError as exc:
            events.append(self._record_human_review_requested(message, inbound, str(exc)))
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="Recibimos el mensaje. Un operador lo revisa para continuar.",
                handoff_required=True,
                events=tuple(events),
            )

        if not any((
            extraction.cargo_type,
            extraction.livestock_type,
            extraction.quantity_estimate,
            extraction.origin,
            extraction.destination,
            extraction.date_window_start,
            extraction.date_window_end,
        )):
            return self._conversation_result(
                session, message, events, self._producer_menu_text(),
                actions=self._producer_menu_actions(),
            )
        extraction = replace(
            extraction,
            contact=extraction.contact or inbound.phone_number,
        )
        extraction = self._canonicalize_extraction(extraction, inbound.occurred_at)
        explicit_date_update = self._parse_chat_shipment_text(text, reference_datetime=inbound.occurred_at)
        if explicit_date_update.date_window_start is not None:
            extraction = replace(
                extraction,
                date_window_start=explicit_date_update.date_window_start,
                date_window_end=explicit_date_update.date_window_end,
            )
        missing_fields = self._detect_missing_fields(extraction)
        requires_human_review = bool(
            missing_fields
            or extraction.has_ambiguous_location
            or extraction.confidence in {"unknown", "low"}
        )
        events.append(self._record_load_preview_prepared(
            message=message,
            session=session,
            extraction=extraction,
            missing_fields=missing_fields,
            inbound=inbound,
            requires_human_review=requires_human_review,
        ))
        if requires_human_review:
            events.append(
                self._record_human_review_requested(
                    message,
                    inbound,
                    self._human_review_reason(missing_fields, extraction),
                )
            )

        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=None,
            response_text=self._build_response_text(
                missing_fields,
                requires_human_review,
                extraction=extraction,
            ),
            handoff_required=requires_human_review,
            events=tuple(events),
            actions=self._load_preview_actions() if not requires_human_review else (),
        )

    def _handle_producer_self_service_command(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        text: str,
        events: list[EventLog],
    ) -> ConversationResult | None:
        flow_match = re.fullmatch(
            r"agro:producer:(shipment|offer|confirm|cancel|loads|interested|offerpage):([A-Za-z0-9_-]+)(?::([A-Za-z0-9_-]+))?",
            text.strip(),
        )
        if flow_match:
            if "interactiveActionId" not in message.related_entity_ids:
                return self._conversation_result(
                    session, message, events,
                    "Esa opción ya no está disponible. Volvé a abrir la lista para consultar las opciones actuales.",
                )
            if self._admin_ops_service is None:
                return self._conversation_result(
                    session, message, events,
                    "Ahora no puedo consultar tus cargas. Te lo revisa soporte.",
                    handoff=True,
                )
            action, shipment_id, offer_id = flow_match.groups()
            phone = inbound.phone_number or session.participant_phone
            if action in {"loads", "interested"}:
                try:
                    page_offset = max(0, int(shipment_id))
                except ValueError:
                    page_offset = 0
                return self._show_producer_shipment_page(
                    session=session, message=message, events=events,
                    phone_number=phone, offset=page_offset,
                    interested_only=action == "interested",
                )
            if action == "offerpage":
                try:
                    offer_offset = max(0, int(offer_id or "0"))
                except ValueError:
                    offer_offset = 0
                return self._show_producer_shipment_offers(
                    session=session, message=message, events=events,
                    phone_number=phone, shipment_id=shipment_id, offset=offer_offset,
                )
            if action == "shipment":
                return self._show_producer_shipment_offers(
                    session=session, message=message, events=events,
                    phone_number=phone, shipment_id=shipment_id,
                )
            if action == "offer":
                return self._show_producer_offer_confirmation(
                    session=session, message=message, events=events,
                    phone_number=phone, shipment_id=shipment_id, offer_id=offer_id or "",
                )
            if action == "confirm":
                return self._confirm_producer_offer(
                    inbound=inbound, session=session, message=message, events=events,
                    phone_number=phone, shipment_id=shipment_id, offer_id=offer_id or "",
                )
            return self._show_producer_shipment_offers(
                session=session, message=message, events=events,
                phone_number=phone, shipment_id=shipment_id,
            )

        normalized = self._normalize_response_text(text)
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
        offer_acceptance = re.fullmatch(r"(?:elegir|aceptar)(?: oferta)?\s+\d+", normalized)
        if (
            not offer_acceptance
            and not self._looks_like_producer_self_service_command(text)
            and not self._looks_like_producer_menu_choice(text, session)
            and normalized not in {"editar", "edit"}
        ):
            return None
        if self._admin_ops_service is None:
            return self._conversation_result(
                session, message, events,
                "Ahora no puedo consultar tus cargas. Te lo revisa soporte.",
                handoff=True,
            )

        if self._is_greeting_or_menu(text):
            return self._conversation_result(
                session, message, events, self._producer_menu_text(),
                actions=self._producer_menu_actions(),
            )
        if normalized in {"crear carga", "1"} and not self._session_has_load_creation_context(session):
            return self._conversation_result(
                session, message, events,
                "Contame qué necesitás transportar, en qué cantidad, desde dónde, hacia dónde y para cuándo.",
            )
        if normalized in {"2", "editar", "edit"} and self._session_has_load_creation_context(session):
            return self._conversation_result(
                session, message, events,
                "Decime qué dato querés cambiar de la carga.",
            )

        query_kind = self._producer_query_kind(normalized)
        if query_kind == "shipments":
            try:
                shipments = self._admin_ops_service.list_producer_shipments(
                    phone_number=inbound.phone_number or session.participant_phone,
                    limit=10,
                )
            except (AdminOpsError, ValueError):
                return self._conversation_result(
                    session, message, events,
                    "Ahora no puedo consultar tus cargas. Te lo revisa soporte.",
                    handoff=True,
                )
            if not shipments:
                return self._conversation_result(session, message, events, "No encontré cargas para este número.")
            if len(shipments) == 1:
                return self._show_producer_shipment_offers(
                    session=session, message=message, events=events,
                    phone_number=inbound.phone_number or session.participant_phone,
                    shipment_id=shipments[0].shipment_id,
                )
            return self._show_producer_shipment_page(
                session=session, message=message, events=events,
                phone_number=inbound.phone_number or session.participant_phone,
                offset=0, interested_only=False,
            )

        if query_kind == "trips":
            try:
                dashboard = self._admin_ops_service.get_producer_dashboard(
                    phone_number=inbound.phone_number or session.participant_phone,
                    limit=5,
                )
            except (AdminOpsError, ValueError):
                return self._conversation_result(
                    session, message, events,
                    "Ahora no puedo consultar tus cargas. Te lo revisa soporte.",
                    handoff=True,
                )
            rows = (*dashboard.current_operations, *dashboard.past_operations)
            if not rows:
                return self._conversation_result(
                    session, message, events, "No encontré cargas para este número."
                )
            if query_kind == "trips":
                rows = tuple(row for row in rows if row.trip_id)
                if not rows:
                    return self._conversation_result(
                        session, message, events,
                        "Todavía no hay viajes asociados a tus cargas.",
                    )
            return self._conversation_result(
                session, message, events,
                self._format_producer_operations(rows, trips_only=query_kind == "trips"),
            )

        if query_kind == "offers":
            try:
                shipments = self._admin_ops_service.list_producer_shipments(
                    phone_number=inbound.phone_number or session.participant_phone,
                    limit=50,
                )
            except (AdminOpsError, ValueError):
                return self._conversation_result(
                    session, message, events,
                    "Ahora no puedo consultar tus interesados. Te lo revisa soporte.",
                    handoff=True,
                )
            if not shipments:
                return self._conversation_result(
                    session, message, events,
                    "Todavía no tenés cargas publicadas.",
                )
            with_interest = [item for item in shipments if item.interested_offers_count]
            if not with_interest:
                return self._conversation_result(
                    session, message, events,
                    "Todavía no hay transportistas interesados en tus cargas.",
                )
            if len(with_interest) == 1:
                return self._show_producer_shipment_offers(
                    session=session, message=message, events=events,
                    phone_number=inbound.phone_number or session.participant_phone,
                    shipment_id=with_interest[0].shipment_id,
                )
            return self._show_producer_shipment_page(
                session=session, message=message, events=events,
                phone_number=inbound.phone_number or session.participant_phone,
                offset=0, interested_only=True,
            )

        match = re.fullmatch(r"(?:elegir|aceptar)(?: oferta)?\s+(\d+)", normalized)
        if match:
            try:
                offers = self._admin_ops_service.list_producer_interested_offers(
                    phone_number=inbound.phone_number or session.participant_phone,
                    limit=10,
                )
                if not offers:
                    return self._conversation_result(
                        session, message, events,
                        "No hay ofertas pendientes para aceptar. Escribí «ver mi viaje» para consultar los viajes planificados.",
                    )
                index = int(match.group(1))
                offer = next(item for item in offers if item.index == index)
                return self._show_producer_offer_confirmation(
                    session=session, message=message, events=events,
                    phone_number=inbound.phone_number or session.participant_phone,
                    shipment_id=offer.shipment_id, offer_id=offer.trip_offer_id,
                )
            except (AdminOpsError, KeyError, ValueError, StopIteration):
                return self._conversation_result(
                    session, message, events,
                    "No pude aceptar esa oferta. Escribí «ver interesados» para revisar las opciones actuales.",
                    handoff=True,
                )

        if normalized in {"soporte", "5"}:
            return self._conversation_result(
                session, message, events,
                "Te derivo a soporte. Contame brevemente qué necesitás.",
                handoff=True,
            )
        return None

    def _show_producer_shipment_offers(
        self, *, session, message, events, phone_number: str | None, shipment_id: str,
        offset: int = 0,
    ) -> ConversationResult:
        try:
            shipments = self._admin_ops_service.list_producer_shipments(
                phone_number=phone_number or "", limit=50,
            )
            shipment = next(item for item in shipments if item.shipment_id == shipment_id)
            offers = self._admin_ops_service.list_producer_interested_offers(
                phone_number=phone_number or "", limit=50, shipment_request_id=shipment_id,
            )
        except (AdminOpsError, ValueError, StopIteration):
            return self._conversation_result(
                session, message, events,
                "No pude encontrar esa carga en tu cuenta o en este escenario. Volvé a consultar tus cargas.",
            )
        header = (
            f"📦 {shipment.origin or 'Origen a coordinar'} → {shipment.destination or 'destino a coordinar'}\n"
            f"📅 {self._shipment_date_label(shipment.date_window_start)} · "
            f"{self._producer_status_label(shipment.status)}"
        )
        if not offers:
            return self._conversation_result(
                session, message, events,
                f"{header}\n\nTodavía no hay interesados disponibles para esta carga.",
            )

        lines = [header, "", "👥 Transportistas interesados:"]
        for offer in offers:
            carrier = self._carriers.get(offer.carrier_id) if self._carriers else None
            lines.append(self._producer_offer_summary_line(offer.index, offer, carrier))

        page_size = 9 if len(offers) - offset > 10 else 10
        visible_offers = offers[offset:offset + page_size]
        if len(offers) <= 3:
            actions = tuple(
                OutboundAction(
                    id=f"producer_offer_{offer.shipment_id}_{offer.trip_offer_id}",
                    label=f"Aceptar {offer.index}",
                    value=f"agro:producer:offer:{offer.shipment_id}:{offer.trip_offer_id}",
                )
                for offer in visible_offers
            )
            lines.append("\nElegí una opción; antes de confirmar te mostraremos el transportista seleccionado.")
            return self._conversation_result(session, message, events, "\n".join(lines), actions=actions)

        actions = tuple(
            OutboundAction(
                id=f"producer_offer_{offer.shipment_id}_{offer.trip_offer_id}",
                label=(self._carrier_display_name(self._carriers.get(offer.carrier_id) if self._carriers else None)),
                value=f"agro:producer:offer:{offer.shipment_id}:{offer.trip_offer_id}",
                kind="list_row",
                metadata={
                    "description": self._producer_offer_description(
                        offer, self._carriers.get(offer.carrier_id) if self._carriers else None,
                    ),
                },
            )
            for offer in visible_offers
        )
        if offset + page_size < len(offers):
            actions += (
                OutboundAction(
                    id=f"producer_offerpage_{shipment_id}_{offset + page_size}",
                    label="Ver más transportistas",
                    value=f"agro:producer:offerpage:{shipment_id}:{offset + page_size}",
                    kind="list_row",
                ),
            )
        lines.append("\nElegí un transportista para revisar su oferta y confirmar.")
        return self._conversation_result(session, message, events, "\n".join(lines), actions=actions)

    def _show_producer_shipment_page(
        self, *, session, message, events, phone_number: str | None,
        offset: int, interested_only: bool,
    ) -> ConversationResult:
        try:
            shipments = self._admin_ops_service.list_producer_shipments(
                phone_number=phone_number or "", limit=50,
            )
        except (AdminOpsError, ValueError):
            return self._conversation_result(
                session, message, events,
                "Ahora no puedo consultar tus cargas. Te lo revisa soporte.", handoff=True,
            )
        if interested_only:
            shipments = [item for item in shipments if item.interested_offers_count]
        if not shipments:
            message_text = (
                "Todavía no hay transportistas interesados en tus cargas."
                if interested_only else "No encontré cargas para este número."
            )
            return self._conversation_result(session, message, events, message_text)
        page_offset = min(offset, max(0, len(shipments) - 1))
        page_size = 9 if len(shipments) - page_offset > 10 else 10
        visible = shipments[page_offset:page_offset + page_size]
        actions = tuple(
            OutboundAction(
                id=f"producer_load_{shipment.shipment_id}",
                label=self._producer_shipment_route_title(shipment),
                value=f"agro:producer:shipment:{shipment.shipment_id}",
                kind="list_row",
                metadata={"description": self._producer_shipment_description(shipment)},
            )
            for shipment in visible
        )
        if page_offset + page_size < len(shipments):
            page_action = "interested" if interested_only else "loads"
            actions += (
                OutboundAction(
                    id=f"producer_{page_action}_{page_offset + page_size}",
                    label="Ver más cargas",
                    value=f"agro:producer:{page_action}:{page_offset + page_size}",
                    kind="list_row",
                ),
            )
        body = (
            "👥 Elegí una carga para ver quiénes se interesaron."
            if interested_only
            else "📦 Elegí una carga para ver su estado y los transportistas interesados."
        )
        return self._conversation_result(session, message, events, body, actions=actions)

    def _show_producer_offer_confirmation(
        self, *, session, message, events, phone_number: str | None,
        shipment_id: str, offer_id: str,
    ) -> ConversationResult:
        try:
            shipments = self._admin_ops_service.list_producer_shipments(
                phone_number=phone_number or "", limit=50,
            )
            shipment = next(item for item in shipments if item.shipment_id == shipment_id)
            offers = self._admin_ops_service.list_producer_interested_offers(
                phone_number=phone_number or "", limit=50, shipment_request_id=shipment_id,
            )
            offer = next(item for item in offers if item.trip_offer_id == offer_id)
        except (AdminOpsError, ValueError, StopIteration):
            return self._conversation_result(
                session, message, events,
                "Esa oferta ya no está disponible. Volvé a abrir la carga para consultar las opciones actuales.",
            )
        carrier = self._carriers.get(offer.carrier_id) if self._carriers else None
        actions = (
            OutboundAction(
                id=f"confirm_offer_{shipment_id}_{offer_id}",
                label="✅ Confirmar",
                value=f"agro:producer:confirm:{shipment_id}:{offer_id}",
            ),
            OutboundAction(
                id=f"back_to_offers_{shipment_id}",
                label="↩️ Volver",
                value=f"agro:producer:cancel:{shipment_id}",
            ),
        )
        return self._conversation_result(
            session, message, events,
            f"📦 Carga: {shipment.origin or 'Origen a coordinar'} → {shipment.destination or 'destino a coordinar'}\n"
            f"📅 Fecha: {self._shipment_date_label(shipment.date_window_start)}\n\n"
            f"🚚 Transportista elegido: {self._carrier_display_name(carrier)}\n"
            f"{self._producer_offer_description(offer, carrier)}\n\n"
            "✅ ¿Confirmás aceptar esta oferta? Al confirmar se planificará el viaje.",
            actions=actions,
        )

    def _confirm_producer_offer(
        self, *, inbound, session, message, events, phone_number: str | None,
        shipment_id: str, offer_id: str,
    ) -> ConversationResult:
        try:
            offers = self._admin_ops_service.list_producer_interested_offers(
                phone_number=phone_number or "", limit=50, shipment_request_id=shipment_id,
            )
            offer = next(item for item in offers if item.trip_offer_id == offer_id)
            result = self._admin_ops_service.accept_offer_by_producer(
                shipment_request_id=shipment_id,
                trip_offer_id=offer.trip_offer_id,
                producer_phone_number=phone_number or "",
                idempotency_key=f"{inbound.idempotency_key}:producer_accept_offer",
            )
        except (AdminOpsError, KeyError, ValueError, StopIteration):
            return self._conversation_result(
                session, message, events,
                "No pude confirmar esa oferta; puede haber cambiado desde que la viste. Consultá nuevamente los interesados.",
                handoff=True,
            )
        carrier = self._carriers.get(offer.carrier_id) if self._carriers else None
        return self._conversation_result(
            session, message, events,
            f"✅ Match confirmado con {self._carrier_display_name(carrier)}. El viaje quedó planificado.\n"
            f"📦 {self._location_label(result.shipment.origin_location_id) or 'Origen'} → "
            f"{self._location_label(result.shipment.destination_location_id) or 'destino'}",
        )

    def _producer_shipment_route_title(self, shipment) -> str:
        route = f"{shipment.origin or 'Origen'} → {shipment.destination or 'Destino'}"
        if len(route) <= 24:
            return route
        return route[:23].rstrip() + "…"

    def _producer_shipment_description(self, shipment) -> str:
        interest_label = "1 interesado" if shipment.interested_offers_count == 1 else f"{shipment.interested_offers_count} interesados"
        return (
            f"{self._shipment_date_label(shipment.date_window_start)} · {interest_label} · "
            f"{self._producer_status_label(shipment.status)}"
        )[:72]

    def _producer_offer_summary_line(self, index: int, offer, carrier: Carrier | None) -> str:
        name = self._carrier_display_name(carrier)
        company = f" ({carrier.company_name})" if carrier and carrier.company_name else ""
        vehicle = self._carrier_equipment_label(carrier)
        verification = "Homologado" if carrier and carrier.is_validated else "Homologación pendiente"
        cargo = offer.cargo_type or offer.livestock_type or "carga"
        quantity = self._quantity_label(offer.quantity_estimate, offer.quantity_unit)
        extras = [value for value in (verification, vehicle) if value]
        return f"{index}. {name}{company} — {quantity} {cargo}; " + "; ".join(extras)

    def _producer_offer_description(self, offer, carrier: Carrier | None) -> str:
        company = carrier.company_name if carrier and carrier.company_name else ""
        vehicle = self._carrier_equipment_label(carrier)
        verification = "Homologado" if carrier and carrier.is_validated else "Revisión pendiente"
        cargo = offer.cargo_type or offer.livestock_type or "carga"
        quantity = self._quantity_label(offer.quantity_estimate, offer.quantity_unit)
        return " · ".join(value for value in (company, verification, vehicle, f"Ofrece por {quantity} {cargo}") if value)[:72]

    def _carrier_display_name(self, carrier: Carrier | None) -> str:
        if carrier is None:
            return "Transportista"
        return carrier.name or carrier.company_name or "Transportista"

    def _carrier_equipment_label(self, carrier: Carrier | None) -> str:
        if carrier is None:
            return ""
        equipment = carrier.truck_body_type or ", ".join(carrier.truck_types)
        return f"Equipo: {equipment}" if equipment else ""

    @staticmethod
    def _shipment_date_label(value: datetime | None) -> str:
        if value is None:
            return "Fecha a coordinar"
        return value.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d/%m/%Y")

    @staticmethod
    def _producer_status_label(status: str) -> str:
        return {
            "DRAFT": "Borrador",
            "INCOMPLETE": "Incompleta",
            "PENDING_OPERATOR_REVIEW": "Pendiente de revisión",
            "VALIDATED": "Validada",
            "PUBLISHED": "Publicada",
            "MATCHING": "Buscando transportista",
            "ASSIGNED": "Asignada",
            "CANCELLED": "Cancelada",
            "CLOSED": "Cerrada",
        }.get(status, "Estado a revisar")

    def _conversation_result(
        self,
        session: ConversationSession,
        message: Message,
        events: list[EventLog],
        response_text: str,
        *,
        handoff: bool = False,
        actions: tuple[OutboundAction, ...] = (),
    ) -> ConversationResult:
        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=None,
            response_text=response_text,
            handoff_required=handoff,
            events=tuple(events),
            actions=actions,
        )

    @staticmethod
    def _load_preview_actions() -> tuple[OutboundAction, ...]:
        return (
            OutboundAction(id="confirmar", label="✅ Confirmar", value="confirmar"),
            OutboundAction(id="editar", label="✏️ Editar", value="editar"),
        )

    def _producer_query_kind(self, normalized: str) -> str | None:
        if normalized in {"2", "ver mi carga", "ver mis cargas", "ver cargas", "mis cargas", "consultar mi carga", "estado de mi carga"} or "ver mi carga" in normalized or "ver mis cargas" in normalized:
            return "shipments"
        if normalized in {"3", "ver mi viaje", "mis viajes", "estado de mi viaje", "estado de mis viajes"} or "ver mi viaje" in normalized:
            return "trips"
        if normalized in {"4", "ver interesados", "ver ofertas", "transportistas interesados"} or "ver interesados" in normalized:
            return "offers"
        return None

    def _is_greeting_or_menu(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
        if normalized in {
            "hola", "hi", "buen dia", "buenos dias", "buenas", "buenas tardes",
            "buenas noches", "menu", "que puedo hacer", "que opciones tengo",
        }:
            return True
        return bool(
            re.fullmatch(
                r"(?:hola|hi|buenas?|buen dia|buenos dias|buenas tardes|buenas noches)"
                r"(?: (?:como va|como estas|como andas|que tal|todo bien|y vos|y tu))*",
                normalized,
            )
        )

    def _is_carrier_onboarding_intent(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        return any(
            phrase in normalized
            for phrase in (
                "quiero registrarme como transportista",
                "quiero darme de alta como transportista",
                "iniciar homologacion",
                "quiero homologarme",
                "alta de transportista",
                "registrarme como camionero",
            )
        )

    def _onboarding_prompt(self, step: str) -> str:
        prompts = {
            "carrier_name": "Vamos a iniciar tu solicitud de alta como transportista. ¿Cuál es tu nombre y apellido o razón social?",
            "email": "¿Qué email podemos usar? Si no tenés, respondé «no tengo». ",
            "company_name": "¿Tenés empresa? Decime el nombre o respondé «no corresponde». ",
            "cuit": "Pasame el CUIT de 11 dígitos, sin puntos ni guiones.",
            "truck_count": "¿Cuántas unidades tenés? Respondé con un número.",
            "vehicle_plate": "Pasame la patente de una unidad para empezar.",
            "vehicle_type": "¿Qué tipo de camión es?",
            "vehicle_body_type": "¿Qué carrocería tiene? Por ejemplo, jaula o baranda.",
            "driver_name": "¿Quién va a manejar esa unidad? Indicá nombre y apellido.",
            "driver_phone": "Pasame el teléfono del conductor. Si usa este mismo número, respondé «mismo».",
            "license_category": "¿Qué categoría figura en su licencia de conducir?",
            "driver_license_upload": "Ahora enviá una foto o archivo de la licencia de ese conductor.",
            "add_another_vehicle": "¿Querés cargar otra unidad y su conductor ahora? Respondé sí o no.",
            "complete": "Ya recibí tus datos. Soporte debe revisarlos antes de habilitar tu perfil.",
        }
        return prompts.get(step, prompts["carrier_name"])

    def _producer_menu_text(self) -> str:
        return "👋 ¿Qué necesitás hacer hoy?\n\n📦 Cargas · 🚚 Viajes · 💬 Ayuda"

    def _carrier_menu_text(self) -> str:
        return "👋 ¿Qué necesitás hacer?\n\n📦 Cargas · 🚚 Recorridos · 💬 Ayuda"

    @staticmethod
    def _producer_menu_actions() -> tuple[OutboundAction, ...]:
        return (
            OutboundAction(id="crear_carga", label="📦 Crear carga", value="crear carga"),
            OutboundAction(id="ver_carga", label="📋 Ver mis cargas", value="ver mis cargas"),
            OutboundAction(id="ver_viaje", label="🚚 Ver mi viaje", value="ver mi viaje"),
            OutboundAction(id="ver_interesados", label="👥 Ver interesados", value="ver interesados"),
            OutboundAction(id="soporte", label="💬 Soporte", value="soporte"),
        )

    @staticmethod
    def _carrier_menu_actions() -> tuple[OutboundAction, ...]:
        return (
            OutboundAction(id="ver_carga_recibida", label="📦 Carga recibida", value="ver carga recibida"),
            OutboundAction(id="me_interesa", label="✅ Me interesa", value="INTERESTED"),
            OutboundAction(id="no_puedo", label="❌ No puedo", value="DECLINED"),
            OutboundAction(id="mas_info", label="ℹ️ Más info", value="MORE_INFO"),
            OutboundAction(id="informar_disponibilidad", label="🛣️ Recorrido", value="informar disponibilidad"),
            OutboundAction(id="mis_recorridos", label="🛣️ Mis recorridos", value="mis recorridos"),
            OutboundAction(id="nuevo_habitual", label="➕ Nuevo habitual", value="agregar recorrido habitual"),
        )

    def _is_route_availability_intent(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
        return normalized in {
            "informar disponibilidad", "recorrido", "publicar recorrido",
            "informar viaje disponible", "tengo un viaje disponible", "tengo disponibilidad",
        }

    def _handle_route_availability_capture(
        self, *, inbound: InboundConversationMessage, session: ConversationSession,
        message: Message, carrier: Carrier, text: str, events: list[EventLog],
    ) -> ConversationResult | None:
        capture = session.route_availability_capture
        if capture.get("test_run_id") != session.active_test_run_id:
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            return self._conversation_result(
                session, message, events,
                "El escenario cambió y descarté el formulario pendiente. Volvé a elegir 🛣️ Recorrido para iniciar uno nuevo.",
            )
        normalized = self._normalize_response_text(text)
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
        if normalized in {"cancelar", "cancel", "salir"}:
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            return self._conversation_result(session, message, events, "Registro de recorrido cancelado.")

        step = capture.get("step")
        prompts = {
            "origin": "📍 ¿Cuál es la localidad de origen?",
            "destination": "📍 ¿Cuál es la localidad de destino?",
            "date": "📅 ¿Qué fecha o día tenés previsto? Por ejemplo: 14/10/2026 o viernes.",
            "stops": "🛣️ ¿Qué paradas intermedias declarás? Indicá localidad y provincia; separá paradas con punto y coma, o respondé *sin paradas*.",
            "capacity": "📦 ¿Qué capacidad libre ofrecés e indicando unidad? Ejemplos: 25 cabezas, 28 toneladas, 12000 kg o 1 camión.",
            "equipment": "🚚 ¿Qué tipo de equipo tenés para este recorrido? Ejemplo: jaula, granelero, batea o sider.",
        }
        if step in {"origin", "destination"}:
            if len(text.strip()) < 2 or len(text.strip()) > 100:
                return self._conversation_result(session, message, events, f"{prompts[step]} (localidad de 2 a 100 caracteres).")
            if self._routing is not None:
                try:
                    value = self._routing.node(text)['label']
                except ValueError as exc:
                    return self._conversation_result(session, message, events, f"📍 {exc}")
            else:
                value = text.strip()
            capture[step] = value
            capture["step"] = "destination" if step == "origin" else "date"
        elif step == "date":
            parsed = self._parse_chat_shipment_text(text, reference_datetime=inbound.occurred_at)
            if parsed.date_window_start is None:
                return self._conversation_result(session, message, events, prompts[step])
            start = parsed.date_window_start
            if inbound.occurred_at is not None:
                reference = inbound.occurred_at
                if reference.tzinfo is None:
                    reference = reference.replace(tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
                if start.date() < reference.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).date():
                    return self._conversation_result(session, message, events, "Esa fecha ya pasó. Indicá una fecha futura para el recorrido.")
            capture["window_start"] = start.isoformat()
            # Date-only declarations remain valid for the full day in Argentina.
            local_day_end = start.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).replace(hour=23, minute=59, second=59, microsecond=0)
            capture["window_end"] = local_day_end.isoformat()
            capture["step"] = "stops"
        elif step == "stops":
            if normalized not in {"sin paradas", "ninguna", "no", "ninguna parada"}:
                stops = [part.strip() for part in re.split(r";|\|", text) if part.strip()]
                if self._routing is not None:
                    try:
                        stops = [self._routing.node(value)['label'] for value in stops]
                    except ValueError as exc:
                        return self._conversation_result(session, message, events, f"📍 {exc}. Separá cada parada con punto y coma.")
                if not stops or any(len(part) > 100 for part in stops):
                    return self._conversation_result(session, message, events, prompts[step])
                capture["stops"] = stops
            else:
                capture["stops"] = []
            capture["step"] = "capacity"
        elif step == "capacity":
            parsed = self._parse_chat_shipment_text(text, reference_datetime=inbound.occurred_at)
            unit = extract_explicit_quantity_unit(text)
            amount = parsed.quantity_estimate
            if amount is None or unit is None or amount <= 0:
                return self._conversation_result(session, message, events, prompts[step])
            capture["capacity"] = str(amount)
            capture["capacity_unit"] = unit
            capture["step"] = "cargo"
        elif step == "cargo":
            parsed = self._parse_chat_shipment_text(text, reference_datetime=inbound.occurred_at)
            if not parsed.cargo_type:
                return self._conversation_result(
                    session, message, events,
                    self._route_availability_cargo_prompt(capture.get("capacity_unit")),
                )
            capture["cargo_types"] = [parsed.cargo_type]
            capture["step"] = "equipment"
        elif step == "equipment":
            if len(text.strip()) < 2 or len(text.strip()) > 100:
                return self._conversation_result(session, message, events, prompts[step])
            capture["equipment_types"] = [text.strip()]
            capture["step"] = "confirm"
            session.route_availability_capture = capture
            session.mark_updated()
            self._conversation_sessions.save(session)
            date_label = datetime.fromisoformat(capture["window_start"]).astimezone(
                ZoneInfo("America/Argentina/Buenos_Aires")
            ).strftime("%d/%m/%Y")
            stops_label = ", ".join(capture.get("stops", [])) or "sin paradas declaradas"
            summary = (
                "🛣️ *Revisá el recorrido disponible:*\n"
                f"📍 {capture['origin']} → {capture['destination']}\n"
                f"📅 {date_label} (día completo)\n"
                f"↪️ Paradas: {stops_label}\n"
                f"📦 Capacidad: {capture['capacity']} {quantity_unit_label(capture['capacity_unit']) or capture['capacity_unit']}\n"
                f"🌾 Carga: {', '.join(capture['cargo_types'])}\n"
                f"🚚 Equipo: {', '.join(capture['equipment_types'])}\n\n"
                "¿Confirmás estos datos?\n\n✅ Confirmar · ✏️ Editar (también podés responder 1 o 2)."
            )
            return self._conversation_result(
                session, message, events, summary,
                actions=(OutboundAction(id="confirmar_recorrido", label="✅ Confirmar", value="confirmar"),
                         OutboundAction(id="editar_recorrido", label="✏️ Editar", value="editar")),
            )
        elif step == "confirm":
            if normalized in {"editar", "edit", "2"}:
                capture.clear()
                session.route_availability_capture = capture
                session.mark_updated()
                self._conversation_sessions.save(session)
                return self._conversation_result(
                    session, message, events,
                    "Reiniciemos el registro para corregir los datos. ¿Desde qué localidad salís? Escribí *cancelar* para salir.",
                )
            if normalized not in {"confirmar", "confirmo", "1", "si", "sí"}:
                return self._conversation_result(
                    session, message, events,
                    "Para guardar, elegí *Confirmar* o *Editar*.",
                    actions=(OutboundAction(id="confirmar_recorrido", label="✅ Confirmar", value="confirmar"),
                             OutboundAction(id="editar_recorrido", label="✏️ Editar", value="editar")),
                )
            if self._route_availabilities is None:
                return self._conversation_result(session, message, events, "No pude guardar el recorrido porque el almacenamiento no está disponible. Probá más tarde.", handoff=True)
            try:
                availability = RouteAvailability(
                    carrier_id=carrier.id, origin=capture["origin"], destination=capture["destination"],
                    window_start=datetime.fromisoformat(capture["window_start"]),
                    window_end=datetime.fromisoformat(capture["window_end"]),
                    capacity=Decimal(capture["capacity"]), capacity_unit=capture["capacity_unit"],
                    cargo_types=capture["cargo_types"], equipment_types=capture["equipment_types"],
                    stops=capture.get("stops", []),
                    test_run_id=session.active_test_run_id,
                    status="ACTIVE" if carrier.is_validated else "DRAFT",
                    declared_by_user_id=carrier.user_id,
                )
            except (KeyError, ValueError, InvalidOperation):
                return self._conversation_result(session, message, events, "Hay un dato del recorrido que no pude validar. Escribí *Editar* para volver a cargarlo.")
            self._route_availabilities.add(availability)
            self._event_log.record(
                event_type="ROUTE_AVAILABILITY_CREATED", actor_type="Carrier", actor_id=carrier.id,
                entity_type="RouteAvailability", entity_id=availability.id,
                summary="Transportista declaró una disponibilidad de recorrido",
                related_entity_ids={"carrierId": carrier.id, "conversationSessionId": session.id, "messageId": message.id},
                new_state=availability.status,
                payload={"test_run_id": session.active_test_run_id, "origin": availability.origin,
                         "destination": availability.destination, "status": availability.status},
                source=inbound.provider, correlation_id=inbound.correlation_id,
                idempotency_key=f"{inbound.idempotency_key}:route_availability_created",
            )
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            result = "✅ Recorrido registrado. Ya podés consultarlo en el backoffice; el sistema no crea un viaje ni compromete capacidad automáticamente."
            if not carrier.is_validated:
                result = "✅ Recorrido recibido y enviado a revisión de soporte. Quedará como borrador hasta que el transportista esté aprobado."
            return self._conversation_result(session, message, events, result)
        else:
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            return self._conversation_result(session, message, events, "El registro quedó reiniciado. Elegí 🛣️ Recorrido para empezar de nuevo.")

        session.route_availability_capture = capture
        session.mark_updated()
        self._conversation_sessions.save(session)
        next_step = capture["step"]
        prompt = (
            self._route_availability_cargo_prompt(capture.get("capacity_unit"))
            if next_step == "cargo"
            else prompts[next_step]
        )
        return self._conversation_result(session, message, events, prompt)

    @staticmethod
    def _route_availability_cargo_prompt(capacity_unit: str | None) -> str:
        if capacity_unit == "HEAD":
            return "🐄 ¿Qué categoría de hacienda podés transportar? Por ejemplo: novillos, vacas o toros."
        if capacity_unit in {"TON", "KG"}:
            return "🌾 ¿Qué grano o cereal podés transportar? Por ejemplo: soja, trigo o maíz."
        return (
            "📦 ¿Qué tipo concreto de carga podés transportar? "
            "Por ejemplo, hacienda (novillos, vacas o toros) o granos (soja, trigo o maíz)."
        )

    def _format_producer_operations(self, rows, *, trips_only: bool) -> str:
        lines = ["Tus viajes:" if trips_only else "Tus cargas:"]
        for row in rows:
            if trips_only and not row.trip_id:
                continue
            cargo = row.cargo_type or row.livestock_type or row.cargo_category or "carga"
            quantity = self._quantity_label(row.quantity_estimate, row.quantity_unit)
            route = " → ".join(part for part in (row.origin, row.destination) if part)
            line = f"• {quantity} {cargo} — {row.shipment_status}"
            if route:
                line += f" — {route}"
            if row.trip_id:
                line += f" — Viaje {row.trip_id}: {row.trip_status}"
            lines.append(line)
        return "\n".join(lines)

    def _quantity_label(self, quantity, unit: str | None) -> str:
        if quantity is None:
            return "Cantidad sin informar"
        if unit is None:
            return f"{quantity} (unidad pendiente)"
        unit_label = quantity_unit_label(unit) or unit
        return f"{quantity} {unit_label}".strip()

    def _latest_notified_shipment_for_carrier(self, carrier: Carrier) -> ShipmentRequest | None:
        active = self._active_notified_shipments_for_carrier(carrier)
        return active[0] if active else None

    def _format_carrier_shipment(self, shipment: ShipmentRequest | None) -> str:
        if shipment is None:
            return "No encontré una carga recibida activa. Si te enviamos una, respondé 1 Me interesa, 2 No puedo o 3 Más info."
        origin = self._location_label(shipment.origin_location_id)
        destination = self._location_label(shipment.destination_location_id)
        cargo = shipment.cargo_type or shipment.livestock_type or shipment.cargo_category or "carga"
        quantity = self._quantity_label(shipment.quantity_estimate, shipment.quantity_unit)
        date = shipment.date_window_start
        date_label = date.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d/%m/%Y") if date else "a coordinar"
        return (
            f"Carga recibida: {quantity} de {cargo}.\nOrigen: {origin or 'a coordinar'}.\n"
            f"Destino: {destination or 'a coordinar'}.\nFecha: {date_label}.\n\n"
            "Respondé 1 Me interesa, 2 No puedo o 3 Más info."
        )

    def _location_label(self, location_id: str | None) -> str | None:
        location = self._locations.get(location_id) if location_id else None
        return location.original_text if location else None

    def _handle_producer_confirmation_if_possible(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        text: str,
        events: list[EventLog],
    ) -> ConversationResult | None:
        if not self._is_producer_confirmation(text):
            return None

        load_messages = self._producer_load_messages_for_session(session, current_message=message)
        if not load_messages:
            return None
        load_message = load_messages[-1]

        idempotency_key = f"conversation:{session.id}:chat_draft:{load_message.id}"
        existing = self._shipment_from_chat_draft_event(idempotency_key)
        if existing is not None:
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=existing,
                response_text=(
                    f"Carga ya publicada: {existing.id}"
                    if existing.status in {"PUBLISHED", "MATCHING", "ASSIGNED"}
                    else f"Carga ya registrada: {existing.id}"
                ),
                handoff_required=False,
                events=tuple(events),
            )

        combined_text = self._combine_load_message_texts(load_messages)
        parsed = self._parse_chat_shipment_from_messages(
            load_messages,
            reference_datetime=inbound.occurred_at,
        )
        canonical_notes = self._build_chat_operational_notes(
            load_messages,
            parsed=parsed,
            reference_datetime=inbound.occurred_at,
        )
        missing_fields = self._chat_missing_fields(parsed)
        if "quantity_unit" in missing_fields:
            return self._conversation_result(
                session,
                message,
                events,
                f"Para terminar, necesito confirmar {self._field_label('quantity_unit')}. ¿Me lo indicás?",
            )
        normalized_phone = self._safe_normalize_phone_number(inbound.phone_number)
        origin_location_id, ambiguous_origin = self._create_location(
            parsed.origin,
            "provided" if parsed.origin else None,
        )
        destination_location_id, ambiguous_destination = self._create_location(
            parsed.destination,
            "provided" if parsed.destination else None,
        )
        has_ambiguous_location = ambiguous_origin or ambiguous_destination
        can_self_publish = self._can_self_publish_chat_shipment(parsed) and not has_ambiguous_location
        shipment = self._shipment_requests.add(
            ShipmentRequest(
                status="DRAFT" if can_self_publish else "PENDING_OPERATOR_REVIEW",
                producer_phone_number=normalized_phone,
                origin_location_id=origin_location_id,
                destination_location_id=destination_location_id,
                date_window_start=parsed.date_window_start,
                date_window_end=parsed.date_window_end,
                cargo_category=parsed.cargo_category,
                cargo_type=parsed.cargo_type,
                quantity_unit=parsed.quantity_unit,
                livestock_type=parsed.livestock_type,
                quantity_estimate=parsed.quantity_estimate,
                weight_per_head_kg=parsed.weight_per_head_kg,
                operational_notes=canonical_notes,
                field_confidence=self._chat_field_confidence(parsed),
                missing_critical_fields=self._chat_missing_fields(parsed),
                requires_human_review=not can_self_publish,
                has_ambiguous_location=has_ambiguous_location,
                source_message_id=load_message.id,
                test_run_id=session.active_test_run_id,
            )
        )
        events.append(
            self._event_log.record(
                event_type="SHIPMENT_DRAFT_CREATED_FROM_CHAT",
                actor_type="Producer",
                entity_type="ShipmentRequest",
                entity_id=shipment.id,
                summary="Borrador de carga creado desde confirmacion por chat",
                related_entity_ids={
                    "loadId": shipment.id,
                    "messageId": load_message.id,
                    "confirmationMessageId": message.id,
                    "conversationSessionId": session.id,
                },
                new_state=shipment.status,
                payload={
                    "text": combined_text,
                    "operational_notes": canonical_notes,
                    "phone_number": inbound.phone_number,
                    "source": "kapso",
                    "trigger": "producer_confirmation",
                    "origin": parsed.origin,
                    "destination": parsed.destination,
                    "date_window_start": parsed.date_window_start.isoformat()
                    if parsed.date_window_start is not None
                    else None,
                    "cargo_category": shipment.cargo_category,
                    "cargo_type": shipment.cargo_type,
                    "quantity_estimate": str(shipment.quantity_estimate)
                    if shipment.quantity_estimate is not None
                    else None,
                    "quantity_unit": shipment.quantity_unit,
                    "weight_per_head_kg": str(shipment.weight_per_head_kg)
                    if shipment.weight_per_head_kg is not None
                    else None,
                },
                source=inbound.provider,
                correlation_id=inbound.correlation_id,
                idempotency_key=idempotency_key,
            )
        )
        if can_self_publish:
            carrier_ids = [] if self._routing is not None else self._eligible_carrier_ids(inbound.phone_number)
            published_event = self._transitions.transition(
                entity_type="ShipmentRequest",
                entity_id=shipment.id,
                from_state=shipment.status,
                event_type="LOAD_SELF_PUBLISHED",
                to_state="PUBLISHED",
                actor_type="Producer",
                summary="Carga publicada automaticamente por confirmacion del productor",
                related_entity_ids={
                    "loadId": shipment.id,
                    "messageId": load_message.id,
                    "confirmationMessageId": message.id,
                    "conversationSessionId": session.id,
                },
                payload={
                    "carrier_ids": carrier_ids,
                    "carrier_count": len(carrier_ids),
                    "producer_phone_number": self._mask_phone(normalized_phone),
                },
                source=inbound.provider,
                correlation_id=inbound.correlation_id,
                idempotency_key=f"{idempotency_key}:self_published",
            )
            events.append(published_event)
            shipment.status = published_event.new_state or shipment.status
            self._shipment_requests.save(shipment)
            events.append(
                self._event_log.record(
                    event_type="BROADCAST_SENT",
                    actor_type="SYSTEM",
                    entity_type="ShipmentRequest",
                    entity_id=shipment.id,
                    summary="Broadcast marketplace registrado",
                    related_entity_ids={"loadId": shipment.id},
                    payload={
                        "carrier_count": len(carrier_ids),
                        "carrier_ids": carrier_ids,
                        "trigger": "producer_self_publish",
                    },
                    source="marketplace",
                    correlation_id=inbound.correlation_id,
                    idempotency_key=f"{idempotency_key}:broadcast",
                )
            )
            if self._routing is not None:
                self._routing.publish(shipment)
            for carrier_id in carrier_ids:
                events.append(
                    self._event_log.record(
                        event_type="CARRIER_NOTIFIED",
                        actor_type="SYSTEM",
                        entity_type="ShipmentRequest",
                        entity_id=shipment.id,
                        summary="Transportista seleccionado para notificacion marketplace",
                        related_entity_ids={"loadId": shipment.id, "carrierId": carrier_id},
                        payload={"carrier_id": carrier_id, "trigger": "producer_self_publish"},
                        source="marketplace",
                        correlation_id=inbound.correlation_id,
                        idempotency_key=f"{idempotency_key}:carrier:{carrier_id}",
                    )
                )
            if self._notification_service is not None and carrier_ids:
                for notification_result in self._notification_service.send_new_load_alerts(
                    shipment=shipment,
                    carrier_ids=carrier_ids,
                    operator_user_id=None,
                ):
                    events.extend(notification_result.events)
        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=shipment,
            response_text=(
                f"Carga publicada: {shipment.id}"
                if shipment.status == "PUBLISHED"
                else f"Carga enviada a soporte: {shipment.id}"
            ),
            handoff_required=shipment.requires_human_review,
            events=tuple(events),
        )

    def _is_producer_confirmation(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        if normalized in {"1", "confirmar", "confirmo", "si", "dale"}:
            return True
        confirmation_phrases = (
            "confirmar",
            "confirmo",
            "confirmalo",
            "si confirmar",
            "si confirmo",
            "si confirmalo",
        )
        return any(self._contains_response_phrase(normalized, phrase) for phrase in confirmation_phrases)

    def _should_route_known_contact_as_producer(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        carrier: Carrier,
        text: str,
    ) -> bool:
        if inbound.action_selection is not None:
            sent = self._resolve_sent_action(selection_id=inbound.action_selection.id, session=session, carrier=None)
            if sent and str(sent.get("value", "")).startswith("agro:producer:"):
                return True
        else:
            recent = self._match_text_to_recent_action(carrier=None, session=session, text=text)
            if recent and recent.value.startswith("agro:producer:"):
                return True
        if not text:
            return False
        if self._looks_like_operator_command(text) or self._looks_like_carrier_availability_report(text):
            return False
        has_producer_menu_context = self._looks_like_producer_menu_choice(text, session)
        has_load_creation_context = self._session_has_load_creation_context(session)
        carrier_shipment = self._resolve_shipment_for_carrier_response(carrier, session, inbound)
        if (
            carrier_shipment is not None
            and self._looks_like_explicit_carrier_load_response(text)
            and not has_producer_menu_context
            and not has_load_creation_context
        ):
            return False
        if self._looks_like_chat_shipment_request(text) or self._looks_like_partial_chat_shipment_update(text):
            return True
        if re.fullmatch(
            r"(?:elegir|aceptar)(?: oferta)?\s+\d+",
            self._normalize_response_text(text),
        ):
            return True
        if self._is_producer_confirmation(text):
            return has_load_creation_context or has_producer_menu_context
        if self._looks_like_producer_self_service_command(text):
            return True
        if has_producer_menu_context:
            return True
        if carrier_shipment is not None:
            return False
        return False

    def _looks_like_explicit_carrier_load_response(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        if normalized in {
            "1",
            "2",
            "3",
            "si",
            "no",
            "me interesa",
            "1 me interesa",
            "2 no puedo",
            "3 mas info",
            "no puedo",
            "mas info",
            "lo hago",
            "paso",
            "dale",
        }:
            return True
        response_phrases = ("me interesa", "no puedo", "mas info", "lo hago", "paso")
        return any(self._contains_response_phrase(normalized, phrase) for phrase in response_phrases)

    def _looks_like_producer_self_service_command(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        if normalized in {
            "hola",
            "hi",
            "buen dia",
            "buenas",
            "menu",
            "menú",
            "que puedo hacer",
            "que opciones tengo",
            "crear carga",
            "editar",
            "edit",
            "ver mi carga",
            "ver mis cargas",
            "ver cargas",
            "mis cargas",
            "ver mi viaje",
            "mis viajes",
            "ver interesados",
            "soporte",
        }:
            return True
        return any(
            token in normalized
            for token in (
                "crear carga",
                "ver mi carga",
                "ver mis cargas",
                "ver cargas",
                "mis cargas",
                "ver mi viaje",
                "mis viajes",
                "ver interesados",
                "transportistas interesados",
            )
        )

    def _looks_like_producer_menu_choice(self, text: str, session: ConversationSession) -> bool:
        normalized = self._normalize_response_text(text)
        if normalized not in {"1", "2", "3", "4", "5"}:
            return False
        for message in reversed(self._recent_inbound_messages(session, limit=6)):
            raw = (message.raw_content or "").strip()
            if not raw:
                continue
            if self._looks_like_chat_shipment_request(raw) or self._looks_like_partial_chat_shipment_update(raw):
                return True
            if self._looks_like_producer_self_service_command(raw):
                return True
        return False

    def _session_has_load_creation_context(self, session: ConversationSession) -> bool:
        load_like_messages = self._session_load_messages(
            session,
            sender_types={"Producer", "Carrier"},
        )
        full_requests = [
            message
            for message in load_like_messages
            if self._looks_like_chat_shipment_request(message.raw_content or "")
        ]
        return bool(full_requests) or len(load_like_messages) >= 2

    def _recent_inbound_messages(self, session: ConversationSession, *, limit: int) -> list[Message]:
        session_messages = [
            message
            for message in self._messages.list()
            if message.conversation_session_id == session.id and message.direction == "inbound"
            and self._message_matches_test_run(message, session)
        ]
        session_messages.sort(key=lambda item: item.received_at or item.created_at)
        return session_messages[-limit:]

    def _detect_role_override_command(self, text: str) -> str | None:
        normalized = self._normalize_response_text(text)
        role_commands = {
            "Producer": {
                "/soy productor",
                "iniciar sesion productor",
                "iniciar sesion como productor",
                "modo productor",
                "soy productor",
            },
            "Carrier": {
                "/soy transportista",
                "/soy carrier",
                "iniciar sesion transportista",
                "iniciar sesion como transportista",
                "modo transportista",
                "soy transportista",
                "iniciar sesion carrier",
                "iniciar sesion como carrier",
                "modo carrier",
                "soy carrier",
            },
            "Operator": {
                "/soy operador",
                "iniciar sesion operador",
                "iniciar sesion como operador",
                "modo operador",
                "soy operador",
            },
        }
        clear_commands = {"/reset", "cerrar sesion", "salir modo", "modo automatico"}
        status_commands = {"/estado", "/estado sesion", "/estado session"}
        if normalized in status_commands:
            return "STATUS"
        if normalized in clear_commands:
            return "CLEAR"
        for role, commands in role_commands.items():
            if normalized in commands:
                return role
            if any(normalized.startswith(f"{command} ") for command in commands):
                return role
        return None

    def _detect_test_run_command(self, text: str) -> str | None:
        normalized = self._normalize_response_text(text)
        if normalized in {"/test iniciar", "/qa iniciar", "/test start"}:
            return "START"
        if normalized in {"/test cerrar", "/qa cerrar", "/test cerrar escenario", "/test stop"}:
            return "CLOSE"
        return None

    def _handle_test_run_command(
        self,
        *,
        command: str,
        inbound: InboundConversationMessage,
        session: ConversationSession,
    ) -> ConversationResult:
        if command == "START" and session.active_test_run_id:
            message = self._record_message(session, inbound, sender_type="User")
            events = [self._record_message_received(message, inbound)]
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text=(
                    f"Ya hay un escenario activo ({session.active_test_run_id}). "
                    "Cerralo con /test cerrar antes de iniciar otro."
                ),
                handoff_required=False,
                events=tuple(events),
            )

        if command == "START":
            session.active_test_run_id = f"qa_{uuid4().hex[:12]}"
            session.role_override = None
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            message = self._record_message(session, inbound, sender_type="User")
            event_type = "TEST_RUN_STARTED"
            response_text = f"Escenario de prueba iniciado: {session.active_test_run_id}."
            previous_state = None
            new_state = session.active_test_run_id
        else:
            test_run_id = session.active_test_run_id
            if test_run_id is None:
                message = self._record_message(session, inbound, sender_type="User")
                events = [self._record_message_received(message, inbound)]
                return ConversationResult(
                    conversation_session=session,
                    message=message,
                    shipment_request=None,
                    response_text="No hay un escenario de prueba activo.",
                    handoff_required=False,
                    events=tuple(events),
                )
            message = self._record_message(session, inbound, sender_type=session.role_override or "User")
            session.active_test_run_id = None
            session.role_override = None
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            event_type = "TEST_RUN_CLOSED"
            response_text = f"Escenario de prueba cerrado: {test_run_id}. El historial quedó preservado."
            previous_state = test_run_id
            new_state = None

        event = self._event_log.record(
            event_type=event_type,
            actor_type="User",
            entity_type="ConversationSession",
            entity_id=session.id,
            summary="Escenario de prueba iniciado" if command == "START" else "Escenario de prueba cerrado",
            related_entity_ids={"messageId": message.id, "conversationSessionId": session.id},
            previous_state=previous_state,
            new_state=new_state,
            payload={"test_run_id": new_state or previous_state},
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:test_run_{command.lower()}",
            test_run_id=new_state or previous_state,
        )
        if command == "CLOSE" and previous_state:
            if self._routing is not None:
                self._routing.close_run(previous_state)
            self._test_run_close_hook(previous_state)
        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=None,
            response_text=response_text,
            handoff_required=False,
            events=(self._record_message_received(message, inbound), event),
        )

    def _role_label(self, role: str | None) -> str:
        return {
            "Producer": "Productor",
            "Carrier": "Transportista",
            "Operator": "Operador",
        }.get(role or "", "Automático")

    def _build_session_status_response(
        self,
        *,
        session: ConversationSession,
        inbound: InboundConversationMessage,
        carrier: Carrier | None,
    ) -> str:
        phone = self._mask_phone(inbound.phone_number or session.normalized_phone_number)
        carrier_label = carrier.id if carrier is not None else "no"
        return "\n".join(
            [
                f"Modo actual: {self._role_label(session.role_override)}",
                f"Teléfono: {phone or 'sin dato'}",
                f"Carrier detectado: {carrier_label}",
            ]
        )

    def _record_session_role_status_requested(
        self,
        *,
        session: ConversationSession,
        message: Message,
        inbound: InboundConversationMessage,
        carrier: Carrier | None,
    ) -> EventLog:
        related_entity_ids = {
            "messageId": message.id,
            "conversationSessionId": session.id,
        }
        if carrier is not None:
            related_entity_ids["carrierId"] = carrier.id
        return self._event_log.record(
            event_type="SESSION_ROLE_STATUS_REQUESTED",
            actor_type=session.role_override or "User",
            actor_id=carrier.id if carrier is not None else None,
            entity_type="ConversationSession",
            entity_id=session.id,
            summary="Estado de modo de prueba consultado",
            related_entity_ids=related_entity_ids,
            payload={
                "role_override": session.role_override,
                "phone_number": self._mask_phone(inbound.phone_number or session.normalized_phone_number),
                "carrier_id": carrier.id if carrier is not None else None,
            },
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:role_status_requested",
        )

    def _apply_role_override_command(
        self,
        *,
        session: ConversationSession,
        message: Message,
        inbound: InboundConversationMessage,
        command: str,
    ) -> EventLog:
        previous_role = session.role_override
        if command == "CLEAR":
            session.role_override = None
            session.route_availability_capture = {}
            session.mark_updated()
            self._conversation_sessions.save(session)
            return self._event_log.record(
                event_type="SESSION_ROLE_OVERRIDE_CLEARED",
                actor_type=previous_role or "User",
                entity_type="ConversationSession",
                entity_id=session.id,
                summary="Modo de prueba de rol limpiado",
                related_entity_ids={
                    "messageId": message.id,
                    "conversationSessionId": session.id,
                },
                previous_state=previous_role,
                new_state=None,
                payload={"previous_role_override": previous_role},
                source=inbound.provider,
                correlation_id=inbound.correlation_id,
                idempotency_key=f"{inbound.idempotency_key}:role_override_cleared",
            )

        session.role_override = command
        session.route_availability_capture = {}
        session.mark_updated()
        self._conversation_sessions.save(session)
        return self._event_log.record(
            event_type="SESSION_ROLE_OVERRIDE_SET",
            actor_type=previous_role or "User",
            entity_type="ConversationSession",
            entity_id=session.id,
            summary="Modo de prueba de rol activado",
            related_entity_ids={
                "messageId": message.id,
                "conversationSessionId": session.id,
            },
            previous_state=previous_role,
            new_state=command,
            payload={"role_override": command, "previous_role_override": previous_role},
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:role_override_set",
        )

    def _latest_load_request_message_for_session(
        self,
        session: ConversationSession,
        *,
        current_message: Message,
    ) -> Message | None:
        session_messages = self._producer_load_messages_for_session(
            session,
            current_message=current_message,
        )
        if not session_messages:
            return None
        return session_messages[-1]

    def _producer_load_messages_for_session(
        self,
        session: ConversationSession,
        *,
        current_message: Message,
    ) -> list[Message]:
        session_messages = self._session_load_messages(
            session,
            current_message=current_message,
            sender_types={"Producer"},
        )
        if session_messages:
            return session_messages
        if session.active_test_run_id:
            return []
        return self._session_load_messages(
            session,
            current_message=current_message,
            sender_types={"Producer", "Carrier"},
        )

    def _session_load_messages(
        self,
        session: ConversationSession,
        *,
        current_message: Message | None = None,
        sender_types: set[str],
    ) -> list[Message]:
        session_messages = [
            message
            for message in self._messages.list()
            if message.conversation_session_id == session.id
            and (current_message is None or message.id != current_message.id)
            and message.direction == "inbound"
            and message.sender_type in sender_types
            and self._message_matches_test_run(message, session)
            and message.raw_content
            and not self._is_producer_confirmation(message.raw_content)
        ]
        session_messages.sort(key=lambda item: item.received_at or item.created_at)
        return [
            candidate
            for candidate in session_messages
            if self._looks_like_chat_shipment_request(candidate.raw_content or "")
            or self._looks_like_partial_chat_shipment_update(candidate.raw_content or "")
        ]

    def _message_matches_test_run(self, message: Message, session: ConversationSession) -> bool:
        active_test_run_id = session.active_test_run_id if self._enable_test_role_switching else None
        return message.test_run_id == active_test_run_id

    def _looks_like_chat_shipment_request(self, text: str) -> bool:
        parsed = self._parse_chat_shipment_text(text)
        if parsed.cargo_type is None and parsed.quantity_estimate is None:
            return False
        normalized = normalize_for_simple_parse(text)
        return any(
            token in normalized
            for token in ("camion", "carga", "transporte", "transportar", "trasladar", "llevar", "necesito")
        )

    def _looks_like_partial_chat_shipment_update(self, text: str) -> bool:
        normalized = normalize_for_simple_parse(text)
        response_normalized = self._normalize_response_text(text)
        parsed = self._parse_chat_shipment_text(text)
        if self._looks_like_explicit_carrier_load_response(text):
            return False
        has_non_numeric_load_signal = bool(
            parsed.cargo_type
            or parsed.quantity_unit
            or parsed.origin
            or parsed.destination
            or parsed.date_window_start is not None
            or any(token in normalized for token in ("desde", "hasta", "salimos", "junio", "julio", "manana", "mañana"))
        )
        if response_normalized.isdigit() and int(response_normalized) <= 5 and not has_non_numeric_load_signal:
            return False
        return bool(
            parsed.cargo_type
            or parsed.quantity_unit
            or parsed.quantity_estimate is not None
            or parsed.origin
            or parsed.destination
            or parsed.date_window_start is not None
            or any(token in normalized for token in ("desde", "hasta", "salimos", "junio", "julio", "manana", "mañana"))
        )

    def _combine_load_message_texts(self, messages: list[Message]) -> str:
        return " ".join(
            (message.raw_content or "").strip()
            for message in messages
            if (message.raw_content or "").strip()
        )

    def _parse_chat_shipment_from_messages(
        self,
        messages: list[Message],
        *,
        reference_datetime: datetime | None,
    ) -> ParsedChatShipment:
        aggregate = ParsedChatShipment(
            livestock_type=None,
            quantity_estimate=None,
            cargo_category=None,
            cargo_type=None,
            quantity_unit=None,
            origin=None,
            destination=None,
            date_window_start=None,
            date_window_end=None,
        )
        for message in messages:
            text = (message.raw_content or "").strip()
            if not text:
                continue
            candidate = self._parse_chat_shipment_text(text, reference_datetime=reference_datetime)
            aggregate = ParsedChatShipment(
                livestock_type=candidate.livestock_type or aggregate.livestock_type,
                quantity_estimate=(
                    candidate.quantity_estimate
                    if self._has_explicit_load_quantity(candidate)
                    else aggregate.quantity_estimate
                ),
                cargo_category=candidate.cargo_category or aggregate.cargo_category,
                cargo_type=candidate.cargo_type or aggregate.cargo_type,
                quantity_unit=candidate.quantity_unit or aggregate.quantity_unit,
                origin=candidate.origin or aggregate.origin,
                destination=candidate.destination or aggregate.destination,
                date_window_start=candidate.date_window_start or aggregate.date_window_start,
                date_window_end=candidate.date_window_end or aggregate.date_window_end,
                weight_per_head_kg=candidate.weight_per_head_kg or aggregate.weight_per_head_kg,
            )
        return aggregate

    def _build_chat_operational_notes(
        self,
        messages: list[Message],
        *,
        parsed: ParsedChatShipment,
        reference_datetime: datetime | None,
    ) -> str | None:
        cleaned_messages: list[str] = []
        for message in reversed(messages):
            text = (message.raw_content or "").strip()
            if not text:
                continue
            parsed_candidate = self._parse_chat_shipment_text(
                text,
                reference_datetime=reference_datetime,
            )
            if self._chat_shipment_candidate_conflicts(parsed_candidate, parsed):
                break
            cleaned_messages.append(text)

        if not cleaned_messages:
            return None
        cleaned_messages.reverse()
        return " ".join(cleaned_messages)

    def _chat_shipment_candidate_conflicts(
        self,
        candidate: ParsedChatShipment,
        final: ParsedChatShipment,
    ) -> bool:
        comparisons = (
            (candidate.origin, final.origin),
            (candidate.destination, final.destination),
            (candidate.cargo_type, final.cargo_type),
            (candidate.quantity_unit, final.quantity_unit),
            (candidate.weight_per_head_kg, final.weight_per_head_kg),
        )
        for current, expected in comparisons:
            if current and expected and current != expected:
                return True
        if (
            self._has_explicit_load_quantity(candidate)
            and candidate.quantity_estimate is not None
            and final.quantity_estimate is not None
            and candidate.quantity_estimate != final.quantity_estimate
        ):
            return True
        if (
            candidate.date_window_start is not None
            and final.date_window_start is not None
            and candidate.date_window_start != final.date_window_start
        ):
            return True
        return False

    def _has_explicit_load_quantity(self, candidate: ParsedChatShipment) -> bool:
        return candidate.quantity_estimate is not None and bool(
            candidate.cargo_type
            or candidate.livestock_type
            or candidate.cargo_category
            or (candidate.quantity_unit and candidate.quantity_unit != "HEAD")
        )

    def _can_self_publish_chat_shipment(self, parsed: ParsedChatShipment) -> bool:
        return (
            parsed.cargo_type is not None
            and parsed.quantity_estimate is not None
            and parsed.quantity_unit is not None
            and parsed.origin is not None
            and parsed.destination is not None
            and (parsed.date_window_start is not None or parsed.date_window_end is not None)
        )

    def _chat_missing_fields(self, parsed: ParsedChatShipment) -> list[str]:
        missing: list[str] = []
        if not parsed.origin:
            missing.append("origin")
        if not parsed.destination:
            missing.append("destination")
        if parsed.date_window_start is None and parsed.date_window_end is None:
            missing.append("date_window")
        if not parsed.cargo_type:
            missing.append("livestock_type")
        if parsed.quantity_estimate is None:
            missing.append("quantity_estimate")
        elif parsed.quantity_unit is None:
            missing.append("quantity_unit")
        return missing

    def _chat_field_confidence(self, parsed: ParsedChatShipment) -> dict[str, str]:
        return {
            "origin": "provided" if parsed.origin else "missing",
            "destination": "provided" if parsed.destination else "missing",
            "date_window": "provided" if parsed.date_window_start or parsed.date_window_end else "missing",
            "livestock_type": "provided" if parsed.cargo_type else "missing",
            "quantity_estimate": "provided" if parsed.quantity_estimate is not None else "missing",
            "quantity_unit": "provided" if parsed.quantity_unit else "missing",
            "weight_per_head_kg": "provided" if parsed.weight_per_head_kg is not None else "missing",
        }

    def _eligible_carrier_ids(self, test_phone_number: str | None = None) -> list[str]:
        if self._carriers is None:
            return []
        carriers = [
            carrier
            for carrier in self._carriers.list()
            if carrier.is_validated
            and (
                carrier.normalized_phone_number
                or carrier.contact_phone
                or carrier.provider_contact_id
                or carrier.provider_conversation_id
            )
        ]
        carriers.sort(key=lambda carrier: carrier.created_at)
        if current_test_run_id.get():
            test_phone = self._safe_normalize_phone_number(test_phone_number)
            carriers = [
                carrier
                for carrier in carriers
                if test_phone
                and test_phone
                in {
                    self._safe_normalize_phone_number(carrier.normalized_phone_number),
                    self._safe_normalize_phone_number(carrier.contact_phone),
                }
            ]
        return [carrier.id for carrier in carriers]

    def _shipment_from_chat_draft_event(self, idempotency_key: str) -> ShipmentRequest | None:
        for event in self._event_log.events:
            if (
                event.event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"
                and event.idempotency_key == idempotency_key
            ):
                return self._shipment_requests.get(event.entity_id)
        return None

    def record_webhook_processing_failed(
        self,
        *,
        provider: str,
        idempotency_key: str,
        correlation_id: str,
        provider_message_id: str | None = None,
    ) -> EventLog:
        return self._event_log.record(
            event_type="WEBHOOK_PROCESSING_FAILED",
            actor_type="System",
            entity_type="WebhookEvent",
            entity_id=idempotency_key,
            summary="Fallo procesable al recibir webhook de canal",
            payload={"provider": provider, "provider_message_id": provider_message_id},
            source=provider,
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}:processing_failed",
        )

    def _handle_carrier_response(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        carrier: Carrier,
        text: str,
        events: list[EventLog],
    ) -> ConversationResult:
        classification = self._classify_carrier_response(text)
        if self._looks_like_operator_command(text):
            events.append(
                self._record_operator_command_routed_to_kapso(
                    message=message,
                    inbound=inbound,
                    session=session,
                    carrier=carrier,
                    text=text,
                )
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text=None,
                handoff_required=False,
                events=tuple(events),
            )

        if (
            classification in {"AMBIGUOUS", "INFO_REQUEST"}
            and self._looks_like_carrier_availability_report(text)
        ):
            events.append(
                self._record_carrier_availability_reported(
                    carrier=carrier,
                    message=message,
                    inbound=inbound,
                    session=session,
                    text=text,
                )
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="Disponibilidad registrada. Un operador la revisa para futuras cargas.",
                handoff_required=False,
                events=tuple(events),
            )

        if classification == "INFO_REQUEST":
            shipment = self._resolve_shipment_for_carrier_response(carrier, session, inbound)
            if shipment is not None:
                return ConversationResult(
                    conversation_session=session,
                    message=message,
                    shipment_request=shipment,
                    response_text=self._format_carrier_shipment(shipment),
                    handoff_required=False,
                    events=tuple(events),
                )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="No pude identificar una carga para ampliar. Respondé «ver carga recibida» o pedí soporte.",
                handoff_required=False,
                events=tuple(events),
            )

        explicit_shipment_id = self._extract_shipment_id_from_text(inbound.text)
        shipment = self._resolve_shipment_for_carrier_response(carrier, session, inbound)
        if shipment is None:
            events.append(
                self._record_human_review_requested(
                    message,
                    inbound,
                    "No se pudo resolver la carga relacionada con la respuesta del transportista",
                )
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=None,
                response_text="Recibimos la respuesta. Un operador la revisa.",
                handoff_required=True,
                events=tuple(events),
            )

        if classification == "AMBIGUOUS":
            events.append(
                self._event_log.record(
                    event_type="CARRIER_RESPONSE_AMBIGUOUS",
                    actor_type="Carrier",
                    actor_id=carrier.id,
                    entity_type="LivestockLoad",
                    entity_id=shipment.id,
                    summary="Respuesta ambigua de transportista",
                    related_entity_ids={
                        "carrierId": carrier.id,
                        "loadId": shipment.id,
                        "messageId": message.id,
                        "conversationSessionId": session.id,
                    },
                    payload={"text": text},
                    source=inbound.provider,
                    correlation_id=inbound.correlation_id,
                    idempotency_key=f"{inbound.idempotency_key}:carrier_response_ambiguous",
                )
            )
            events.append(
                self._record_human_review_requested(
                    message,
                    inbound,
                    "Respuesta de transportista requiere interpretacion humana",
                    shipment,
                )
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=shipment,
                response_text="Recibimos la respuesta. Un operador la revisa.",
                handoff_required=True,
                events=tuple(events),
            )

        existing_offer = self._find_existing_trip_offer(
            shipment=shipment,
            carrier=carrier,
            response_type=classification,
        )
        if existing_offer is not None:
            disambiguation_hint = self._build_carrier_disambiguation_hint(
                carrier=carrier,
                shipment=shipment,
                classification=classification,
                explicit_shipment_id=explicit_shipment_id,
            )
            return ConversationResult(
                conversation_session=session,
                message=message,
                shipment_request=shipment,
                response_text=disambiguation_hint or self._carrier_response_ack(classification, duplicate=True),
                handoff_required=False,
                events=tuple(events),
            )

        offer = self._create_trip_offer(
            shipment=shipment,
            carrier=carrier,
            message=message,
            response_type=classification,
        )
        event_type = "CARRIER_INTERESTED" if classification == "INTERESTED" else "CARRIER_DECLINED"
        events.append(
            self._event_log.record(
                event_type=event_type,
                actor_type="Carrier",
                actor_id=carrier.id,
                entity_type="Offer",
                entity_id=offer.id,
                summary="Respuesta de transportista registrada",
                related_entity_ids={
                    "carrierId": carrier.id,
                    "loadId": shipment.id,
                    "offerId": offer.id,
                    "messageId": message.id,
                    "conversationSessionId": session.id,
                },
                payload={"text": text, "response_type": classification},
                source=inbound.provider,
                correlation_id=inbound.correlation_id,
                idempotency_key=f"{inbound.idempotency_key}:carrier_response",
            )
        )
        matching_event = self._start_matching_if_first_interested_offer(
            shipment=shipment,
            offer=offer,
            carrier=carrier,
            inbound=inbound,
        )
        if matching_event is not None:
            events.append(matching_event)
        return ConversationResult(
            conversation_session=session,
            message=message,
            shipment_request=shipment,
            trip_offer=offer,
            response_text=self._build_carrier_disambiguation_hint(
                carrier=carrier,
                shipment=shipment,
                classification=classification,
                explicit_shipment_id=explicit_shipment_id,
            ) or self._carrier_response_ack(classification),
            handoff_required=False,
            events=tuple(events),
        )

    def _carrier_response_ack(self, classification: str, *, duplicate: bool = False) -> str:
        if classification == "INTERESTED":
            if duplicate:
                return "Ya había registrado tu interés por esta carga. El productor puede verlo y confirmar el viaje."
            return "Listo, registré tu interés. El productor puede verlo y confirmar el viaje."
        if classification == "DECLINED":
            return "Anoté que no podés tomar esta carga. Gracias por responder."
        return "Recibido."

    def _start_matching_if_first_interested_offer(
        self,
        *,
        shipment: ShipmentRequest,
        offer: TripOffer,
        carrier: Carrier,
        inbound: InboundConversationMessage,
    ) -> EventLog | None:
        if offer.response_type != "INTERESTED" or shipment.status != "PUBLISHED":
            return None
        event = self._transitions.transition(
            entity_type="ShipmentRequest",
            entity_id=shipment.id,
            from_state=shipment.status,
            event_type="LOAD_MATCHING_STARTED",
            to_state="MATCHING",
            actor_type="Carrier",
            actor_id=carrier.id,
            summary="Matching iniciado por interes de transportista",
            related_entity_ids={
                "carrierId": carrier.id,
                "loadId": shipment.id,
                "offerId": offer.id,
            },
            payload={
                "shipment_request_id": shipment.id,
                "trigger": "carrier_interested",
                "trip_offer_id": offer.id,
            },
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"shipment:{shipment.id}:matching_started",
        )
        shipment.status = event.new_state or shipment.status
        self._shipment_requests.save(shipment)
        return event

    def _classify_carrier_response(self, text: str) -> str:
        normalized = self._normalize_response_text(text)
        if normalized in {"mas info", "mas informacion", "mas detalles", "detalle", "detalles"}:
            return "INFO_REQUEST"
        ambiguous_tokens = (
            "puede ser",
            "depende",
            "precio?",
            "precio",
            "cuanto pagan?",
            "cuanto pagan",
        )
        # The text fallback shown to carriers numbers "Más info" as option 3.
        # Keep this aligned with the interactive action and the WhatsApp copy.
        info_tokens = (
            "3", "4", "mas info", "mas informacion", "mas detalles", "detalle", "detalles",
            "more_info", "more info",
        )
        declined_tokens = ("2", "no", "no puedo", "paso", "declined")
        interested_tokens = ("1", "si", "me interesa", "lo hago", "dale", "interested")
        if normalized in ambiguous_tokens or any(self._contains_response_phrase(normalized, token) for token in ambiguous_tokens if token not in {"3", "mas info"}):
            return "AMBIGUOUS"
        if normalized in declined_tokens or any(self._contains_response_phrase(normalized, token) for token in declined_tokens if token != "2"):
            return "DECLINED"
        if normalized in info_tokens:
            return "INFO_REQUEST"
        if normalized in interested_tokens or any(self._contains_response_phrase(normalized, token) for token in interested_tokens if token != "1"):
            return "INTERESTED"
        return "AMBIGUOUS"

    def _contains_response_phrase(self, normalized_text: str, phrase: str) -> bool:
        return normalized_text == phrase or normalized_text.startswith(f"{phrase} ") or normalized_text.endswith(f" {phrase}")

    def _normalize_response_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.strip().lower())
        without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
        return " ".join(without_accents.split())

    def _looks_like_carrier_availability_report(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        availability_tokens = (
            "disponibilidad",
            "disponible",
            "libre",
            "vacio",
            "vacia",
            "voy vacio",
            "tengo jaula",
            "jaula disponible",
            "zona",
        )
        return any(token in normalized for token in availability_tokens)

    def _looks_like_operator_command(self, text: str) -> bool:
        normalized = self._normalize_response_text(text)
        command_tokens = (
            "ver cargas",
            "ver mis cargas",
            "ver borradores",
            "validar sr_",
            "publicar sr_",
            "seleccionar oferta",
            "elegir oferta",
        )
        return any(token in normalized for token in command_tokens)

    def _record_operator_command_routed_to_kapso(
        self,
        *,
        message: Message,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        carrier: Carrier | None,
        text: str,
    ) -> EventLog:
        related_entity_ids = {
            "messageId": message.id,
            "conversationSessionId": session.id,
        }
        if carrier is not None:
            related_entity_ids["carrierId"] = carrier.id
        return self._event_log.record(
            event_type="OPERATOR_COMMAND_ROUTED_TO_KAPSO",
            actor_type="Operator",
            entity_type="Message",
            entity_id=message.id,
            summary="Comando operativo recibido por WhatsApp y manejado por Kapso",
            related_entity_ids=related_entity_ids,
            payload={"text": text},
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:operator_command_routed",
        )

    def _record_carrier_availability_reported(
        self,
        *,
        carrier: Carrier,
        message: Message,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        text: str,
    ) -> EventLog:
        previous_notes = carrier.availability_notes
        carrier.availability_notes = text
        carrier.last_inbound_at = inbound.occurred_at
        if self._carriers is not None:
            self._carriers.save(carrier)
        return self._event_log.record(
            event_type="CARRIER_AVAILABILITY_REPORTED",
            actor_type="Carrier",
            actor_id=carrier.id,
            entity_type="Carrier",
            entity_id=carrier.id,
            summary="Disponibilidad general reportada por transportista",
            related_entity_ids={
                "carrierId": carrier.id,
                "messageId": message.id,
                "conversationSessionId": session.id,
            },
            previous_state=None,
            new_state=None,
            payload={
                "text": text,
                "previous_availability_notes": previous_notes,
                "source": inbound.provider,
            },
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:carrier_availability_reported",
        )

    def _resolve_carrier(self, inbound: InboundConversationMessage) -> Carrier | None:
        normalized_phone = self._safe_normalize_phone_number(inbound.phone_number)
        candidates = self._phone_lookup_candidates(normalized_phone)
        carrier = self._find_carrier_by_phone_candidates(candidates) if self._carriers is not None else None
        logger.info(
            "carrier_phone_lookup_attempt inbound_raw=%s normalized_phone=%s matched=%s",
            self._mask_phone(inbound.phone_number),
            self._mask_phone(normalized_phone),
            str(carrier is not None).lower(),
        )
        return carrier

    def _find_carrier_by_phone_candidates(self, candidates: set[str]) -> Carrier | None:
        if self._carriers is None:
            return None
        if not candidates:
            return None
        for carrier in self._carriers.list():
            carrier_candidates = self._phone_lookup_candidates(carrier.normalized_phone_number)
            carrier_contact_phone = self._safe_normalize_phone_number(carrier.contact_phone)
            carrier_candidates.update(self._phone_lookup_candidates(carrier_contact_phone))
            if carrier_candidates.intersection(candidates):
                return carrier
        return None

    def _phone_lookup_candidates(self, normalized_phone: str | None) -> set[str]:
        if not normalized_phone:
            return set()
        candidates = {normalized_phone}
        digits = normalized_phone[1:] if normalized_phone.startswith("+") else normalized_phone
        if digits.startswith("549") and len(digits) >= 6:
            candidates.add(f"+54{digits[3:]}")
        if digits.startswith("54") and not digits.startswith("549") and len(digits) >= 5:
            national = digits[2:]
            if national.startswith("11") and len(national) == 10:
                candidates.add(f"+549{national}")
        return candidates

    def _mask_phone(self, phone_number: str | None) -> str | None:
        if not phone_number:
            return None
        digits = "".join(character for character in phone_number if character.isdigit())
        if len(digits) <= 4:
            return "***"
        prefix = "+" if phone_number.strip().startswith("+") else ""
        return f"{prefix}{digits[:3]}***{digits[-3:]}"

    def _resolve_shipment_for_carrier_response(
        self,
        carrier: Carrier,
        session: ConversationSession,
        inbound: InboundConversationMessage,
    ) -> ShipmentRequest | None:
        explicit_shipment_id = self._extract_shipment_id_from_text(inbound.text)
        if explicit_shipment_id:
            shipment = self._shipment_requests.get(explicit_shipment_id)
            if (
                shipment is not None
                and shipment.test_run_id == session.active_test_run_id
                and shipment.status in {"PUBLISHED", "MATCHING"}
            ):
                return shipment

        for event in reversed(sorted(self._event_log.events, key=lambda item: item.occurred_at)):
            if event.event_type != "CARRIER_NOTIFICATION_SENT":
                continue
            if event.test_run_id != current_test_run_id.get():
                continue
            if event.test_run_id != session.active_test_run_id:
                continue
            if event.related_entity_ids.get("carrierId") != carrier.id:
                continue
            payload = event.payload
            load_id = str(payload.get("shipment_request_id") or event.entity_id)
            shipment = self._shipment_requests.get(load_id)
            if (
                shipment is not None
                and shipment.test_run_id == session.active_test_run_id
                and shipment.status in {"PUBLISHED", "MATCHING"}
            ):
                return shipment

        shipment_id = self._shipment_id_from_correlation(inbound.correlation_id)
        if shipment_id:
            shipment = self._shipment_requests.get(shipment_id)
            if (
                shipment is not None
                and shipment.test_run_id == session.active_test_run_id
                and shipment.status in {"PUBLISHED", "MATCHING"}
            ):
                return shipment
        return None

    def _build_carrier_disambiguation_hint(
        self,
        *,
        carrier: Carrier,
        shipment: ShipmentRequest,
        classification: str,
        explicit_shipment_id: str | None,
    ) -> str | None:
        if classification != "INTERESTED" or explicit_shipment_id is not None:
            return None
        if len(self._active_notified_shipments_for_carrier(carrier)) <= 1:
            return None
        return (
            f"Recibido, marcamos tu interés por la última carga enviada ({shipment.id}). "
            'Si querías una anterior, respondé "me interesa sr_...".'
        )

    def _active_notified_shipments_for_carrier(self, carrier: Carrier) -> list[ShipmentRequest]:
        seen: set[str] = set()
        active_shipments: list[ShipmentRequest] = []
        for event in reversed(sorted(self._event_log.events, key=lambda item: item.occurred_at)):
            if event.event_type != "CARRIER_NOTIFICATION_SENT":
                continue
            if event.test_run_id != current_test_run_id.get():
                continue
            if event.related_entity_ids.get("carrierId") != carrier.id:
                continue
            load_id = str(event.payload.get("shipment_request_id") or event.entity_id)
            if load_id in seen:
                continue
            seen.add(load_id)
            shipment = self._shipment_requests.get(load_id)
            if (
                shipment is not None
                and shipment.test_run_id == current_test_run_id.get()
                and shipment.status in {"PUBLISHED", "MATCHING"}
            ):
                active_shipments.append(shipment)
        return active_shipments

    def _extract_shipment_id_from_text(self, text: str | None) -> str | None:
        if not text:
            return None
        match = SHIPMENT_ID_PATTERN.search(text)
        if match is None:
            return None
        return match.group(1).lower()

    def _shipment_id_from_correlation(self, correlation_id: str | None) -> str | None:
        if not correlation_id:
            return None
        if correlation_id.startswith("shipment:"):
            parts = correlation_id.split(":")
            if len(parts) >= 2:
                return parts[1]
        return None

    def _create_trip_offer(
        self,
        *,
        shipment: ShipmentRequest,
        carrier: Carrier,
        message: Message,
        response_type: str,
    ) -> TripOffer:
        if self._trip_offers is None:
            raise RuntimeError("Trip offer repository is not configured")
        offer = TripOffer(
            shipment_request_id=shipment.id,
            carrier_id=carrier.id,
            test_run_id=shipment.test_run_id,
            response_type=response_type,
            source_message_id=message.id,
            status="RECEIVED",
            confidence="provided",
            requires_human_review=False,
        )
        return self._trip_offers.add(offer)

    def _find_existing_trip_offer(
        self,
        *,
        shipment: ShipmentRequest,
        carrier: Carrier,
        response_type: str,
    ) -> TripOffer | None:
        if self._trip_offers is None:
            raise RuntimeError("Trip offer repository is not configured")
        matching_offers = [
            offer
            for offer in self._trip_offers.list()
            if offer.shipment_request_id == shipment.id
            and offer.carrier_id == carrier.id
            and offer.response_type == response_type
        ]
        if not matching_offers:
            return None
        return max(matching_offers, key=lambda offer: offer.created_at)

    def _get_or_create_session(self, inbound: InboundConversationMessage) -> ConversationSession:
        normalized_phone = self._safe_normalize_phone_number(inbound.phone_number)
        for session in self._conversation_sessions.list():
            if (
                inbound.conversation_id
                and (
                    session.provider_conversation_id == inbound.conversation_id
                    or session.external_conversation_id == inbound.conversation_id
                )
                and session.channel == inbound.provider
            ) or (
                inbound.provider_contact_id
                and session.provider_contact_id == inbound.provider_contact_id
                and session.channel == inbound.provider
            ) or (
                normalized_phone
                and session.normalized_phone_number == normalized_phone
                and session.channel == inbound.provider
            ):
                session.last_message_at = inbound.occurred_at
                session.last_inbound_at = inbound.occurred_at
                session.provider_name = inbound.provider
                session.provider_contact_id = inbound.provider_contact_id or session.provider_contact_id
                session.provider_conversation_id = inbound.conversation_id or session.provider_conversation_id
                session.workflow_execution_id = inbound.workflow_execution_id or session.workflow_execution_id
                session.participant_phone = inbound.phone_number or session.participant_phone
                session.normalized_phone_number = normalized_phone or session.normalized_phone_number
                return self._conversation_sessions.save(session)

        session = ConversationSession(
            channel=inbound.provider,
            external_conversation_id=inbound.conversation_id,
            provider_name=inbound.provider,
            provider_contact_id=inbound.provider_contact_id,
            provider_conversation_id=inbound.conversation_id,
            workflow_execution_id=inbound.workflow_execution_id,
            participant_phone=inbound.phone_number,
            normalized_phone_number=normalized_phone,
            last_message_at=inbound.occurred_at,
            last_inbound_at=inbound.occurred_at,
        )
        return self._conversation_sessions.add(session)

    def _safe_normalize_phone_number(self, phone_number: str | None) -> str | None:
        try:
            return normalize_phone_number(phone_number)
        except PhoneNormalizationError:
            return None

    def _find_message_by_idempotency_key(self, idempotency_key: str) -> Message | None:
        for message in self._messages.list():
            if message.idempotency_key == idempotency_key:
                return message
        return None

    def _record_message(
        self,
        session: ConversationSession,
        inbound: InboundConversationMessage,
        sender_type: str = "Producer",
    ) -> Message:
        message = Message(
            conversation_session_id=session.id,
            provider=inbound.provider,
            direction="inbound",
            sender_type=sender_type,
            message_type=self._message_type_for_inbound(inbound),
            provider_message_id=inbound.provider_message_id,
            idempotency_key=inbound.idempotency_key,
            test_run_id=session.active_test_run_id if self._enable_test_role_switching else None,
            related_entity_ids=(
                {"testRunId": session.active_test_run_id, "qaRole": sender_type}
                if self._enable_test_role_switching and session.active_test_run_id
                else {}
            ),
            raw_content=inbound.text,
            normalized_content="📍 Ubicación compartida" if inbound.location is not None else (inbound.text or "").strip() or None,
            received_at=inbound.occurred_at,
            correlation_id=inbound.correlation_id,
        )
        return self._messages.add(message)

    def _resolve_inbound_action_selection(
        self,
        *,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        message: Message,
        carrier: Carrier | None,
        text: str,
    ) -> InboundActionSelection | None:
        selection = inbound.action_selection
        if selection is None:
            selection = self._match_text_to_recent_action(
                carrier=carrier,
                session=session,
                text=text,
            )
        if selection is not None and inbound.action_selection is not None:
            # Provider replies normally include an action id only. Resolve it
            # against the latest action set actually accepted for this chat,
            # so stale or fabricated buttons cannot become domain commands.
            resolved = self._resolve_sent_action(
                selection_id=selection.id,
                session=session,
                carrier=carrier,
            )
            if resolved is None:
                return None
            selection = InboundActionSelection(
                id=selection.id,
                value=resolved.get("value", selection.id),
                label=resolved.get("label") or selection.label,
                raw=resolved,
            )
        if selection is None:
            return None

        message.normalized_content = selection.value
        message.related_entity_ids = {
            **message.related_entity_ids,
            "interactiveActionId": selection.id,
        }
        self._messages.save(message)
        return selection

    def _resolve_sent_action(
        self,
        *,
        selection_id: str,
        session: ConversationSession,
        carrier: Carrier | None,
    ) -> dict | None:
        for event in reversed(sorted(self._event_log.events, key=lambda item: item.occurred_at)):
            if event.test_run_id != session.active_test_run_id:
                continue
            event_role = event.related_entity_ids.get("qaRole")
            if event_role and event_role != session.role_override:
                continue
            if event.event_type == "CONVERSATION_REPLY_SENT" and event.entity_id == session.id:
                actions = event.payload.get("interactive_actions")
            elif carrier is not None and event.event_type == "CARRIER_NOTIFICATION_SENT" and event.related_entity_ids.get("carrierId") == carrier.id:
                actions = event.payload.get("interactive_actions")
            else:
                continue
            if not isinstance(actions, list):
                return None
            for action in actions:
                if isinstance(action, dict) and str(action.get("id")) == selection_id:
                    return action
            # Only the newest outbound action set is valid for this role/chat.
            return None
        return None

    def _match_text_to_recent_action(
        self,
        *,
        carrier: Carrier | None,
        session: ConversationSession,
        text: str,
    ) -> InboundActionSelection | None:
        normalized = self._normalize_response_text(text)
        if not normalized:
            return None
        for event in reversed(sorted(self._event_log.events, key=lambda item: item.occurred_at)):
            if event.test_run_id != session.active_test_run_id:
                continue
            event_role = event.related_entity_ids.get("qaRole")
            if event_role and event_role != session.role_override:
                continue
            is_conversation_reply = (
                event.event_type == "CONVERSATION_REPLY_SENT"
                and event.entity_id == session.id
            )
            is_carrier_notification = (
                carrier is not None
                and event.event_type == "CARRIER_NOTIFICATION_SENT"
                and event.related_entity_ids.get("carrierId") == carrier.id
            )
            if not is_conversation_reply and not is_carrier_notification:
                continue
            actions = event.payload.get("interactive_actions")
            if not isinstance(actions, list):
                return None
            for index, action in enumerate(actions, start=1):
                if not isinstance(action, dict):
                    continue
                action_id = str(action.get("id") or "")
                value = str(action.get("value") or action_id)
                label = str(action.get("label") or "")
                candidates = {
                    str(index),
                    self._normalize_response_text(action_id),
                    self._normalize_response_text(value),
                    self._normalize_response_text(label),
                    " ".join(re.sub(r"[^a-z0-9]+", " ", self._normalize_response_text(label)).split()),
                }
                if normalized in candidates:
                    return InboundActionSelection(id=action_id, value=value, label=label, raw=action)
            return None
        return None

    def _message_type_for_inbound(self, inbound: InboundConversationMessage) -> str:
        if inbound.location is not None:
            return "location"
        if inbound.media is None:
            return "text"
        if inbound.media.media_type in {"image", "audio", "document", "video"}:
            return inbound.media.media_type
        return "unknown"

    def _create_shipment_request(
        self,
        *,
        extraction: LoadDataExtraction,
        message: Message,
        missing_fields: list[str],
        requires_human_review: bool,
    ) -> ShipmentRequest:
        origin_location_id, ambiguous_origin = self._create_location(
            extraction.origin,
            extraction.field_confidence.get("origin"),
        )
        destination_location_id, ambiguous_destination = self._create_location(
            extraction.destination,
            extraction.field_confidence.get("destination"),
        )
        has_ambiguous_location = (
            extraction.has_ambiguous_location or ambiguous_origin or ambiguous_destination
        )
        status = "INCOMPLETE" if missing_fields else "PENDING_OPERATOR_REVIEW"
        cargo_type = extraction.cargo_type or extraction.livestock_type
        livestock_type = extraction.livestock_type
        if not livestock_type and extraction.cargo_category == "LIVESTOCK":
            livestock_type = cargo_type
        cargo_category = extraction.cargo_category or ("LIVESTOCK" if livestock_type else None)
        shipment_request = ShipmentRequest(
            origin_location_id=origin_location_id,
            destination_location_id=destination_location_id,
            date_window_start=extraction.date_window_start,
            date_window_end=extraction.date_window_end,
            cargo_category=cargo_category,
            cargo_type=cargo_type,
            quantity_unit=extraction.quantity_unit,
            livestock_type=livestock_type,
            quantity_estimate=extraction.quantity_estimate,
            operational_notes=self._build_operational_notes(extraction),
            status=status,
            field_confidence=extraction.field_confidence,
            missing_critical_fields=missing_fields,
            requires_human_review=requires_human_review or has_ambiguous_location,
            has_ambiguous_location=has_ambiguous_location,
            has_estimated_values=self._has_estimated_values(extraction),
            source_message_id=message.id,
            test_run_id=current_test_run_id.get(),
        )
        return self._shipment_requests.add(shipment_request)

    def _parse_chat_shipment_text(
        self,
        text: str,
        *,
        reference_datetime: datetime | None = None,
    ) -> ParsedChatShipment:
        return parse_chat_shipment_text(
            text,
            reference_datetime=reference_datetime,
            cargo_categories=self._cargo_categories,
            cargo_types=self._cargo_types,
        )

    def _create_location(self, original_text: str | None, confidence: str | None) -> tuple[str | None, bool]:
        if not original_text:
            return None, False
        resolution = (
            resolve_catalog_locality(original_text, self._geography_catalog)
            if self._geography_catalog is not None
            else resolve_argentine_locality(original_text)
        )
        locality = resolution.locality
        is_ambiguous = resolution.status == "AMBIGUOUS"
        location = Location(
            original_text=original_text,
            normalized_name=locality.name if locality else None,
            province=locality.province if locality else None,
            locality=locality.name if locality else None,
            georef_id=locality.georef_id if locality else None,
            catalog_version=resolution.catalog_version if locality else None,
            provenance="GEOREF" if locality else "USER_DECLARED",
            confidence="catalog_exact" if locality else ("ambiguous" if is_ambiguous else confidence or "unknown"),
            is_validated=False,
        )
        return self._locations.add(location).id, is_ambiguous

    def _detect_missing_fields(self, extraction: LoadDataExtraction) -> list[str]:
        missing: list[str] = []
        if not extraction.origin:
            missing.append("origin")
        if not extraction.destination:
            missing.append("destination")
        if not extraction.date_window_start and not extraction.date_window_end:
            missing.append("date_window")
        if not (extraction.cargo_type or extraction.livestock_type):
            missing.append("livestock_type")
        if extraction.quantity_estimate is None:
            missing.append("quantity_estimate")
        elif not extraction.quantity_unit:
            missing.append("quantity_unit")
        if not extraction.contact:
            missing.append("contact")
        return missing

    def _canonicalize_extraction(
        self,
        extraction: LoadDataExtraction,
        reference_datetime: datetime | None,
    ) -> LoadDataExtraction:
        parsed = self._parse_chat_shipment_text(
            extraction.raw_text,
            reference_datetime=reference_datetime,
        )
        cargo_category = normalize_cargo_category(
            parsed.cargo_category or extraction.cargo_category, self._cargo_categories
        )
        declared_cargo_type = parsed.cargo_type or extraction.cargo_type or extraction.livestock_type
        canonical_cargo_type = normalize_cargo_type(
            declared_cargo_type, cargo_category, self._cargo_types, self._cargo_categories
        )
        unknown_cargo_type = bool(cargo_category and declared_cargo_type and canonical_cargo_type is None)
        cargo_type = canonical_cargo_type or declared_cargo_type
        livestock_type = parsed.livestock_type or extraction.livestock_type
        if not livestock_type and cargo_category == "LIVESTOCK":
            livestock_type = cargo_type
        # Only a unit expressed in the source message may become canonical.
        quantity_unit = normalize_quantity_unit(parsed.quantity_unit)
        return replace(
            extraction,
            cargo_category=cargo_category,
            cargo_type=cargo_type,
            confidence="unknown" if unknown_cargo_type else extraction.confidence,
            field_confidence=(
                {**extraction.field_confidence, "cargo_type": "unknown"}
                if unknown_cargo_type
                else extraction.field_confidence
            ),
            quantity_unit=quantity_unit,
            livestock_type=livestock_type,
            quantity_estimate=parsed.quantity_estimate or extraction.quantity_estimate,
            weight_per_head_kg=parsed.weight_per_head_kg or extraction.weight_per_head_kg,
            origin=parsed.origin or extraction.origin,
            destination=parsed.destination or extraction.destination,
            date_window_start=parsed.date_window_start or extraction.date_window_start,
            date_window_end=parsed.date_window_end or extraction.date_window_end,
        )

    def _build_operational_notes(self, extraction: LoadDataExtraction) -> str:
        parts = [f"Texto original: {extraction.raw_text}"]
        if extraction.contact:
            parts.append(f"Contacto informado: {extraction.contact}")
        return " | ".join(parts)

    def _has_estimated_values(self, extraction: LoadDataExtraction) -> bool:
        return any(value == "estimated" for value in extraction.field_confidence.values())

    def _build_response_text(
        self,
        missing_fields: list[str],
        requires_human_review: bool,
        *,
        extraction: LoadDataExtraction,
    ) -> str | None:
        if missing_fields:
            field_name = missing_fields[0]
            return f"Para crear la carga, necesito confirmar {self._field_label(field_name)}. ¿Me lo indicás?"
        if requires_human_review:
            return "Hay un dato de la carga que no pude interpretar con seguridad. ¿Podés aclararlo o pedir soporte?"
        origin = extraction.origin or "No informado"
        destination = extraction.destination or "No informado"
        cargo = extraction.cargo_type or extraction.livestock_type or "No informado"
        quantity = self._quantity_label(
            extraction.quantity_estimate,
            extraction.quantity_unit,
        )
        quantity_label = (
            "⚖️ Peso total"
            if extraction.cargo_category == "GRAIN"
            and extraction.quantity_unit in {"TON", "KG"}
            else "• Cantidad"
        )
        weight_line = (
            f"\n⚖️ Pesaje: {self._quantity_label(extraction.weight_per_head_kg, 'KG')} por cabeza"
            if extraction.weight_per_head_kg is not None
            else ""
        )
        date = extraction.date_window_start
        date_label = (
            date.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d/%m/%Y")
            if date
            else "No informada"
        )
        return (
            "Para crear la carga, confirmá estos datos:\n\n"
            f"📦 Tipo de carga: {cargo}\n{quantity_label}: {quantity}{weight_line}\n📍 Origen: {origin}\n"
            f"📍 Destino: {destination}\n📅 Fecha: {date_label}\n\n"
            "✅ ¿Confirmás esta información?"
        )

    def _field_label(self, field_name: str) -> str:
        labels = {
            "origin": "origen",
            "destination": "destino",
            "date_window": "fecha u horario",
            "livestock_type": "tipo de carga",
            "quantity_estimate": "cantidad estimada",
            "quantity_unit": "unidad de cantidad (cabezas, toneladas, kg o camiones)",
            "contact": "contacto",
        }
        return labels.get(field_name, field_name)

    def _human_review_reason(
        self,
        missing_fields: list[str],
        extraction: LoadDataExtraction,
    ) -> str:
        reasons: list[str] = []
        if missing_fields:
            reasons.append(f"Faltan campos criticos: {', '.join(missing_fields)}")
        if extraction.has_ambiguous_location:
            reasons.append("Ubicacion ambigua")
        if extraction.confidence in {"unknown", "low"}:
            reasons.append(f"Confianza baja: {extraction.confidence}")
        return "; ".join(reasons) or "Revision humana requerida"

    def _record_message_received(
        self,
        message: Message,
        inbound: InboundConversationMessage,
    ) -> EventLog:
        return self._event_log.record(
            event_type="MESSAGE_RECEIVED",
            actor_type=message.sender_type,
            entity_type="Message",
            entity_id=message.id,
            summary="Mensaje entrante registrado",
            related_entity_ids={
                "conversationSessionId": message.conversation_session_id,
                **({"testRunId": message.test_run_id} if message.test_run_id else {}),
            },
            payload={
                "provider": inbound.provider,
                "provider_message_id": inbound.provider_message_id,
                "has_text": bool(inbound.text),
                "interactive_action_selected": {
                    "id": inbound.action_selection.id,
                    "value": inbound.action_selection.value,
                    "label": inbound.action_selection.label,
                }
                if inbound.action_selection is not None
                else None,
            },
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:message_received",
            test_run_id=message.test_run_id,
        )

    def _record_interactive_action_selected(
        self,
        *,
        message: Message,
        inbound: InboundConversationMessage,
        session: ConversationSession,
        carrier: Carrier | None,
        action_selection: InboundActionSelection,
    ) -> EventLog:
        related_entity_ids = {
            "messageId": message.id,
            "conversationSessionId": session.id,
            "interactiveActionId": action_selection.id,
        }
        if carrier is not None:
            related_entity_ids["carrierId"] = carrier.id
        return self._event_log.record(
            event_type="INTERACTIVE_ACTION_SELECTED",
            actor_type=message.sender_type,
            actor_id=carrier.id if carrier is not None else None,
            entity_type="Message",
            entity_id=message.id,
            summary="Respuesta interactiva seleccionada",
            related_entity_ids=related_entity_ids,
            payload={
                "id": action_selection.id,
                "value": action_selection.value,
                "label": action_selection.label,
                "raw": action_selection.raw,
            },
            source=inbound.provider,
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:interactive_action_selected",
        )

    def _record_data_extracted(
        self,
        message: Message,
        shipment_request: ShipmentRequest,
        extraction: LoadDataExtraction,
        inbound: InboundConversationMessage,
    ) -> EventLog:
        return self._event_log.record(
            event_type="DATA_EXTRACTED",
            actor_type="AI Agent",
            entity_type="Message",
            entity_id=message.id,
            summary="Datos de carga extraidos desde mensaje",
            related_entity_ids={
                "messageId": message.id,
                "loadId": shipment_request.id,
                "conversationSessionId": message.conversation_session_id,
            },
            payload={
                "confidence": extraction.confidence,
                "field_confidence": extraction.field_confidence,
                "has_ambiguous_location": extraction.has_ambiguous_location,
            },
            source="ai_agent",
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:data_extracted",
        )

    def _record_load_preview_prepared(
        self,
        *,
        message: Message,
        session: ConversationSession,
        extraction: LoadDataExtraction,
        missing_fields: list[str],
        inbound: InboundConversationMessage,
        requires_human_review: bool,
    ) -> EventLog:
        return self._event_log.record(
            event_type="LOAD_PREVIEW_PREPARED",
            actor_type="SYSTEM",
            entity_type="ConversationSession",
            entity_id=session.id,
            summary="Resumen de carga preparado para confirmacion del productor",
            related_entity_ids={"messageId": message.id, "conversationSessionId": session.id},
            payload={
                "cargo_category": extraction.cargo_category,
                "cargo_type": extraction.cargo_type or extraction.livestock_type,
                "quantity_unit": extraction.quantity_unit,
                "quantity_estimate": str(extraction.quantity_estimate)
                if extraction.quantity_estimate is not None
                else None,
                "origin": extraction.origin,
                "destination": extraction.destination,
                "pickup_date": extraction.date_window_start.isoformat()
                if extraction.date_window_start is not None
                else None,
                "missing_fields": missing_fields,
                "requires_human_review": requires_human_review,
                "confidence": extraction.confidence,
                "has_ambiguous_location": extraction.has_ambiguous_location,
                "field_confidence": extraction.field_confidence,
            },
            source="conversation_orchestrator",
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:load_preview_prepared",
        )

    def _record_load_created(
        self,
        shipment_request: ShipmentRequest,
        message: Message,
        inbound: InboundConversationMessage,
    ) -> EventLog:
        return self._event_log.record(
            event_type="LOAD_CREATED",
            actor_type="System",
            entity_type="LivestockLoad",
            entity_id=shipment_request.id,
            summary="Carga creada desde conversacion",
            new_state=shipment_request.status,
            related_entity_ids={
                "loadId": shipment_request.id,
                "messageId": message.id,
                "conversationSessionId": message.conversation_session_id,
            },
            source="system",
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:load_created",
        )

    def _record_load_incomplete(
        self,
        shipment_request: ShipmentRequest,
        message: Message,
        inbound: InboundConversationMessage,
        missing_fields: list[str],
    ) -> EventLog:
        return self._event_log.record(
            event_type="LOAD_INCOMPLETE",
            actor_type="System",
            entity_type="LivestockLoad",
            entity_id=shipment_request.id,
            summary="Carga creada con datos faltantes",
            new_state=shipment_request.status,
            related_entity_ids={
                "loadId": shipment_request.id,
                "messageId": message.id,
                "conversationSessionId": message.conversation_session_id,
            },
            payload={"missing_critical_fields": missing_fields},
            source="system",
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:load_incomplete",
        )

    def _record_human_review_requested(
        self,
        message: Message,
        inbound: InboundConversationMessage,
        reason: str,
        shipment_request: ShipmentRequest | None = None,
    ) -> EventLog:
        related_ids = {
            "messageId": message.id,
            "conversationSessionId": message.conversation_session_id,
        }
        entity_type = "Message"
        entity_id = message.id
        if shipment_request is not None:
            related_ids["loadId"] = shipment_request.id
            entity_type = "LivestockLoad"
            entity_id = shipment_request.id
        return self._event_log.record(
            event_type="HUMAN_REVIEW_REQUESTED",
            actor_type="System",
            entity_type=entity_type,
            entity_id=entity_id,
            summary="Revision humana requerida",
            related_entity_ids=related_ids,
            payload={"reason": reason},
            source="system",
            correlation_id=inbound.correlation_id,
            idempotency_key=f"{inbound.idempotency_key}:human_review",
        )
