from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_app_state, reset_app_state
from app.core.config import get_settings
from app.domain.models import Assignment, Carrier, ConversationSession, Message, ShipmentRequest, Trip, TripOffer
from app.main import app


TEST_INTERNAL_API_KEY = "qa-internal-test-key"
OPERATOR_HEADERS = {
    "x-internal-api-key": TEST_INTERNAL_API_KEY,
    "x-operator-user-id": "user_operator",
    "x-operator-role": "operator",
}
UNAUTHENTICATED_HEADERS = {
    "x-internal-api-key": "",
    "x-operator-user-id": "",
    "x-operator-role": "",
}


@pytest.fixture(autouse=True)
def use_synthetic_internal_api_key(monkeypatch) -> Iterator[None]:  # noqa: ANN001
    """Keep API tests independent of developer .env secrets."""
    monkeypatch.setenv("INTERNAL_API_KEY", TEST_INTERNAL_API_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def client_with_clean_state() -> tuple[TestClient, object]:
    state = reset_app_state()
    return TestClient(app, headers=OPERATOR_HEADERS), state


def test_lists_pending_and_incomplete_shipments() -> None:
    client, state = client_with_clean_state()
    pending = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="PENDING_OPERATOR_REVIEW")
    )
    incomplete = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="INCOMPLETE", missing_critical_fields=["origin"])
    )

    pending_response = client.get("/api/v1/admin/ops/pending-shipments")
    incomplete_response = client.get("/api/v1/admin/ops/incomplete-shipments")

    assert pending_response.status_code == 200
    assert [item["id"] for item in pending_response.json()] == [pending.id]
    assert incomplete_response.status_code == 200
    assert [item["id"] for item in incomplete_response.json()] == [incomplete.id]


def test_validate_shipment_requires_operator_and_generates_event() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="PENDING_OPERATOR_REVIEW")
    )

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers=OPERATOR_HEADERS,
        json={"notes": "datos revisados"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "VALIDATED"
    assert state.shipment_requests.get(shipment.id).status == "VALIDATED"  # type: ignore[attr-defined, union-attr]
    assert state.event_log.events[-1].event_type == "LOAD_VALIDATED"  # type: ignore[attr-defined]
    assert state.event_log.events[-1].actor_id == "user_operator"  # type: ignore[attr-defined]


def test_mutating_admin_endpoint_requires_authenticated_operator() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="PENDING_OPERATOR_REVIEW"))  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers=UNAUTHENTICATED_HEADERS,
        json={"notes": "datos revisados"},
    )

    assert response.status_code == 401


def test_mutating_admin_endpoint_rejects_non_operator_role() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="PENDING_OPERATOR_REVIEW"))  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers={
            "x-internal-api-key": TEST_INTERNAL_API_KEY,
            "x-operator-user-id": "user_viewer",
            "x-operator-role": "viewer",
        },
        json={"notes": "datos revisados"},
    )

    assert response.status_code == 403


def test_shared_environment_uses_fixed_service_identity_not_claimed_operator(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("APP_ENV", "staging")
    get_settings.cache_clear()
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="PENDING_OPERATOR_REVIEW"))  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers={
            "x-internal-api-key": TEST_INTERNAL_API_KEY,
            "x-operator-user-id": "claimed-human-user",
            "x-operator-role": "admin",
        },
        json={"notes": "revision automatizada"},
    )

    assert response.status_code == 200
    assert state.event_log.events[-1].actor_id == "service:agro-backend-client"  # type: ignore[attr-defined]


