"""Memory and SQL stores with identical scope and transactional locking rules."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from threading import RLock

from sqlalchemy import select, text

from app.domain.routing import RoutingEntry, aware
from app.infrastructure.db.base import Base
from sqlalchemy import Column, DateTime, Index, JSON, String


class RoutingOperationRecord(Base):
    __tablename__ = "routing_operations"
    id = Column(String(96), primary_key=True)
    kind = Column(String(24), nullable=False)
    entity_id = Column(String(96), nullable=False)
    test_run_id = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index("ix_routing_due", "kind", "status", "due_at"),
        Index("ix_routing_scope", "kind", "test_run_id", "entity_id"),
    )


class MemoryRoutingStore:
    def __init__(self):
        self.entries = {}
        self.mutex = RLock()

    def put(self, entry):
        self.entries[entry.id] = deepcopy(entry)
        return entry

    def get(self, entry_id):
        return deepcopy(self.entries.get(entry_id))

    def list(self, kind, scope, *, entity_id=None):
        return [deepcopy(e) for e in self.entries.values() if e.kind == kind and e.test_run_id == scope and (entity_id is None or e.entity_id == entity_id)]

    def checkpoint_for_reply(self, provider_id):
        return next((e.id for e in self.entries.values() if e.kind == "checkpoint" and e.data.get("provider_message_id") == provider_id), None)

    def due(self, now):
        return sorted((deepcopy(e) for e in self.entries.values() if e.kind == "job" and e.status == "PENDING" and e.due_at and aware(e.due_at) <= now), key=lambda e: (aware(e.due_at), e.id))

    @contextmanager
    def lock(self, key):
        with self.mutex:
            yield


class SqlRoutingStore:
    def __init__(self, session):
        self.session = session

    def put(self, entry):
        self.session.merge(RoutingOperationRecord(**asdict(entry)))
        self.session.flush()
        return entry

    def get(self, entry_id):
        record = self.session.get(RoutingOperationRecord, entry_id, populate_existing=True)
        return self._domain(record) if record else None

    def list(self, kind, scope, *, entity_id=None):
        stmt = select(RoutingOperationRecord).where(RoutingOperationRecord.kind == kind, RoutingOperationRecord.test_run_id == scope)
        if entity_id is not None:
            stmt = stmt.where(RoutingOperationRecord.entity_id == entity_id)
        return [self._domain(r) for r in self.session.scalars(stmt)]

    def checkpoint_for_reply(self, provider_id):
        from app.infrastructure.db.models import NotificationOutboxRecord
        record = self.session.scalar(select(NotificationOutboxRecord).where(NotificationOutboxRecord.provider_message_id == provider_id))
        return record.message_payload.get("metadata", {}).get("checkpoint_id") if record else None

    def due(self, now):
        stmt = select(RoutingOperationRecord).where(RoutingOperationRecord.kind == "job", RoutingOperationRecord.status == "PENDING", RoutingOperationRecord.due_at <= now).order_by(RoutingOperationRecord.due_at, RoutingOperationRecord.id).limit(1).with_for_update(skip_locked=True)
        return [self._domain(r) for r in self.session.scalars(stmt)]

    @contextmanager
    def lock(self, key):
        # Held until transaction commits, including related outbox and bookings.
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.flush()
            number = int.from_bytes(sha256(key.encode()).digest()[:8], "big", signed=True)
            self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})
            self.session.expire_all()
        yield

    @staticmethod
    def _domain(r):
        return RoutingEntry(**{c.name: deepcopy(getattr(r, c.name)) for c in r.__table__.columns})
