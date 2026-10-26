from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_ai_extraction_client, reset_app_state
from app.application.ai import LoadDataExtraction
from app.application.whatsapp_allowlist import (
    WhatsappAllowlistService,
)
from app.core.config import get_settings
from app.domain.events import EventLogService
from app.domain.models import WhatsappAllowedContact
from app.infrastructure.repositories.memory import InMemoryRepository
from app.main import app


OPERATOR_HEADERS = {
    "x-internal-api-key": "qa-internal-test-key",
    "x-operator-user-id": "user_operator",
    "x-operator-role": "operator",
}


class FakeAIClient:
    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        return LoadDataExtraction(
            raw_text=message_text,
            origin="Azul",
            destination="Liniers",
            date_window_start=datetime(2026, 6, 13, 8, 0, tzinfo=UTC),
            livestock_type="novillos",
            quantity_estimate=Decimal("35"),
            contact="Juan",
            confidence="high",
            field_confidence={"origin": "provided"},
        )


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("INTERNAL_API_KEY", "qa-internal-test-key")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("WHATSAPP_ALLOWLIST_SOURCE", "db_then_env")
    monkeypatch.setenv("WHATSAPP_ALLOWLIST_DEFAULT_ALLOW", "false")
    monkeypatch.delenv("WHATSAPP_DEV_ALLOWLIST", raising=False)
    get_settings.cache_clear()
    reset_app_state()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_app_state()


def build_service(
    *,
    environment: str = "local",
    source: str = "db_then_env",
    default_allow: bool = False,
    env_allowlist: set[str] | None = None,
) -> tuple[WhatsappAllowlistService, InMemoryRepository[WhatsappAllowedContact], EventLogService]:
    contacts: InMemoryRepository[WhatsappAllowedContact] = InMemoryRepository()
    event_log = EventLogService()
    service = WhatsappAllowlistService(
        contacts=contacts,
        event_log=event_log,
        environment=environment,
        source=source,
        default_allow=default_allow,
        env_allowlist=env_allowlist,
    )
    return service, contacts, event_log


def signed_headers(raw_body: bytes) -> dict[str, str]:
    import hashlib
    import hmac

    digest = hmac.new(b"test-secret", raw_body, hashlib.sha256).hexdigest()
    return {"X-Webhook-Signature": f"sha256={digest}"}


def test_phone_normalization_variants_share_match_key() -> None:
    service, _, _ = build_service()

    variants = [
        "+5491135690073",
        "5491135690073",
        "+541135690073",
        " (011) 15-3569-0073 ",
    ]
    keys = {service.phone_match_key(value) for value in variants}

    assert keys == {"541135690073"}


def test_service_allows_active_exact_match() -> None:
    service, contacts, _ = build_service()
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+5491135690073",
            normalized_phone_number="+5491135690073",
            environment="local",
            provider="kapso",
            status="ACTIVE",
        )
    )

    decision = service.is_phone_allowed(phone_number="+541135690073", provider="kapso")

    assert decision.allowed is True
    assert decision.reason == "matched_db_active"


def test_service_allows_environment_and_provider_all() -> None:
    service, contacts, _ = build_service(environment="staging")
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+5491135690073",
            normalized_phone_number="+5491135690073",
            environment="all",
            provider="all",
            status="ACTIVE",
        )
    )

    decision = service.is_phone_allowed(phone_number="5491135690073", provider="whatsapp")

    assert decision.allowed is True


def test_blocked_contact_wins_over_generic_active_match() -> None:
    service, contacts, _ = build_service(environment="staging")
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+5491135690073",
            normalized_phone_number="+5491135690073",
            environment="all",
            provider="all",
            status="ACTIVE",
        )
    )
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+541135690073",
            normalized_phone_number="+541135690073",
            environment="staging",
            provider="kapso",
            status="BLOCKED",
        )
    )

    decision = service.is_phone_allowed(phone_number="+5491135690073", provider="kapso")

    assert decision.allowed is False
    assert decision.reason == "matched_db_blocked"


def test_service_blocks_when_number_missing_and_default_false() -> None:
    service, _, _ = build_service()

    decision = service.is_phone_allowed(phone_number="+5491111111111", provider="kapso")

    assert decision.allowed is False
    assert decision.reason == "not_in_allowlist"


def test_service_uses_env_fallback_only_when_enabled() -> None:
    service, _, _ = build_service(env_allowlist={"+5491111111111"})

    decision = service.is_phone_allowed(phone_number="+541111111111", provider="kapso")

    assert decision.allowed is True
    assert decision.reason == "matched_env_fallback"