def test_local_operator_headers_do_not_require_exposing_internal_key(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("INTERNAL_API_KEY", TEST_INTERNAL_API_KEY)
    get_settings.cache_clear()
    client = TestClient(app)

    response = client.get(
        "/api/v1/backoffice/overview",
        headers={"x-operator-user-id": "local-operator", "x-operator-role": "operator"},
    )

    assert response.status_code == 200


def test_shared_environment_fails_closed_without_internal_service_key(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    get_settings.cache_clear()
    client = TestClient(app)

    response = client.get(
        "/api/v1/backoffice/overview",
        headers={"x-operator-user-id": "claimed-human-user", "x-operator-role": "admin"},
    )

    assert response.status_code == 401


def test_chat_shipment_preview_returns_canonical_date_without_mutating_state(monkeypatch) -> None:  # noqa: ANN001
    buenos_aires = "2026-09-29T17:55:00-03:00"
    from app.api.routes import admin_ops as admin_ops_routes

    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-key")
    get_settings.cache_clear()
    headers = {**OPERATOR_HEADERS, "x-internal-api-key": "test-internal-key"}
    monkeypatch.setattr(admin_ops_routes, "datetime", type("FixedDateTime", (), {
        "now": staticmethod(lambda _timezone: datetime.fromisoformat(buenos_aires).astimezone(ZoneInfo("America/Argentina/Buenos_Aires"))),
    }))
    client, state = client_with_clean_state()
    before = {
        "shipments": len(state.shipment_requests.list()),  # type: ignore[attr-defined]
        "events": len(state.event_log.events),  # type: ignore[attr-defined]
        "messages": len(state.messages.list()),  # type: ignore[attr-defined]
    }

    response = client.post(
        "/api/v1/admin/shipments/chat-preview",
        headers=headers,
        json={"text": "Necesito transportar 45 cabezas de novillos desde Mar del Plata hasta Rosario el viernes"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pickup_date"] == "2026-10-02"
    assert payload["pickup_date_display"] == "viernes 02/10/2026"
    assert payload["origin"] == "Mar del Plata"
    assert payload["destination"] == "Rosario"
    assert payload["confirmation_summary"] == (
        "Tipo de carga: novillos\n"
        "Cantidad: 45 cabezas\n"
        "Origen: Mar del Plata\n"
        "Destino: Rosario\n"
        "Fecha: viernes 02/10/2026"
    )
    assert payload["missing_fields"] == []
    assert before == {
        "shipments": len(state.shipment_requests.list()),  # type: ignore[attr-defined]
        "events": len(state.event_log.events),  # type: ignore[attr-defined]
        "messages": len(state.messages.list()),  # type: ignore[attr-defined]
    }


def test_chat_shipment_preview_requires_operator_authentication() -> None:
    from app.api.dependencies import get_settings as dependency_settings

    dependency_settings.cache_clear()
    client, _state = client_with_clean_state()

    response = client.post(
        "/api/v1/admin/shipments/chat-preview",
        headers=UNAUTHENTICATED_HEADERS,
        json={"text": "45 cabezas de novillos el viernes"},
    )

    assert response.status_code == 401


def test_chat_shipment_preview_marks_missing_grain_unit() -> None:
    client, _state = client_with_clean_state()
    response = client.post(
        "/api/v1/admin/shipments/chat-preview",
        headers=OPERATOR_HEADERS,
        json={"text": "Necesito transportar 30 de soja desde Tandil hasta Rosario manana"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cargo_category"] == "GRAIN"
    assert payload["quantity_unit"] is None
    assert "unidad" in payload["missing_fields"]

    explicit_unit = client.post(
        "/api/v1/admin/shipments/chat-preview",
        headers=OPERATOR_HEADERS,
        json={"text": "Necesito transportar 30 toneladas de soja desde Tandil hasta Rosario manana"},
    )

    assert explicit_unit.status_code == 200
    explicit_payload = explicit_unit.json()
    assert explicit_payload["quantity_unit"] == "TON"
    assert explicit_payload["missing_fields"] == []
    assert "Cantidad: 30 toneladas" in explicit_payload["confirmation_summary"]


def test_test_session_status_reports_role_override_and_carrier(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("ENABLE_TEST_ROLE_SWITCHING", "true")
    get_settings.cache_clear()
    client, state = client_with_clean_state()
    state.carriers.add(  # type: ignore[attr-defined]
        Carrier(
            id="car_status",
            name="Carrier Status",
            contact_phone="+5491111111111",
            normalized_phone_number="+5491111111111",
        )
    )
    state.conversation_sessions.add(  # type: ignore[attr-defined]
        ConversationSession(
            channel="kapso",
            normalized_phone_number="+5491111111111",
            role_override="Operator",
        )
    )

    response = client.get(
        "/api/v1/admin/test/session-status?phone_number=+5491111111111",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "mode": "Operador",
        "role_override": "Operator",
        "phone_number": "+549***111",
        "carrier_detected": True,
        "carrier_id": "car_status",
        "active_test_run_id": None,
    }


def test_create_shipment_from_chat_creates_draft_and_event() -> None:
    client, state = client_with_clean_state()

    response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 40 cabezas de novillos de Azul a Liniers manana",
            "phone_number": "+5491135690073",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DRAFT"
    shipment = state.shipment_requests.get(payload["shipment_id"])  # type: ignore[attr-defined]
    assert shipment is not None
    assert shipment.status == "DRAFT"
    assert shipment.cargo_category == "LIVESTOCK"
    assert shipment.cargo_type == "novillos"
    assert shipment.quantity_unit == "HEAD"
    assert shipment.livestock_type == "novillos"
    assert shipment.quantity_estimate == 40
    assert shipment.operational_notes == "Necesito camion para 40 cabezas de novillos de Azul a Liniers manana"
    assert shipment.requires_human_review is False
    assert state.trip_offers.list() == []  # type: ignore[attr-defined]
    assert state.assignments.list() == []  # type: ignore[attr-defined]
    assert state.trips.list() == []  # type: ignore[attr-defined]
    event = state.event_log.events[-1]  # type: ignore[attr-defined]
    assert event.event_type == "SHIPMENT_DRAFT_CREATED_FROM_CHAT"
    assert event.entity_id == shipment.id
    assert event.new_state == "DRAFT"
    assert event.payload == {
        "text": "Necesito camion para 40 cabezas de novillos de Azul a Liniers manana",
        "phone_number": "+5491135690073",
        "source": "kapso",
        "cargo_category": "LIVESTOCK",
        "cargo_type": "novillos",
        "quantity_unit": "HEAD",
    }


def test_create_shipment_from_chat_supports_grain_load() -> None:
    client, state = client_with_clean_state()

    response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 30 toneladas de soja de Tandil a Rosario manana",
            "phone_number": "+5491135690073",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DRAFT"
    assert payload["cargo_category"] == "GRAIN"
    assert payload["cargo_type"] == "soja"
    assert payload["quantity_unit"] == "TON"
    shipment = state.shipment_requests.get(payload["shipment_id"])  # type: ignore[attr-defined]
    assert shipment is not None
    assert shipment.cargo_category == "GRAIN"
    assert shipment.cargo_type == "soja"
    assert shipment.quantity_unit == "TON"
    assert shipment.livestock_type is None
    assert shipment.quantity_estimate == 30
    event = state.event_log.events[-1]  # type: ignore[attr-defined]
    assert event.payload["cargo_category"] == "GRAIN"
    assert event.payload["cargo_type"] == "soja"
    assert event.payload["quantity_unit"] == "TON"


def test_create_shipment_from_chat_allows_grain_without_quantity() -> None:
    client, state = client_with_clean_state()

    response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={"text": "Necesito camion para soja de Tandil a Rosario manana"},
    )

    assert response.status_code == 200
    shipment = state.shipment_requests.get(response.json()["shipment_id"])  # type: ignore[attr-defined]
    assert shipment is not None
    assert shipment.status == "DRAFT"
    assert shipment.cargo_category == "GRAIN"
    assert shipment.cargo_type == "soja"
    assert shipment.quantity_unit is None
    assert shipment.quantity_estimate is None


def test_create_shipment_from_chat_does_not_block_missing_data() -> None:
    client, state = client_with_clean_state()

    response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={"text": "Necesito camion para manana"},
    )

    assert response.status_code == 200
    shipment = state.shipment_requests.get(response.json()["shipment_id"])  # type: ignore[attr-defined]
    assert shipment is not None
    assert shipment.status == "DRAFT"
    assert shipment.cargo_category is None
    assert shipment.cargo_type is None
    assert shipment.quantity_unit is None
    assert shipment.livestock_type is None
    assert shipment.quantity_estimate is None
    assert shipment.operational_notes == "Necesito camion para manana"


def test_create_shipment_from_chat_is_idempotent() -> None:
    client, state = client_with_clean_state()
    payload = {
        "text": "Necesito camion para 25 cabezas de vacas",
        "phone_number": "+5491135690073",
        "idempotency_key": "chat_draft_1",
    }

    first = client.post("/api/v1/shipment-requests/from-chat", headers=OPERATOR_HEADERS, json=payload)
    second = client.post("/api/v1/shipment-requests/from-chat", headers=OPERATOR_HEADERS, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(state.shipment_requests.list()) == 1  # type: ignore[attr-defined]
    assert len(state.event_log.events) == 1  # type: ignore[attr-defined]
    shipment = state.shipment_requests.list()[0]  # type: ignore[attr-defined]
    assert shipment.livestock_type == "vacas"
    assert shipment.quantity_estimate == 25


def test_lists_recent_chat_drafts_for_phone_number() -> None:
    client, _ = client_with_clean_state()
    other_response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 20 novillos",
            "phone_number": "+5492222222222",
        },
    )
    target_response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 110 cabezas de vacas de Tandil a Cañuelas mañana",
            "phone_number": "541135690073",
        },
    )

    response = client.get(
        "/api/v1/admin/shipments/from-chat/recent",
        headers=OPERATOR_HEADERS,
        params={"phone_number": "+5491135690073"},
    )

    assert other_response.status_code == 200
    assert target_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["shipment_id"] == target_response.json()["shipment_id"]
    assert payload[0]["status"] == "DRAFT"
    assert payload[0]["livestock_type"] == "vacas"
    assert payload[0]["cargo_category"] == "LIVESTOCK"
    assert payload[0]["cargo_type"] == "vacas"
    assert payload[0]["quantity_unit"] == "HEAD"
    assert payload[0]["quantity_estimate"] == "110"
    assert payload[0]["operational_notes"] == "Necesito camion para 110 cabezas de vacas de Tandil a Cañuelas mañana"
    assert payload[0]["source_phone_number"] == "541135690073"


def test_list_recent_chat_drafts_falls_back_when_phone_does_not_match() -> None:
    client, _ = client_with_clean_state()
    target_response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={
            "text": "Necesito camion para 112 cabezas de vacas",
            "phone_number": "541135690073",
        },
    )

    response = client.get(
        "/api/v1/admin/shipments/from-chat/recent",
        headers=OPERATOR_HEADERS,
        params={"phone_number": "12014298268"},
    )

    assert target_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["shipment_id"] == target_response.json()["shipment_id"]
    assert payload[0]["quantity_estimate"] == "112"
    assert payload[0]["source_phone_number"] == "541135690073"


def test_list_recent_chat_drafts_requires_operator() -> None:
    client, _ = client_with_clean_state()

    response = client.get("/api/v1/admin/shipments/from-chat/recent", headers=UNAUTHENTICATED_HEADERS)

    assert response.status_code == 401


def test_lists_draft_shipments_for_operator_ordered_desc() -> None:
    client, state = client_with_clean_state()
    older = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_older_draft",
            status="DRAFT",
            livestock_type="novillos",
            quantity_estimate=40,
            operational_notes="Draft viejo",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    newer = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_newer_draft",
            status="DRAFT",
            livestock_type="toros",
            quantity_estimate=500,
            operational_notes="Draft nuevo",
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
    )
    state.shipment_requests.add(ShipmentRequest(id="sr_validated", status="VALIDATED"))  # type: ignore[attr-defined]

    response = client.get("/api/v1/admin/shipments/drafts", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    assert [item["shipment_id"] for item in response.json()] == [newer.id, older.id]
    assert response.json()[0]["livestock_type"] == "toros"
    assert response.json()[0]["quantity_estimate"] == "500"


def test_list_draft_shipments_requires_operator() -> None:
    client, _ = client_with_clean_state()

    response = client.get("/api/v1/admin/shipments/drafts", headers=UNAUTHENTICATED_HEADERS)

    assert response.status_code == 401


def test_chat_draft_can_be_validated_by_operator() -> None:
    client, state = client_with_clean_state()
    draft_response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={"text": "Necesito camion para 40 cabezas de novillos"},
    )

    validate_response = client.post(
        f"/api/v1/shipment-requests/{draft_response.json()['shipment_id']}/validate",
        headers=OPERATOR_HEADERS,
        json={"notes": "confirmado desde chat"},
    )

    assert validate_response.status_code == 200
    assert validate_response.json()["status"] == "VALIDATED"
    shipment = state.shipment_requests.get(draft_response.json()["shipment_id"])  # type: ignore[attr-defined]
    assert shipment is not None
    assert shipment.status == "VALIDATED"


