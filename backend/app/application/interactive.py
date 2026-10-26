from app.infrastructure.adapters.whatsapp import OutboundAction, OutboundMessage, ProviderCapabilities


MAX_DIRECT_BUTTONS = 3
MAX_LIST_ITEMS = 10


def build_text_fallback(body: str, actions: tuple[OutboundAction, ...]) -> str:
    if not actions:
        return body
    lines = [body.rstrip(), ""]
    lines.extend(f"{index}. {action.label}" for index, action in enumerate(actions, start=1))
    lines.extend(["", "Respondé con el número o el texto de la opción."])
    return "\n".join(lines)


def prepare_outbound_message(
    message: OutboundMessage,
    capabilities: ProviderCapabilities,
) -> tuple[OutboundMessage, str]:
    if not message.actions:
        return message, "text"

    action_payload = [action.as_metadata() for action in message.actions]
    metadata = {
        **message.metadata,
        "interactive_actions": action_payload,
    }

    force_list = all(action.kind == "list_row" for action in message.actions)
    if (
        force_list
        and capabilities.supports_interactive_messages
        and capabilities.supports_list_messages
        and len(message.actions) <= MAX_LIST_ITEMS
    ):
        return (
            OutboundMessage(
                conversation_id=message.conversation_id,
                body=message.body,
                message_type="interactive_list",
                correlation_id=message.correlation_id,
                metadata={**metadata, "interactive_delivery": "list"},
                actions=message.actions,
                allowlist_phone_number=message.allowlist_phone_number,
            ),
            "list",
        )

    if (
        capabilities.supports_interactive_messages
        and capabilities.supports_buttons
        and len(message.actions) <= MAX_DIRECT_BUTTONS
    ):
        return (
            OutboundMessage(
                conversation_id=message.conversation_id,
                body=message.body,
                message_type="interactive",
                correlation_id=message.correlation_id,
                metadata={**metadata, "interactive_delivery": "buttons"},
                actions=message.actions,
                allowlist_phone_number=message.allowlist_phone_number,
            ),
            "buttons",
        )

    if (
        capabilities.supports_interactive_messages
        and capabilities.supports_list_messages
        and MAX_DIRECT_BUTTONS < len(message.actions) <= MAX_LIST_ITEMS
    ):
        return (
            OutboundMessage(
                conversation_id=message.conversation_id,
                body=message.body,
                message_type="interactive_list",
                correlation_id=message.correlation_id,
                metadata={**metadata, "interactive_delivery": "list"},
                actions=message.actions,
                allowlist_phone_number=message.allowlist_phone_number,
            ),
            "list",
        )

    return (
        OutboundMessage(
            conversation_id=message.conversation_id,
            body=build_text_fallback(message.body, message.actions),
            message_type="text",
            correlation_id=message.correlation_id,
            metadata={**metadata, "interactive_delivery": "text_fallback"},
            actions=message.actions,
            allowlist_phone_number=message.allowlist_phone_number,
        ),
        "text_fallback",
    )


def compact_action_label(label: str, *, max_length: int = 20) -> str:
    compact = " ".join(label.split())
    if len(compact) <= max_length:
        return compact
    return compact[:max_length].rstrip()
