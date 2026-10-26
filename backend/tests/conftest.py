from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.infrastructure.db.session import get_engine, get_session_factory


@pytest.fixture(autouse=True)
def safe_test_runtime_defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("KAPSO_INTERACTIVE_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "")
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "mock")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "false")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "local-dev-secret")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def legacy_broadcast(monkeypatch):
    """Historical explicit-recipient cases; new directed cases run with the feature enabled."""
    monkeypatch.setenv("ROUTE_OPERATIONS_ENABLED", "false")
    get_settings.cache_clear()