def test_draft_validated_then_published_by_operator() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_1", name="Carrier 1", contact_phone="+5491111111111"))  # type: ignore[attr-defined]
    draft_response = client.post(
        "/api/v1/shipment-requests/from-chat",
        headers=OPERATOR_HEADERS,
        json={"text": "Necesito camion para 500 cabezas de toros de Entre Rios a Buenos Aires"},
    )
    shipment_id = draft_response.json()["shipment_id"]

    validate_response = client.post(
        f"/api/v1/shipment-requests/{shipment_id}/validate",
        headers=OPERATOR_HEADERS,
        json={"notes": "datos minimos revisados", "idempotency_key": "validate_draft_1"},
    )
    publish_response = client.post(
        f"/api/v1/shipment-requests/{shipment_id}/publish",
        headers=OPERATOR_HEADERS,
        json={"carrier_ids": ["car_1"], "idempotency_key": "publish_draft_1"},
    )

    assert validate_response.status_code == 200
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "PUBLISHED"
    shipment = state.shipment_requests.get(shipment_id)  # type: ignore[attr-defined]
    assert shipment is not None
    assert shipment.status == "PUBLISHED"
    assert shipment.livestock_type == "toros"
    assert "LOAD_VALIDATED" in [event.event_type for event in state.event_log.events]  # type: ignore[attr-defined]
    assert "LOAD_PUBLISHED" in [event.event_type for event in state.event_log.events]  # type: ignore[attr-defined]


def test_publish_draft_without_validation_is_rejected() -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_1", name="Carrier 1", contact_phone="+5491111111111"))  # type: ignore[attr-defined]
    shipment = state.shipment_requests.add(ShipmentRequest(status="DRAFT"))  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={"carrier_ids": ["car_1"]},
    )

    assert response.status_code == 409
    assert state.shipment_requests.get(shipment.id).status == "DRAFT"  # type: ignore[attr-defined, union-attr]


def test_validate_shipment_with_missing_fields_without_override_is_rejected() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            status="PENDING_OPERATOR_REVIEW",
            missing_critical_fields=["destination"],
        )
    )

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers=OPERATOR_HEADERS,
        json={},
    )

    assert response.status_code == 409
    assert "missing critical fields" in response.json()["detail"]


