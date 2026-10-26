from fastapi.testclient import TestClient

from app.api.dependencies import reset_app_state
from app.domain.models import Assignment, ShipmentRequest, TripOffer
from app.main import app


OPERATOR_HEADERS = {"x-operator-user-id": "user_operator", "x-operator-role": "operator"}


def test_main_mvp_flow_from_validated_load_to_cancelled_trip(legacy_broadcast, ) -> None:
    state = reset_app_state()
    client = TestClient(app)
    shipment = state.shipment_requests.add(
        ShipmentRequest(
            status="PENDING_OPERATOR_REVIEW",
            livestock_type="novillos",
            missing_critical_fields=[],
            requires_human_review=False,
        )
    )

    validate_response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/validate",
        headers=OPERATOR_HEADERS,
        json={
            "notes": "origen, destino, fecha, hacienda y contacto confirmados",
            "idempotency_key": "flow_validate",
        },
    )
    publish_response = client.post(
        f"/api/v1/shipment-requests/{shipment.id}/publish",
        headers=OPERATOR_HEADERS,
        json={
            "carrier_ids": ["car_norte"],
            "idempotency_key": "flow_publish",
        },
    )
    offer = state.trip_offers.add(
        TripOffer(
            shipment_request_id=shipment.id,
            carrier_id="car_norte",
            response_type="INTERESTED",
            status="INTERESTED",
        )
    )
    shipment.status = "MATCHING"
    state.shipment_requests.save(shipment)
    assignment = state.assignments.add(
        Assignment(
            shipment_request_id=shipment.id,
            trip_offer_id=offer.id,
            carrier_id="car_norte",
            selected_by_user_id="user_operator",
        )
    )
    confirm_response = client.post(
        f"/api/v1/assignments/{assignment.id}/confirm",
        headers=OPERATOR_HEADERS,
        json={
            "confirmation_notes": "carrier y productor confirmados por operador",
            "idempotency_key": "flow_confirm",
        },
    )
    trip_id = confirm_response.json()["trip_id"]
    cancel_response = client.post(
        f"/api/v1/trips/{trip_id}/cancel",
        headers=OPERATOR_HEADERS,
        json={
            "reason": "cancelacion posterior del transportista",
            "idempotency_key": "flow_cancel",
        },
    )

    assert validate_response.status_code == 200
    assert publish_response.status_code == 200
    assert confirm_response.status_code == 200
    assert cancel_response.status_code == 200
    assert state.shipment_requests.get(shipment.id).status == "ASSIGNED"
    assert state.trips.get(trip_id).status == "CANCELLED"
    assert state.trips.get(trip_id).requires_human_review is True
    event_types = [event.event_type for event in state.event_log.events]
    assert "LOAD_VALIDATED" in event_types
    assert "LOAD_PUBLISHED" in event_types
    assert "BROADCAST_SENT" in event_types
    assert "CARRIER_NOTIFIED" in event_types
    assert "ASSIGNMENT_CONFIRMED" in event_types
    assert "TRIP_CREATED" in event_types
    assert "TRIP_CANCELLED" in event_types