def test_env_source_ignores_database_contacts() -> None:
    service, contacts, _ = build_service(
        source="env",
        env_allowlist={"+5491111111111"},
    )
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+5492222222222",
            normalized_phone_number="+5492222222222",
            environment="local",
            provider="kapso",
            status="ACTIVE",
        )
    )

    decision = service.is_phone_allowed(phone_number="+5492222222222", provider="kapso")

    assert decision.allowed is False
    assert decision.reason == "not_in_allowlist"


def test_env_source_still_matches_argentina_mobile_number_variants() -> None:
    service, _, _ = build_service(
        source="env",
        env_allowlist={"+541135690073"},
    )

    decision = service.is_phone_allowed(phone_number="+5491135690073", provider="kapso")

    assert decision.allowed is True
    assert decision.reason == "matched_env_fallback"


def test_db_priority_over_env_fallback() -> None:
    service, contacts, _ = build_service(env_allowlist={"+5491111111111"})
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+5491111111111",
            normalized_phone_number="+5491111111111",
            environment="local",
            provider="kapso",
            status="DISABLED",
        )
    )

    decision = service.is_phone_allowed(phone_number="+5491111111111", provider="kapso")

    assert decision.allowed is False
    assert decision.reason == "matched_db_disabled"


def test_production_ignores_env_fallback_and_default_allow() -> None:
    service, _, _ = build_service(
        environment="production",
        source="db",
        default_allow=False,
        env_allowlist={"+5491111111111"},
    )

    decision = service.is_phone_allowed(phone_number="+5491111111111", provider="kapso")

    assert decision.allowed is False
    assert decision.reason == "not_in_allowlist"


def test_production_allows_active_db_contact() -> None:
    service, contacts, _ = build_service(environment="production", source="db")
    contacts.add(
        WhatsappAllowedContact(
            phone_number="+5491111111111",
            normalized_phone_number="+5491111111111",
            environment="production",
            provider="kapso",
            status="ACTIVE",
        )
    )

    decision = service.is_phone_allowed(phone_number="+5491111111111", provider="kapso")

    assert decision.allowed is True
    assert decision.reason == "matched_db_active"