def test_publish_shipment_records_broadcast_and_carrier_notifications(legacy_broadcast, ) -> None:
    client, state = client_with_clean_state()
    state.carriers.add(Carrier(id="car_1", name="Carrier 1", contact_phone="+5491111111111"))  # type: ignore[attr-defined]
    state.carriers.add(Carrier(id="car_2", name="Carrier 2", contact_phone="+5492222222222"))  # type: ignore[attr-defined]
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="VALIDATED")
    )

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={
            "carrier_ids": ["car_1", "car_2"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PUBLISHED"
    assert response.json()["notifications_queued"] == 2
    assert response.json()["notifications_sent"] == 2
    assert response.json()["notifications_failed"] == 0
    assert response.json()["event_types"] == [
        "LOAD_PUBLISHED",
        "BROADCAST_SENT",
        "CARRIER_NOTIFIED",
        "CARRIER_NOTIFIED",
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_SENT",
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_SENT",
    ]


def test_publish_shipment_is_idempotent_for_retried_operator_action(legacy_broadcast, ) -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="VALIDATED")
    )
    payload = {
        "carrier_ids": ["car_1"],
        "idempotency_key": "publish_1",
    }

    first = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json=payload,
    )
    second = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(state.event_log.events) == 5  # type: ignore[attr-defined]
    assert second.json()["event_types"] == ["LOAD_PUBLISHED", "BROADCAST_SENT", "CARRIER_NOTIFIED"]
    assert second.json()["notifications_sent"] == 0


def test_publish_shipment_with_no_carriers_is_rejected_without_state_change(legacy_broadcast, ) -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="VALIDATED"))  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={"carrier_ids": []},
    )

    assert response.status_code == 409
    assert "without carriers" in response.json()["detail"]
    assert state.shipment_requests.get(shipment.id).status == "VALIDATED"  # type: ignore[attr-defined, union-attr]
    assert state.event_log.events == ()  # type: ignore[attr-defined]


def test_lists_offers_for_shipment() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
        )
    )

    response = client.get(f"/api/v1/shipment-requests/{shipment.id}/offers")

    assert response.status_code == 200
    assert response.json()[0]["id"] == offer.id


def test_lists_published_shipment_without_offers() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_without_offers",
                status="PUBLISHED",
                livestock_type="novillos",
                quantity_unit="HEAD",
                quantity_estimate=35,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    state.shipment_requests.add(ShipmentRequest(id="sr_validated", status="VALIDATED"))  # type: ignore[attr-defined]

    response = client.get("/api/v1/admin/shipments/with-offers")

    assert response.status_code == 200
    assert response.json() == [
        {
            "shipment_id": shipment.id,
            "status": "PUBLISHED",
            "cargo_category": "LIVESTOCK",
            "cargo_type": "novillos",
            "quantity_unit": "HEAD",
            "livestock_type": "novillos",
            "quantity_estimate": "35",
            "offers": [],
        }
    ]


def test_lists_shipment_with_multiple_active_offers_ordered_desc() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_with_offers",
            status="MATCHING",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    older_offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            id="off_older",
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
            created_at=datetime(2026, 5, 1, 13, 0, tzinfo=UTC),
        )
    )
    newer_offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            id="off_newer",
            shipment_request_id=shipment.id,
            carrier_id="car_2",
            response_type="DECLINED",
            created_at=datetime(2026, 5, 1, 14, 0, tzinfo=UTC),
        )
    )
    deleted_offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            id="off_deleted",
            shipment_request_id=shipment.id,
            carrier_id="car_deleted",
            response_type="INTERESTED",
            created_at=datetime(2026, 5, 1, 15, 0, tzinfo=UTC),
        )
    )
    deleted_offer.soft_delete()
    state.trip_offers.save(deleted_offer)  # type: ignore[attr-defined]

    response = client.get("/api/v1/admin/shipments/with-offers")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["shipment_id"] == shipment.id
    assert [offer["trip_offer_id"] for offer in payload[0]["offers"]] == [newer_offer.id, older_offer.id]


def test_lists_shipment_with_active_assignment_without_selectable_offers() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_active_assignment", status="MATCHING")
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            id="off_active_assignment",
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
        )
    )
    state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            trip_offer_id="off_active_assignment",
            selected_by_user_id="user_operator",
            status="PROPOSED",
        )
    )

    response = client.get("/api/v1/admin/shipments/with-offers")

    assert response.status_code == 200
    assert response.json()[0]["shipment_id"] == shipment.id
    assert response.json()[0]["offers"] == []


def test_lists_shipments_with_offers_orders_shipments_by_created_at_desc() -> None:
    client, state = client_with_clean_state()
    older = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_older", status="PUBLISHED", created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
    )
    newer = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_newer", status="MATCHING", created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC))
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=older.id, carrier_id="car_1", response_type="INTERESTED")
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=newer.id, carrier_id="car_2", response_type="INTERESTED")
    )

    response = client.get("/api/v1/admin/shipments/with-offers")

    assert response.status_code == 200
    assert [item["shipment_id"] for item in response.json()] == [newer.id, older.id]


def test_select_offer_creates_assignment_trip_and_events() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
        )
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id, "idempotency_key": "select_offer_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assignment_status"] == "PROPOSED"
    assert payload["trip_status"] == "PLANNED"
    assert payload["carrier_id"] == "car_1"
    assert payload["trip_offer_id"] == offer.id
    assert payload["event_types"] == [
        "ASSIGNMENT_CREATED",
        "ASSIGNMENT_SELECTED",
        "TRIP_CREATED",
    ]
    assignments = state.assignments.list()  # type: ignore[attr-defined]
    trips = state.trips.list()  # type: ignore[attr-defined]
    assert len(assignments) == 1
    assert assignments[0].shipment_request_id == shipment.id
    assert assignments[0].trip_offer_id == offer.id
    assert assignments[0].carrier_id == offer.carrier_id
    assert len(trips) == 1
    assert trips[0].assignment_id == assignments[0].id


def test_producer_lists_only_owned_shipments() -> None:
    client, state = client_with_clean_state()
    owned = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            status="MATCHING",
            producer_phone_number="+5491111111111",
            cargo_category="GRAIN",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
        )
    )
    state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            status="MATCHING",
            producer_phone_number="+5492222222222",
            cargo_category="LIVESTOCK",
            cargo_type="vacas",
            quantity_unit="HEAD",
            quantity_estimate=40,
        )
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=owned.id, carrier_id="car_1", response_type="INTERESTED")
    )

    response = client.get("/api/v1/producer/shipments?phone_number=+5491111111111")

    assert response.status_code == 200
    assert [item["shipment_id"] for item in response.json()] == [owned.id]
    assert response.json()[0]["interested_offers_count"] == 1


