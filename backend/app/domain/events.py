from dataclasses import dataclass, field
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


current_test_run_id: ContextVar[str | None] = ContextVar("current_test_run_id", default=None)


@dataclass(frozen=True)
class EventLog:
    event_id: str
    event_type: str
    occurred_at: datetime
    actor_type: str
    entity_type: str
    entity_id: str
    summary: str
    test_run_id: str | None = None
    actor_id: str | None = None
    related_entity_ids: dict[str, str] = field(default_factory=dict)
    previous_state: str | None = None
    new_state: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    correlation_id: str | None = None
    idempotency_key: str | None = None


class DuplicateEventError(ValueError):
    pass


class EventLogService:
    """In-memory event log service for domain-level tests and orchestration.

    Persistence is intentionally out of scope until repositories/models are
    implemented. The API keeps idempotency explicit so a repository-backed
    version can preserve the same contract later.
    """

    def __init__(self) -> None:
        self._events: list[EventLog] = []
        self._idempotency_index: dict[str, EventLog] = {}

    @property
    def events(self) -> tuple[EventLog, ...]:
        return tuple(self._events)

    def list(self, *, include_deleted: bool = False) -> list[EventLog]:
        del include_deleted
        return list(self._events)

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
        test_run_id: str | None = None,
    ) -> EventLog:
        test_run_id = test_run_id or current_test_run_id.get()
        if idempotency_key and idempotency_key in self._idempotency_index:
            return self._idempotency_index[idempotency_key]

        event = EventLog(
            event_id=f"evt_{uuid4().hex}",
            test_run_id=test_run_id,
            event_type=event_type,
            occurred_at=occurred_at or datetime.now(UTC),
            actor_type=actor_type,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            related_entity_ids=related_entity_ids or {},
            previous_state=previous_state,
            new_state=new_state,
            summary=summary,
            payload=payload or {},
            source=source,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self._events.append(event)
        if idempotency_key:
            self._idempotency_index[idempotency_key] = event
        return event
