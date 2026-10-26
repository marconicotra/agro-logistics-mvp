from dataclasses import dataclass


@dataclass(frozen=True)
class IdempotencyResult:
    key: str
    is_duplicate: bool


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def check_and_store(self, *, provider: str, idempotency_key: str) -> IdempotencyResult:
        key = f"{provider}:{idempotency_key}"
        if key in self._seen:
            return IdempotencyResult(key=key, is_duplicate=True)
        self._seen.add(key)
        return IdempotencyResult(key=key, is_duplicate=False)