def test_producer_lists_interested_offers_for_owned_matching_shipments() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            status="MATCHING",
            producer_phone_number="+5491111111111",
            cargo_category="GRAIN",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
        )
    )
    own_offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_2", response_type="DECLINED")
    )

    response = client.get("/api/v1/producer/shipments/interested-offers?phone_number=+5491111111111")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["index"] == 1
    assert payload[0]["shipment_id"] == shipment.id
    assert payload[0]["trip_offer_id"] == own_offer.id
    assert payload[0]["response_type"] == "INTERESTED"


def test_producer_dashboard_summarizes_current_and_past_operations() -> None:
    client, state = client_with_clean_state()
    current_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_prod_current",
            status="MATCHING",
            producer_phone_number="+5491111111111",
            cargo_type="vacas",
            quantity_unit="HEAD",
            quantity_estimate=50,
        )
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=current_shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    past_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_prod_past",
            status="CLOSED",
            producer_phone_number="+5491111111111",
            cargo_type="soja",
            quantity_unit="TON",
            quantity_estimate=30,
        )
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_prod_past",
            shipment_request_id=past_shipment.id,
            carrier_id="car_past",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_prod_past",
            shipment_request_id=past_shipment.id,
            assignment_id=assignment.id,
            carrier_id="car_past",
            status="COMPLETED",
        )
    )

    response = client.get("/api/v1/producer/dashboard?phone_number=+5491111111111")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_shipments"] == 2
    assert payload["pending_interested_offers"] == 1
    assert len(payload["current_operations"]) == 1
    assert payload["current_operations"][0]["shipment_id"] == "sr_prod_current"
    assert len(payload["past_operations"]) == 1
    assert payload["past_operations"][0]["trip_status"] == "COMPLETED"


def test_carrier_dashboard_lists_current_and_past_trips() -> None:
    client, state = client_with_clean_state()
    carrier = state.carriers.add(  # type: ignore[attr-defined]
        Carrier(id="car_dash", name="Carrier Dash", contact_phone="+5491111111111")
    )
    current_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_car_current", status="ASSIGNED", producer_phone_number="+5492222222222")
    )
    current_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_car_current",
            shipment_request_id=current_shipment.id,
            carrier_id=carrier.id,
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_car_current",
            shipment_request_id=current_shipment.id,
            assignment_id=current_assignment.id,
            carrier_id=carrier.id,
            status="IN_TRANSIT",
        )
    )
    past_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_car_past", status="CLOSED", producer_phone_number="+5493333333333")
    )
    past_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_car_past",
            shipment_request_id=past_shipment.id,
            carrier_id=carrier.id,
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_car_past",
            shipment_request_id=past_shipment.id,
            assignment_id=past_assignment.id,
            carrier_id=carrier.id,
            status="COMPLETED",
        )
    )
    state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=current_shipment.id, carrier_id=carrier.id, response_type="INTERESTED")
    )

    response = client.get(f"/api/v1/carrier/dashboard/{carrier.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["carrier_id"] == carrier.id
    assert payload["active_trips"] == 1
    assert payload["completed_trips"] == 1
    assert payload["total_offers"] == 1
    assert len(payload["current_operations"]) == 1
    assert payload["current_operations"][0]["trip_status"] == "IN_TRANSIT"
    assert len(payload["past_operations"]) == 1


def test_producer_accepts_interested_offer_and_confirms_assignment_trip() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="MATCHING", producer_phone_number="+5491111111111")
    )
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/offers/{offer.id}/accept",
        json={"phone_number": "+5491111111111", "idempotency_key": "producer_accept_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assignment_status"] == "CONFIRMED"
    assert payload["trip_status"] == "PLANNED"
    assert payload["shipment_status"] == "ASSIGNED"
    assert payload["already_active_assignment"] is False
    assert payload["event_types"][:5] == [
        "PRODUCER_OFFER_ACCEPTED",
        "ASSIGNMENT_CREATED",
        "TRIP_CREATED",
        "MARKETPLACE_MATCH_CONFIRMED",
        "ASSIGNMENT_CONFIRMED",
    ]
    assert payload["event_types"][5:] == [
        "CARRIER_NOTIFICATION_REQUESTED",
        "CARRIER_NOTIFICATION_FAILED",
        "PRODUCER_NOTIFICATION_REQUESTED",
        "PRODUCER_NOTIFICATION_SENT",
    ]
    assert state.shipment_requests.get(shipment.id).status == "ASSIGNED"  # type: ignore[attr-defined, union-attr]
    assignments = state.assignments.list()  # type: ignore[attr-defined]
    trips = state.trips.list()  # type: ignore[attr-defined]
    assert len(assignments) == 1
    assert assignments[0].status == "CONFIRMED"
    assert assignments[0].selected_by_user_id == "producer:+5491111111111"
    assert len(trips) == 1
    assert trips[0].assignment_id == assignments[0].id


def test_producer_accept_offer_is_idempotent() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="MATCHING", producer_phone_number="+5491111111111")
    )
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    payload = {"phone_number": "+5491111111111", "idempotency_key": "producer_accept_retry"}

    first = client.post(f"/api/v1/shipments/{shipment.id}/offers/{offer.id}/accept", json=payload)
    second = client.post(f"/api/v1/shipments/{shipment.id}/offers/{offer.id}/accept", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["assignment_id"] == first.json()["assignment_id"]
    assert second.json()["trip_id"] == first.json()["trip_id"]
    assert len(state.assignments.list()) == 1  # type: ignore[attr-defined]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]
    assert len(state.event_log.events) == 9  # type: ignore[attr-defined]
    assert [event.event_type for event in state.event_log.events].count("CARRIER_NOTIFICATION_FAILED") == 1  # type: ignore[attr-defined]
    assert [event.event_type for event in state.event_log.events].count("PRODUCER_NOTIFICATION_SENT") == 1  # type: ignore[attr-defined]


def test_other_producer_cannot_accept_offer() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="MATCHING", producer_phone_number="+5491111111111")
    )
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/offers/{offer.id}/accept",
        json={"phone_number": "+5492222222222"},
    )

    assert response.status_code == 409
    assert "does not belong" in response.json()["detail"]
    assert state.assignments.list() == []  # type: ignore[attr-defined]
    assert state.trips.list() == []  # type: ignore[attr-defined]


