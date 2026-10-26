from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.events import EventLog, current_test_run_id
from app.infrastructure.db.repositories import SqlEventLogRepository


class SqlEventLogService:
    def __init__(self, session: Session) -> None:
        self._repository = SqlEventLogRepository(session)

    @property
    def events(self) -> tuple[EventLog, ...]:
        return tuple(self._repository.list())

    def list(self, *, include_deleted: bool = False) -> list[EventLog]:
        return self._repository.list(include_deleted=include_deleted)

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
        if idempotency_key:
            existing = self._repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

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
        return self._repository.add(event)