def test_backoffice_allowlist_crud_and_auth() -> None:
    client = TestClient(app)

    create_response = client.post(
        "/api/v1/backoffice/whatsapp-allowlist",
        headers=OPERATOR_HEADERS,
        json={
            "phone_number": "+5491135690073",
            "label": "Marco test",
            "environment": "staging",
            "provider": "kapso",
            "status": "ACTIVE",
            "notes": "Número de prueba",
        },
    )
    assert create_response.status_code == 201
    contact_id = create_response.json()["id"]

    list_response = client.get(
        "/api/v1/backoffice/whatsapp-allowlist?search=marco",
        headers=OPERATOR_HEADERS,
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [contact_id]

    update_response = client.patch(
        f"/api/v1/backoffice/whatsapp-allowlist/{contact_id}",
        headers=OPERATOR_HEADERS,
        json={
            "phone_number": "+541135690073",
            "label": "Marco editado",
            "environment": "all",
            "provider": "all",
            "status": "ACTIVE",
            "notes": "Editado",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["normalized_phone_number"] == "+541135690073"

    block_response = client.post(
        f"/api/v1/backoffice/whatsapp-allowlist/{contact_id}/block",
        headers=OPERATOR_HEADERS,
        json={"reason": "Bloqueado por soporte"},
    )
    assert block_response.status_code == 200
    assert block_response.json()["status"] == "BLOCKED"

    reactivate_response = client.post(
        f"/api/v1/backoffice/whatsapp-allowlist/{contact_id}/reactivate",
        headers=OPERATOR_HEADERS,
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["status"] == "ACTIVE"

    disable_response = client.post(
        f"/api/v1/backoffice/whatsapp-allowlist/{contact_id}/disable",
        headers=OPERATOR_HEADERS,
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["status"] == "DISABLED"

    missing_auth = client.get("/api/v1/backoffice/whatsapp-allowlist")
    assert missing_auth.status_code == 401


def test_backoffice_allowlist_records_events() -> None:
    client = TestClient(app)
    state = reset_app_state()

    create_response = client.post(
        "/api/v1/backoffice/whatsapp-allowlist",
        headers=OPERATOR_HEADERS,
        json={
            "phone_number": "+5491135690073",
            "environment": "staging",
            "provider": "kapso",
            "status": "ACTIVE",
        },
    )
    contact_id = create_response.json()["id"]
    client.post(
        f"/api/v1/backoffice/whatsapp-allowlist/{contact_id}/block",
        headers=OPERATOR_HEADERS,
        json={"reason": "Bloqueado"},
    )
    event_types = [event.event_type for event in state.event_log.events]  # type: ignore[attr-defined]
    assert "WHATSAPP_ALLOWED_CONTACT_CREATED" in event_types
    assert "WHATSAPP_ALLOWED_CONTACT_BLOCKED" in event_types


def test_backoffice_allowlist_update_persists_label_in_sql(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.infrastructure.db import models  # noqa: F401
    from app.infrastructure.db.base import Base
    from app.infrastructure.db.models import WhatsappAllowedContactRecord
    from app.infrastructure.db.session import get_engine, get_session_factory

    database_path = tmp_path / "allowlist.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "staging")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = create_engine(database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    with factory() as session, session.begin():
        session.add(
            WhatsappAllowedContactRecord(
                id="wac_sql_1",
                phone_number="+5491135690073",
                normalized_phone_number="+5491135690073",
                label="Viejo label",
                environment="staging",
                provider="kapso",
                status="ACTIVE",
                notes=None,
                created_by_user_id="seed",
                updated_by_user_id="seed",
            )
        )

    response = TestClient(app).patch(
        "/api/v1/backoffice/whatsapp-allowlist/wac_sql_1",
        headers=OPERATOR_HEADERS,
        json={
            "phone_number": "+5491135690073",
            "label": "Nuevo label",
            "environment": "staging",
            "provider": "kapso",
            "status": "ACTIVE",
            "notes": None,
        },
    )

    assert response.status_code == 200
    with factory() as session:
        stored = session.scalar(
            select(WhatsappAllowedContactRecord).where(WhatsappAllowedContactRecord.id == "wac_sql_1")
        )
        assert stored is not None
        assert stored.label == "Nuevo label"

    Base.metadata.drop_all(engine)
    engine.dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def test_webhook_blocks_inbound_not_in_allowlist() -> None:
    state = reset_app_state()
    client = TestClient(app)
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient()
    raw_body = (
        b'{"event_type":"message.received","idempotency_key":"evt_blocked","provider_contact_id":"contact_1",'
        b'"provider_message_id":"wamid_blocked","conversation_id":"conv_blocked","workflow_execution_id":"wf_1",'
        b'"phone_number":"+5491111111111","occurred_at":"2026-05-01T12:00:00Z","payload":{"text":"hola"}}'
    )

    response = client.post(
        "/api/v1/webhooks/kapso",
        content=raw_body,
        headers=signed_headers(raw_body),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1
    assert payload["results"][0]["accepted"] is False
    assert state.conversation_sessions.list() == []  # type: ignore[attr-defined]
    event_types = [event.event_type for event in state.event_log.events]  # type: ignore[attr-defined]
    assert "WHATSAPP_INBOUND_BLOCKED_BY_ALLOWLIST" in event_types


def test_webhook_allows_inbound_when_contact_is_active() -> None:
    state = reset_app_state()
    state.whatsapp_allowed_contacts.add(  # type: ignore[attr-defined]
        WhatsappAllowedContact(
            phone_number="+5491111111111",
            normalized_phone_number="+5491111111111",
            environment="local",
            provider="kapso",
            status="ACTIVE",
        )
    )
    client = TestClient(app)
    app.dependency_overrides[get_ai_extraction_client] = lambda: FakeAIClient()
    raw_body = (
        b'{"event_type":"message.received","idempotency_key":"evt_allowed","provider_contact_id":"contact_1",'
        b'"provider_message_id":"wamid_allowed","conversation_id":"conv_allowed","workflow_execution_id":"wf_1",'
        b'"phone_number":"+5491111111111","occurred_at":"2026-05-01T12:00:00Z","payload":{"text":"35 novillos"}}'
    )

    response = client.post(
        "/api/v1/webhooks/kapso",
        content=raw_body,
        headers=signed_headers(raw_body),
    )

    assert response.status_code == 200
    assert len(state.conversation_sessions.list()) == 1  # type: ignore[attr-defined]
    event_types = [event.event_type for event in state.event_log.events]  # type: ignore[attr-defined]
    assert "WHATSAPP_INBOUND_ALLOWED_BY_ALLOWLIST" in event_types
    assert "MESSAGE_RECEIVED" in event_types