def test_select_offer_rejects_offer_from_different_shipment() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    other_shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=other_shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
        )
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id},
    )

    assert response.status_code == 409
    assert "does not belong" in response.json()["detail"]
    assert state.assignments.list() == []  # type: ignore[attr-defined]
    assert state.trips.list() == []  # type: ignore[attr-defined]


def test_select_offer_missing_offer_returns_not_found() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": "off_missing"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Trip offer not found"
    assert state.assignments.list() == []  # type: ignore[attr-defined]
    assert state.trips.list() == []  # type: ignore[attr-defined]


def test_select_offer_requires_matching_shipment() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="PUBLISHED"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
        )
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id},
    )

    assert response.status_code == 409
    assert "MATCHING" in response.json()["detail"]
    assert state.assignments.list() == []  # type: ignore[attr-defined]
    assert state.trips.list() == []  # type: ignore[attr-defined]


def test_select_offer_is_idempotent_for_retried_operator_action() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            response_type="INTERESTED",
        )
    )
    payload = {"trip_offer_id": offer.id, "idempotency_key": "select_offer_retry"}

    first = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json=payload,
    )
    second = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["assignment_id"] == first.json()["assignment_id"]
    assert second.json()["trip_id"] == first.json()["trip_id"]
    assert len(state.assignments.list()) == 1  # type: ignore[attr-defined]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]
    assert len(state.event_log.events) == 3  # type: ignore[attr-defined]


def test_select_offer_returns_existing_proposed_assignment_without_duplication() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    selected_offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    other_offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_2", response_type="INTERESTED")
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            trip_offer_id=selected_offer.id,
            selected_by_user_id="user_operator",
            status="PROPOSED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            status="PLANNED",
        )
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": other_offer.id, "idempotency_key": "select_existing_proposed"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assignment_id"] == assignment.id
    assert payload["trip_id"] == trip.id
    assert payload["carrier_id"] == "car_1"
    assert payload["trip_offer_id"] == selected_offer.id
    assert payload["event_types"] == []
    assert len(state.assignments.list()) == 1  # type: ignore[attr-defined]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]
    assert len(state.event_log.events) == 0  # type: ignore[attr-defined]


def test_select_offer_returns_existing_pending_assignment_without_duplication() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            trip_offer_id=offer.id,
            selected_by_user_id="user_operator",
            status="PENDING_CONFIRMATION",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            status="PLANNED",
        )
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id},
    )

    assert response.status_code == 200
    assert response.json()["assignment_id"] == assignment.id
    assert response.json()["trip_id"] == trip.id
    assert response.json()["event_types"] == []
    assert len(state.assignments.list()) == 1  # type: ignore[attr-defined]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]
    assert len(state.event_log.events) == 0  # type: ignore[attr-defined]


def test_select_offer_returns_existing_confirmed_assignment_without_duplication() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="ASSIGNED"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            trip_offer_id=offer.id,
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            status="PLANNED",
        )
    )

    response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id},
    )

    assert response.status_code == 200
    assert response.json()["assignment_id"] == assignment.id
    assert response.json()["trip_id"] == trip.id
    assert response.json()["assignment_status"] == "CONFIRMED"
    assert response.json()["event_types"] == []
    assert len(state.assignments.list()) == 1  # type: ignore[attr-defined]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]
    assert len(state.event_log.events) == 0  # type: ignore[attr-defined]


