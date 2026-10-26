from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class InboundMedia:
    media_type: str
    provider_media_id: str | None = None
    external_url: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    sha256: str | None = None
    caption: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InboundActionSelection:
    id: str
    value: str
    label: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedInboundEvent:
    provider: str
    event_type: str
    idempotency_key: str
    correlation_id: str
    conversation_id: str | None = None
    workflow_execution_id: str | None = None
    provider_contact_id: str | None = None
    provider_message_id: str | None = None
    phone_number: str | None = None
    occurred_at: str | None = None
    text: str | None = None
    location: dict[str, Any] | None = None
    reply_to_message_id: str | None = None
    media: InboundMedia | None = None
    action_selection: InboundActionSelection | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundAction:
    id: str
    label: str
    value: str
    kind: str = "quick_reply"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "kind": self.kind,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_interactive_messages: bool = False
    supports_buttons: bool = False
    supports_list_messages: bool = False


@dataclass(frozen=True)
class OutboundMessage:
    conversation_id: str
    body: str
    message_type: str = "text"
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    actions: tuple[OutboundAction, ...] = ()
    allowlist_phone_number: str | None = None


@dataclass(frozen=True)
class OutboundResult:
    provider: str
    accepted: bool
    provider_message_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class WhatsAppProvider(Protocol):
    provider_name: str
    capabilities: ProviderCapabilities

    def normalize_inbound(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> NormalizedInboundEvent:
        pass

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        pass


class MockWhatsAppProvider:
    provider_name = "mock_whatsapp"
    capabilities = ProviderCapabilities()

    def __init__(self, *, failing_conversation_ids: set[str] | None = None) -> None:
        self.sent_messages: list[OutboundMessage] = []
        self.failing_conversation_ids = failing_conversation_ids or set()

    def normalize_inbound(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> NormalizedInboundEvent:
        raise NotImplementedError("MockWhatsAppProvider only supports outbound messages")

    def send_message(self, message: OutboundMessage) -> OutboundResult:
        if message.conversation_id in self.failing_conversation_ids:
            raise RuntimeError("Mock provider configured to fail")
        self.sent_messages.append(message)
        return OutboundResult(
            provider=self.provider_name,
            accepted=True,
            provider_message_id=f"mock_msg_{uuid4().hex}",
            correlation_id=message.correlation_id,
            payload={"conversation_id": message.conversation_id},
        )
