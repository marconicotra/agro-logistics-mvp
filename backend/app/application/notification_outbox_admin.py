from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class NotificationOutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRY = "RETRY"
    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"


@dataclass(frozen=True)
class NotificationOutboxItem:
    id: str
    status: str
    provider: str
    notification_type: str | None
    entity_type: str | None
    entity_id: str | None
    test_run_id: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    last_error_code: str | None


@dataclass(frozen=True)
class NotificationOutboxPage:
    counts: dict[str, int]
    items: tuple[NotificationOutboxItem, ...]
    total: int
    limit: int
    offset: int


class NotificationOutboxReadRepository(Protocol):
    def counts(self) -> dict[str, int]: ...

    def list(
        self,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationOutboxItem], int]: ...

    def reconcile(
        self,
        *,
        outbox_id: str,
        resolution: str,
        evidence_reference: str,
        operator_user_id: str,
    ) -> str: ...


class NotificationOutboxAdminService:
    def __init__(self, repository: NotificationOutboxReadRepository | None) -> None:
        self._repository = repository

    def list_page(
        self,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> NotificationOutboxPage:
        if self._repository is None:
            return NotificationOutboxPage(
                counts={state.value: 0 for state in NotificationOutboxStatus},
                items=(),
                total=0,
                limit=limit,
                offset=offset,
            )
        counts = self._repository.counts()
        items, total = self._repository.list(status=status, limit=limit, offset=offset)
        return NotificationOutboxPage(
            counts=counts,
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    def reconcile(
        self,
        *,
        outbox_id: str,
        resolution: str,
        evidence_reference: str,
        operator_user_id: str,
    ) -> str:
        if self._repository is None:
            raise RuntimeError("Outbox reconciliation requires SQL persistence")
        return self._repository.reconcile(
            outbox_id=outbox_id,
            resolution=resolution,
            evidence_reference=evidence_reference,
            operator_user_id=operator_user_id,
        )