def test_lists_pending_assignments_for_operator_ordered_desc() -> None:
    client, state = client_with_clean_state()
    older_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_older", status="MATCHING", livestock_type="novillos", quantity_estimate=35)
    )
    newer_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_newer", status="MATCHING", livestock_type="vacas", quantity_estimate=130)
    )
    older_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_older",
            shipment_request_id=older_shipment.id,
            carrier_id="car_1",
            trip_offer_id="off_older",
            selected_by_user_id="user_operator",
            status="PROPOSED",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    newer_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_newer",
            shipment_request_id=newer_shipment.id,
            carrier_id="car_2",
            trip_offer_id="off_newer",
            selected_by_user_id="user_operator",
            status="PENDING_CONFIRMATION",
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_newer",
            shipment_request_id=newer_shipment.id,
            assignment_id=newer_assignment.id,
            carrier_id="car_2",
            status="PLANNED",
        )
    )
    state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_confirmed",
            shipment_request_id=older_shipment.id,
            carrier_id="car_3",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
        )
    )

    response = client.get("/api/v1/admin/assignments/pending", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert [item["assignment_id"] for item in payload] == [newer_assignment.id]
    assert payload[0]["shipment_id"] == newer_shipment.id
    assert payload[0]["quantity_estimate"] == "130"
    assert payload[0]["trip_id"] == trip.id
    assert payload[0]["trip_status"] == "PLANNED"


def test_lists_pending_assignments_uses_canonical_assignment_per_shipment() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_canonical_pending", status="ASSIGNED", livestock_type="vacas", quantity_estimate=130)
    )
    state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_old_proposed",
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            selected_by_user_id="user_operator",
            status="PROPOSED",
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
    )
    confirmed_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_canonical_confirmed",
            shipment_request_id=shipment.id,
            carrier_id="car_2",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_canonical_confirmed",
            shipment_request_id=shipment.id,
            assignment_id=confirmed_assignment.id,
            carrier_id=confirmed_assignment.carrier_id,
            status="PLANNED",
        )
    )

    response = client.get("/api/v1/admin/assignments/pending", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    assert response.json() == []


def test_list_pending_assignments_requires_operator() -> None:
    client, _ = client_with_clean_state()

    response = client.get("/api/v1/admin/assignments/pending", headers=UNAUTHENTICATED_HEADERS)

    assert response.status_code == 401


def test_lists_active_assignments_including_confirmed_for_operator() -> None:
    client, state = client_with_clean_state()
    proposed_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_active_proposed", status="MATCHING", livestock_type="vacas", quantity_estimate=130)
    )
    confirmed_shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_active_confirmed", status="ASSIGNED", livestock_type="novillos", quantity_estimate=45)
    )
    cancelled_shipment = state.shipment_requests.add(ShipmentRequest(id="sr_cancelled", status="MATCHING"))  # type: ignore[attr-defined]
    proposed_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_active_proposed",
            shipment_request_id=proposed_shipment.id,
            carrier_id="car_1",
            trip_offer_id="off_1",
            selected_by_user_id="user_operator",
            status="PROPOSED",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    confirmed_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_active_confirmed",
            shipment_request_id=confirmed_shipment.id,
            carrier_id="car_2",
            trip_offer_id="off_2",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
    )
    state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_cancelled",
            shipment_request_id=cancelled_shipment.id,
            carrier_id="car_3",
            selected_by_user_id="user_operator",
            status="CANCELLED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_active_confirmed",
            shipment_request_id=confirmed_shipment.id,
            assignment_id=confirmed_assignment.id,
            carrier_id=confirmed_assignment.carrier_id,
            status="PLANNED",
        )
    )

    response = client.get("/api/v1/admin/assignments/active", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert [item["assignment_id"] for item in payload] == [confirmed_assignment.id, proposed_assignment.id]
    assert payload[0]["shipment_id"] == confirmed_shipment.id
    assert payload[0]["shipment_status"] == "ASSIGNED"
    assert payload[0]["trip_id"] == trip.id
    assert payload[0]["trip_status"] == "PLANNED"
    assert payload[0]["quantity_estimate"] == "45"


def test_lists_active_assignments_uses_canonical_assignment_per_shipment() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_canonical_active", status="ASSIGNED", livestock_type="vacas", quantity_estimate=130)
    )
    old_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_canonical_old_proposed",
            shipment_request_id=shipment.id,
            carrier_id="car_old",
            selected_by_user_id="user_operator",
            status="PROPOSED",
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
    )
    confirmed_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_canonical_active_confirmed",
            shipment_request_id=shipment.id,
            carrier_id="car_confirmed",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_canonical_old",
            shipment_request_id=shipment.id,
            assignment_id=old_assignment.id,
            carrier_id=old_assignment.carrier_id,
            status="PLANNED",
        )
    )
    confirmed_trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_canonical_confirmed",
            shipment_request_id=shipment.id,
            assignment_id=confirmed_assignment.id,
            carrier_id=confirmed_assignment.carrier_id,
            status="PLANNED",
        )
    )

    response = client.get("/api/v1/admin/assignments/active", headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["assignment_id"] == confirmed_assignment.id
    assert payload[0]["trip_id"] == confirmed_trip.id
    assert payload[0]["carrier_id"] == "car_confirmed"


def test_list_active_assignments_requires_operator() -> None:
    client, _ = client_with_clean_state()

    response = client.get("/api/v1/admin/assignments/active", headers=UNAUTHENTICATED_HEADERS)

    assert response.status_code == 401


def test_lookup_operation_by_assignment_trip_and_shipment_ids() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(
            id="sr_lookup",
            status="MATCHING",
            livestock_type="vacas",
            quantity_estimate=130,
            operational_notes="Carga lookup",
        )
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_lookup",
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            trip_offer_id="off_lookup",
            selected_by_user_id="user_operator",
            status="PROPOSED",
        )
    )
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_lookup",
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=assignment.carrier_id,
            status="PLANNED",
        )
    )

    by_assignment = client.get(f"/api/v1/admin/operations/lookup/{assignment.id}", headers=OPERATOR_HEADERS)
    by_trip = client.get(f"/api/v1/admin/operations/lookup/{trip.id}", headers=OPERATOR_HEADERS)
    by_shipment = client.get(f"/api/v1/admin/operations/lookup/{shipment.id}", headers=OPERATOR_HEADERS)

    assert by_assignment.status_code == 200
    assert by_trip.status_code == 200
    assert by_shipment.status_code == 200
    assert by_assignment.json() == by_trip.json() == by_shipment.json()
    payload = by_assignment.json()
    assert payload["shipment_id"] == shipment.id
    assert payload["assignment_id"] == assignment.id
    assert payload["trip_id"] == trip.id
    assert payload["carrier_id"] == "car_1"
    assert payload["operational_notes"] == "Carga lookup"


def test_lookup_operation_returns_canonical_assignment_for_old_trip_or_assignment_id() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(id="sr_lookup_canonical", status="ASSIGNED", livestock_type="vacas", quantity_estimate=130)
    )
    old_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_lookup_old",
            shipment_request_id=shipment.id,
            carrier_id="car_old",
            selected_by_user_id="user_operator",
            status="PROPOSED",
            created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
    )
    confirmed_assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_lookup_confirmed",
            shipment_request_id=shipment.id,
            carrier_id="car_confirmed",
            selected_by_user_id="user_operator",
            status="CONFIRMED",
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    old_trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_lookup_old",
            shipment_request_id=shipment.id,
            assignment_id=old_assignment.id,
            carrier_id=old_assignment.carrier_id,
            status="PLANNED",
        )
    )
    confirmed_trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            id="trip_lookup_confirmed",
            shipment_request_id=shipment.id,
            assignment_id=confirmed_assignment.id,
            carrier_id=confirmed_assignment.carrier_id,
            status="PLANNED",
        )
    )

    by_old_assignment = client.get(f"/api/v1/admin/operations/lookup/{old_assignment.id}", headers=OPERATOR_HEADERS)
    by_old_trip = client.get(f"/api/v1/admin/operations/lookup/{old_trip.id}", headers=OPERATOR_HEADERS)
    by_shipment = client.get(f"/api/v1/admin/operations/lookup/{shipment.id}", headers=OPERATOR_HEADERS)

    assert by_old_assignment.status_code == 200
    assert by_old_trip.status_code == 200
    assert by_shipment.status_code == 200
    assert by_old_assignment.json() == by_old_trip.json() == by_shipment.json()
    assert by_shipment.json()["assignment_id"] == confirmed_assignment.id
    assert by_shipment.json()["trip_id"] == confirmed_trip.id
    assert by_shipment.json()["carrier_id"] == "car_confirmed"


def test_lookup_operation_missing_or_inactive_returns_not_found() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(id="sr_inactive", status="MATCHING"))  # type: ignore[attr-defined]
    state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            id="asg_inactive",
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            selected_by_user_id="user_operator",
            status="CANCELLED",
        )
    )

    missing = client.get("/api/v1/admin/operations/lookup/trip_missing", headers=OPERATOR_HEADERS)
    inactive = client.get(f"/api/v1/admin/operations/lookup/{shipment.id}", headers=OPERATOR_HEADERS)

    assert missing.status_code == 404
    assert inactive.status_code == 404
    assert missing.json()["detail"] == "Active operation not found"


def test_lookup_operation_requires_operator() -> None:
    client, _ = client_with_clean_state()

    response = client.get("/api/v1/admin/operations/lookup/sr_1", headers=UNAUTHENTICATED_HEADERS)

    assert response.status_code == 401


