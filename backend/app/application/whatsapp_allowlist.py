from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, Protocol, TypeVar

from app.application.contact_mapping import PhoneNormalizationError, normalize_phone_number
from app.domain.events import EventLog, EventLogService
from app.domain.models import WhatsappAllowedContact


class WhatsappAllowlistError(ValueError):
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
class AllowlistDecision:
    allowed: bool
    reason: str
    contact_id: str | None = None
    matched_source: str | None = None
    normalized_phone_number: str | None = None


@dataclass(frozen=True)
class WhatsappAllowedContactInput:
    phone_number: str
    label: str | None = None
    environment: str = "all"
    provider: str = "all"
    status: str = "ACTIVE"
    notes: str | None = None


@dataclass(frozen=True)
class WhatsappAllowedContactSummary:
    id: str
    phone_number: str
    normalized_phone_number: str
    label: str | None
    environment: str
    provider: str
    status: str
    notes: str | None
    created_by_user_id: str | None
    updated_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


class WhatsappAllowlistService:
    VALID_ENVIRONMENTS = {"local", "staging", "production", "all"}
    VALID_PROVIDERS = {"kapso", "whatsapp", "all"}
    VALID_STATUSES = {"ACTIVE", "BLOCKED", "DISABLED"}

    def __init__(
        self,
        *,
        contacts: Repository[WhatsappAllowedContact],
        event_log: EventRecorder | EventLogService,
        environment: str,
        source: str,
        default_allow: bool,
        env_allowlist: set[str] | None = None,
    ) -> None:
        self._contacts = contacts
        self._event_log = event_log
        self._environment = environment.strip().lower()
        self._source = source.strip().lower()
        self._default_allow = default_allow
        self._env_allowlist = env_allowlist or set()

    def is_phone_allowed(
        self,
        *,
        phone_number: str | None,
        provider: str,
        environment: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        record_event: bool = False,
    ) -> AllowlistDecision:
        environment_value = (environment or self._environment).strip().lower()
        provider_value = provider.strip().lower()
        normalized_phone = self.normalize_phone_number(phone_number)
        if normalized_phone is None:
            decision = AllowlistDecision(
                allowed=False,
                reason="missing_phone_number",
                normalized_phone_number=None,
            )
            if record_event:
                self._record_inbound_decision(
                    decision,
                    phone_number=phone_number,
                    provider=provider_value,
                    environment=environment_value,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                )
            return decision

        db_matches = []
        if self._source in {"db", "db_then_env"}:
            db_matches = [
                contact
                for contact in self._contacts.list()
                if self._same_phone(phone_number=normalized_phone, contact=contact)
                and self._scope_matches(
                    contact=contact,
                    environment=environment_value,
                    provider=provider_value,
                )
            ]
        blocked_match = next((contact for contact in db_matches if contact.status == "BLOCKED"), None)
        if blocked_match is not None:
            decision = AllowlistDecision(
                allowed=False,
                reason="matched_db_blocked",
                contact_id=blocked_match.id,
                matched_source="db",
                normalized_phone_number=normalized_phone,
            )
            if record_event:
                self._record_inbound_decision(
                    decision,
                    phone_number=phone_number,
                    provider=provider_value,
                    environment=environment_value,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                )
            return decision

        active_match = next((contact for contact in db_matches if contact.status == "ACTIVE"), None)
        if active_match is not None:
            decision = AllowlistDecision(
                allowed=True,
                reason="matched_db_active",
                contact_id=active_match.id,
                matched_source="db",
                normalized_phone_number=normalized_phone,
            )
            if record_event:
                self._record_inbound_decision(
                    decision,
                    phone_number=phone_number,
                    provider=provider_value,
                    environment=environment_value,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                )
            return decision

        disabled_match = next((contact for contact in db_matches if contact.status == "DISABLED"), None)
        if disabled_match is not None:
            decision = AllowlistDecision(
                allowed=False,
                reason="matched_db_disabled",
                contact_id=disabled_match.id,
                matched_source="db",
                normalized_phone_number=normalized_phone,
            )
            if record_event:
                self._record_inbound_decision(
                    decision,
                    phone_number=phone_number,
                    provider=provider_value,
                    environment=environment_value,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                )
            return decision

        if self._source in {"env", "db_then_env"} and not self._is_production_environment(environment_value):
            if self._phone_in_env_allowlist(normalized_phone):
                decision = AllowlistDecision(
                    allowed=True,
                    reason="matched_env_fallback",
                    matched_source="env",
                    normalized_phone_number=normalized_phone,
                )
                if record_event:
                    self._record_inbound_decision(
                        decision,
                        phone_number=phone_number,
                        provider=provider_value,
                        environment=environment_value,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                    )
                return decision

        if self._default_allow and not self._is_production_environment(environment_value):
            decision = AllowlistDecision(
                allowed=True,
                reason="default_allow_non_production",
                matched_source="default",
                normalized_phone_number=normalized_phone,
            )
            if record_event:
                self._record_inbound_decision(
                    decision,
                    phone_number=phone_number,
                    provider=provider_value,
                    environment=environment_value,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                )
            return decision

        decision = AllowlistDecision(
            allowed=False,
            reason="not_in_allowlist",
            matched_source="none",
            normalized_phone_number=normalized_phone,
        )
        if record_event:
            self._record_inbound_decision(
                decision,
                phone_number=phone_number,
                provider=provider_value,
                environment=environment_value,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        return decision

    def list_contacts(
        self,
        *,
        status: str | None = None,
        environment: str | None = None,
        provider: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WhatsappAllowedContactSummary]:
        normalized_search = (search or "").strip().lower()
        rows = []
        for contact in self._contacts.list():
            if status and contact.status != status.strip().upper():
                continue
            if environment and contact.environment != environment.strip().lower():
                continue
            if provider and contact.provider != provider.strip().lower():
                continue
            if normalized_search and normalized_search not in " ".join(
                [
                    contact.phone_number,
                    contact.normalized_phone_number,
                    contact.label or "",
                    contact.notes or "",
                ]
            ).lower():
                continue
            rows.append(self._summary(contact))
        rows.sort(key=lambda item: item.created_at, reverse=True)
        start = max(offset, 0)
        return rows[start : start + max(min(limit, 200), 1)]

    def create_contact(
        self,
        *,
        operator_user_id: str,
        data: WhatsappAllowedContactInput,
    ) -> WhatsappAllowedContact:
        normalized_phone = self._require_normalized_phone_number(data.phone_number)
        environment = self._validate_environment(data.environment)
        provider = self._validate_provider(data.provider)
        status = self._validate_status(data.status)
        self._ensure_no_duplicate(
            normalized_phone_number=normalized_phone,
            environment=environment,
            provider=provider,
        )
        contact = WhatsappAllowedContact(
            phone_number=data.phone_number.strip(),
            normalized_phone_number=normalized_phone,
            label=self._normalized_text(data.label),
            environment=environment,
            provider=provider,
            status=status,
            notes=self._normalized_text(data.notes),
            created_by_user_id=operator_user_id,
            updated_by_user_id=operator_user_id,
        )
        self._contacts.add(contact)
        self._record_contact_event(
            event_type="WHATSAPP_ALLOWED_CONTACT_CREATED",
            summary="Numero autorizado de WhatsApp creado",
            contact=contact,
            actor_id=operator_user_id,
            previous_state=None,
            new_state=contact.status,
            payload=self._contact_payload(contact),
        )
        return contact

    def update_contact(
        self,
        *,
        contact_id: str,
        operator_user_id: str,
        data: WhatsappAllowedContactInput,
    ) -> WhatsappAllowedContact:
        contact = self._require_contact(contact_id)
        before = self._contact_payload(contact)
        normalized_phone = self._require_normalized_phone_number(data.phone_number)
        environment = self._validate_environment(data.environment)
        provider = self._validate_provider(data.provider)
        status = self._validate_status(data.status)
        self._ensure_no_duplicate(
            normalized_phone_number=normalized_phone,
            environment=environment,
            provider=provider,
            exclude_contact_id=contact.id,
        )
        previous_status = contact.status
        contact.phone_number = data.phone_number.strip()
        contact.normalized_phone_number = normalized_phone
        contact.label = self._normalized_text(data.label)
        contact.environment = environment
        contact.provider = provider
        contact.status = status
        contact.notes = self._normalized_text(data.notes)
        contact.updated_by_user_id = operator_user_id
        contact.mark_updated()
        self._contacts.save(contact)
        after = self._contact_payload(contact)
        changed_fields = [key for key, value in after.items() if before.get(key) != value]
        self._record_contact_event(
            event_type="WHATSAPP_ALLOWED_CONTACT_UPDATED",
            summary="Numero autorizado de WhatsApp actualizado",
            contact=contact,
            actor_id=operator_user_id,
            previous_state=previous_status,
            new_state=contact.status,
            payload={
                "changed_fields": changed_fields,
                "previous_values": {key: before[key] for key in changed_fields},
                "new_values": {key: after[key] for key in changed_fields},
            },
        )
        return contact

    def block_contact(
        self,
        *,
        contact_id: str,
        operator_user_id: str,
        reason: str,
    ) -> WhatsappAllowedContact:
        if not reason.strip():
            raise WhatsappAllowlistError("reason is required")
        contact = self._require_contact(contact_id)
        previous_status = contact.status
        contact.status = "BLOCKED"
        contact.notes = self._merge_note(contact.notes, reason)
        contact.updated_by_user_id = operator_user_id
        contact.mark_updated()
        self._contacts.save(contact)
        self._record_contact_event(
            event_type="WHATSAPP_ALLOWED_CONTACT_BLOCKED",
            summary="Numero de WhatsApp bloqueado",
            contact=contact,
            actor_id=operator_user_id,
            previous_state=previous_status,
            new_state=contact.status,
            payload={"reason": reason.strip(), **self._contact_payload(contact)},
        )
        return contact

    def reactivate_contact(
        self,
        *,
        contact_id: str,
        operator_user_id: str,
    ) -> WhatsappAllowedContact:
        contact = self._require_contact(contact_id)
        previous_status = contact.status
        contact.status = "ACTIVE"
        contact.updated_by_user_id = operator_user_id
        contact.mark_updated()
        self._contacts.save(contact)
        self._record_contact_event(
            event_type="WHATSAPP_ALLOWED_CONTACT_REACTIVATED",
            summary="Numero de WhatsApp reactivado",
            contact=contact,
            actor_id=operator_user_id,
            previous_state=previous_status,
            new_state=contact.status,
            payload=self._contact_payload(contact),
        )
        return contact

    def disable_contact(
        self,
        *,
        contact_id: str,
        operator_user_id: str,
    ) -> WhatsappAllowedContact:
        contact = self._require_contact(contact_id)
        previous_status = contact.status
        contact.status = "DISABLED"
        contact.updated_by_user_id = operator_user_id
        contact.mark_updated()
        self._contacts.save(contact)
        self._record_contact_event(
            event_type="WHATSAPP_ALLOWED_CONTACT_DISABLED",
            summary="Numero de WhatsApp deshabilitado",
            contact=contact,
            actor_id=operator_user_id,
            previous_state=previous_status,
            new_state=contact.status,
            payload=self._contact_payload(contact),
        )
        return contact

    def normalize_phone_number(self, phone_number: str | None) -> str | None:
        try:
            return normalize_phone_number(phone_number)
        except PhoneNormalizationError:
            return None

    def phone_match_key(self, phone_number: str | None) -> str | None:
        normalized = self.normalize_phone_number(phone_number)
        if normalized is None:
            return None
        digits = normalized[1:] if normalized.startswith("+") else normalized
        if digits.startswith("549"):
            return f"54{digits[3:]}"
        if digits.startswith("54"):
            return f"54{digits[2:]}"
        return digits

    def _scope_matches(
        self,
        *,
        contact: WhatsappAllowedContact,
        environment: str,
        provider: str,
    ) -> bool:
        environment_match = contact.environment in {environment, "all"}
        provider_match = contact.provider in {provider, "all"}
        return environment_match and provider_match

    def _phone_in_env_allowlist(self, normalized_phone_number: str) -> bool:
        target_key = self.phone_match_key(normalized_phone_number)
        if target_key is None:
            return False
        for item in self._env_allowlist:
            if self.phone_match_key(item) == target_key:
                return True
        return False

    def _same_phone(self, *, phone_number: str, contact: WhatsappAllowedContact) -> bool:
        return self.phone_match_key(phone_number) == self.phone_match_key(contact.normalized_phone_number)

    def _ensure_no_duplicate(
        self,
        *,
        normalized_phone_number: str,
        environment: str,
        provider: str,
        exclude_contact_id: str | None = None,
    ) -> None:
        target_key = self.phone_match_key(normalized_phone_number)
        for contact in self._contacts.list():
            if exclude_contact_id and contact.id == exclude_contact_id:
                continue
            if contact.environment != environment or contact.provider != provider:
                continue
            if self.phone_match_key(contact.normalized_phone_number) != target_key:
                continue
            if contact.status in {"ACTIVE", "BLOCKED", "DISABLED"}:
                raise WhatsappAllowlistError(
                    "An allowlist contact already exists for this phone/environment/provider"
                )

    def _record_inbound_decision(
        self,
        decision: AllowlistDecision,
        *,
        phone_number: str | None,
        provider: str,
        environment: str,
        correlation_id: str | None,
        idempotency_key: str | None,
    ) -> None:
        event_type = (
            "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST"
            if decision.allowed
            else "WHATSAPP_INBOUND_BLOCKED_BY_ALLOWLIST"
        )
        entity_id = decision.contact_id or f"allowlist:{decision.normalized_phone_number or 'unknown'}"
        summary = (
            "Inbound WhatsApp permitido por allowlist"
            if decision.allowed
            else "Inbound WhatsApp bloqueado por allowlist"
        )
        self._event_log.record(
            event_type=event_type,
            actor_type="SYSTEM",
            entity_type="WhatsappAllowedContact",
            entity_id=entity_id,
            summary=summary,
            related_entity_ids=(
                {"whatsappAllowedContactId": decision.contact_id} if decision.contact_id else {}
            ),
            payload={
                "phone_number": phone_number,
                "normalized_phone_number": decision.normalized_phone_number,
                "environment": environment,
                "provider": provider,
                "status": "ALLOWED" if decision.allowed else "BLOCKED",
                "reason": decision.reason,
                "matched_contact_id": decision.contact_id,
                "matched_source": decision.matched_source,
            },
            source="whatsapp_allowlist",
            correlation_id=correlation_id,
            idempotency_key=f"allowlist:{idempotency_key}:{event_type}" if idempotency_key else None,
        )

    def _record_contact_event(
        self,
        *,
        event_type: str,
        summary: str,
        contact: WhatsappAllowedContact,
        actor_id: str | None,
        previous_state: str | None,
        new_state: str | None,
        payload: dict[str, Any],
    ) -> None:
        self._event_log.record(
            event_type=event_type,
            actor_type="OPERATOR",
            actor_id=actor_id,
            entity_type="WhatsappAllowedContact",
            entity_id=contact.id,
            summary=summary,
            previous_state=previous_state,
            new_state=new_state,
            payload=payload,
            source="backoffice",
        )

    def _require_contact(self, contact_id: str) -> WhatsappAllowedContact:
        contact = self._contacts.get(contact_id)
        if contact is None:
            raise KeyError(contact_id)
        return contact

    def _require_normalized_phone_number(self, phone_number: str) -> str:
        normalized = self.normalize_phone_number(phone_number)
        if normalized is None:
            raise WhatsappAllowlistError("phone_number is invalid")
        return normalized

    def _validate_environment(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in self.VALID_ENVIRONMENTS:
            raise WhatsappAllowlistError("environment is invalid")
        return normalized

    def _validate_provider(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in self.VALID_PROVIDERS:
            raise WhatsappAllowlistError("provider is invalid")
        return normalized

    def _validate_status(self, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in self.VALID_STATUSES:
            raise WhatsappAllowlistError("status is invalid")
        return normalized

    def _summary(self, contact: WhatsappAllowedContact) -> WhatsappAllowedContactSummary:
        return WhatsappAllowedContactSummary(
            id=contact.id,
            phone_number=contact.phone_number,
            normalized_phone_number=contact.normalized_phone_number,
            label=contact.label,
            environment=contact.environment,
            provider=contact.provider,
            status=contact.status,
            notes=contact.notes,
            created_by_user_id=contact.created_by_user_id,
            updated_by_user_id=contact.updated_by_user_id,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
        )

    def _contact_payload(self, contact: WhatsappAllowedContact) -> dict[str, Any]:
        return {
            "phone_number": contact.phone_number,
            "normalized_phone_number": contact.normalized_phone_number,
            "label": contact.label,
            "environment": contact.environment,
            "provider": contact.provider,
            "status": contact.status,
            "notes": contact.notes,
        }

    def _normalized_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _merge_note(self, current: str | None, extra: str) -> str:
        current_text = self._normalized_text(current)
        extra_text = extra.strip()
        if not current_text:
            return extra_text
        return f"{current_text}\n{extra_text}"

    def _is_production_environment(self, environment: str) -> bool:
        return environment == "production"
