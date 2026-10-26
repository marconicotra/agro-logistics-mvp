from collections.abc import Iterable
from typing import Generic, Protocol, TypeVar


class Identified(Protocol):
    id: str


class SoftDeletable(Protocol):
    deleted_at: object | None

    def soft_delete(self) -> None:
        pass


T = TypeVar("T", bound=Identified)


class InMemoryRepository(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def add(self, entity: T) -> T:
        if entity.id in self._items:
            raise ValueError(f"Entity already exists: {entity.id}")
        self._items[entity.id] = entity
        return entity

    def get(self, entity_id: str) -> T | None:
        return self._items.get(entity_id)

    def list(self, *, include_deleted: bool = False) -> list[T]:
        if include_deleted:
            return list(self._items.values())
        return [
            item
            for item in self._items.values()
            if not hasattr(item, "deleted_at") or getattr(item, "deleted_at") is None
        ]

    def save(self, entity: T) -> T:
        if entity.id not in self._items:
            raise ValueError(f"Entity does not exist: {entity.id}")
        if hasattr(entity, "mark_updated"):
            entity.mark_updated()  # type: ignore[attr-defined]
        self._items[entity.id] = entity
        return entity

    def soft_delete(self, entity_id: str) -> T:
        entity = self._items.get(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        if not hasattr(entity, "soft_delete"):
            raise TypeError(f"Entity does not support soft delete: {entity_id}")
        entity.soft_delete()  # type: ignore[attr-defined]
        return entity

    def extend(self, entities: Iterable[T]) -> None:
        for entity in entities:
            self.add(entity)