def test_confirm_assignment_creates_event_log_and_planned_trip() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            selected_by_user_id="user_operator",
        )
    )

    response = client.post(
        f"/api/v1/assignments/{assignment.id}/confirm",
        headers=OPERATOR_HEADERS,
        json={
            "confirmation_notes": "productor y transportista confirmados",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assignment_status"] == "CONFIRMED"
    assert payload["trip_status"] == "PLANNED"
    assert payload["event_types"] == [
        "ASSIGNMENT_CREATED",
        "ASSIGNMENT_CONFIRMED",
        "TRIP_CREATED",
        "ASSIGNMENT_CONFIRMED",
    ]
    assert state.shipment_requests.get(shipment.id).status == "ASSIGNED"  # type: ignore[attr-defined, union-attr]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]


def test_confirm_assignment_reuses_trip_created_by_offer_selection() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="MATCHING"))  # type: ignore[attr-defined]
    offer = state.trip_offers.add(  # type: ignore[attr-defined]
        TripOffer(shipment_request_id=shipment.id, carrier_id="car_1", response_type="INTERESTED")
    )
    select_response = client.post(
        f"/api/v1/shipments/{shipment.id}/select-offer",
        headers=OPERATOR_HEADERS,
        json={"trip_offer_id": offer.id, "idempotency_key": "select_for_confirm"},
    )
    selected_trip_id = select_response.json()["trip_id"]
    assignment_id = select_response.json()["assignment_id"]

    confirm_response = client.post(
        f"/api/v1/assignments/{assignment_id}/confirm",
        headers=OPERATOR_HEADERS,
        json={
            "confirmation_notes": "confirmado manualmente",
            "idempotency_key": "confirm_selected_assignment",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert payload["assignment_status"] == "CONFIRMED"
    assert payload["trip_id"] == selected_trip_id
    assert payload["trip_status"] == "PLANNED"
    assert payload["event_types"] == [
        "ASSIGNMENT_CREATED",
        "ASSIGNMENT_CONFIRMED",
        "ASSIGNMENT_CONFIRMED",
    ]
    assert state.assignments.get(assignment_id).status == "CONFIRMED"  # type: ignore[attr-defined, union-attr]
    assert state.shipment_requests.get(shipment.id).status == "ASSIGNED"  # type: ignore[attr-defined, union-attr]
    assert len(state.trips.list()) == 1  # type: ignore[attr-defined]


def test_confirm_assignment_fails_if_shipment_does_not_exist() -> None:
    client, state = client_with_clean_state()
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id="sr_missing",
            carrier_id="car_1",
            selected_by_user_id="user_operator",
        )
    )

    response = client.post(
        f"/api/v1/assignments/{assignment.id}/confirm",
        headers=OPERATOR_HEADERS,
        json={"confirmation_notes": "no shipment"},
    )

    assert response.status_code == 404
    assert len(state.trips.list()) == 0  # type: ignore[attr-defined]


def test_confirm_assignment_fails_if_shipment_state_is_not_matching() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="VALIDATED"))  # type: ignore[attr-defined]
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            selected_by_user_id="user_operator",
        )
    )

    response = client.post(
        f"/api/v1/assignments/{assignment.id}/confirm",
        headers=OPERATOR_HEADERS,
        json={"confirmation_notes": "too early"},
    )

    assert response.status_code == 409
    assert "MATCHING" in response.json()["detail"]
    assert len(state.trips.list()) == 0  # type: ignore[attr-defined]


def test_confirm_assignment_fails_if_shipment_requires_review() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(  # type: ignore[attr-defined]
        ShipmentRequest(status="MATCHING", requires_human_review=True)
    )
    assignment = state.assignments.add(  # type: ignore[attr-defined]
        Assignment(
            shipment_request_id=shipment.id,
            carrier_id="car_1",
            selected_by_user_id="user_operator",
        )
    )

    response = client.post(
        f"/api/v1/assignments/{assignment.id}/confirm",
        headers=OPERATOR_HEADERS,
        json={"confirmation_notes": "still risky"},
    )

    assert response.status_code == 409
    assert "not operationally ready" in response.json()["detail"]
    assert len(state.trips.list()) == 0  # type: ignore[attr-defined]


def test_cancel_trip_validates_transition_and_records_event() -> None:
    client, state = client_with_clean_state()
    trip = state.trips.add(  # type: ignore[attr-defined]
        Trip(
            shipment_request_id="sr_1",
            assignment_id="asg_1",
            carrier_id="car_1",
            status="PLANNED",
        )
    )

    response = client.post(
        f"/api/v1/trips/{trip.id}/cancel",
        headers=OPERATOR_HEADERS,
        json={"reason": "carrier cancelled"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert state.trips.get(trip.id).requires_human_review is True  # type: ignore[attr-defined, union-attr]
    assert state.event_log.events[-1].event_type == "TRIP_CANCELLED"  # type: ignore[attr-defined]


def test_manual_fallback_marks_entity_for_review_without_state_change() -> None:
    client, state = client_with_clean_state()
    shipment = state.shipment_requests.add(ShipmentRequest(status="PUBLISHED"))  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/admin/ops/fallback",
        headers=OPERATOR_HEADERS,
        json={
            "entity_type": "ShipmentRequest",
            "entity_id": shipment.id,
            "reason": "ubicacion ambigua",
        },
    )

    assert response.status_code == 200
    assert response.json()["handoff_required"] is True
    stored = state.shipment_requests.get(shipment.id)  # type: ignore[attr-defined]
    assert stored.status == "PUBLISHED"
    assert stored.requires_human_review is True
    assert state.event_log.events[-1].event_type == "HUMAN_REVIEW_REQUESTED"  # type: ignore[attr-defined]


def test_lists_messages_for_conversation() -> None:
    client, state = client_with_clean_state()
    conversation = state.conversation_sessions.add(ConversationSession(channel="kapso"))  # type: ignore[attr-defined]
    message = state.messages.add(  # type: ignore[attr-defined]
        Message(
            conversation_session_id=conversation.id,
            provider="kapso",
            direction="inbound",
            sender_type="Producer",
            raw_content="Necesito camion",
        )
    )

    response = client.get(f"/api/v1/conversations/{conversation.id}/messages")

    assert response.status_code == 200
    assert response.json()[0]["id"] == message.id
    assert response.json()[0]["redacted_content"] == "[redacted]"
    assert "raw_content" not in response.json()[0]
