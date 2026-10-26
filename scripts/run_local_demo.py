"""Start an isolated, synthetic, memory-only AGRO backoffice demo.

Run from the repository root with:
    .venv/bin/python scripts/run_local_demo.py

The API binds to loopback only. It deliberately disables AI, WhatsApp sending,
media downloads, and SQL persistence. Demo rows are recreated on each start.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
_ISOLATED_CWD = tempfile.TemporaryDirectory(prefix="agro-local-demo-")
os.chdir(_ISOLATED_CWD.name)  # Prevent Settings from reading any repository .env.

os.environ.update(
    {
        "APP_ENV": "local",
        "STORAGE_BACKEND": "memory",
        "WHATSAPP_PROVIDER": "mock",
        "ENABLE_REAL_WHATSAPP": "false",
        "AI_PROVIDER": "disabled",
        "OPENAI_API_KEY": "",
        "STT_ENABLED": "false",
        "MEDIA_DOWNLOAD_ENABLED": "false",
        "INTERNAL_API_KEY": "",
        "ENABLE_TEST_ROLE_SWITCHING": "false",
    }
)

from app.api.dependencies import get_app_state, reset_app_state  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.domain.models import (  # noqa: E402
    Assignment,
    Carrier,
    ConversationSession,
    Document,
    Location,
    Message,
    ShipmentRequest,
    Trip,
    TripOffer,
    Vehicle,
)
from app.main import app  # noqa: E402


BA = ZoneInfo("America/Argentina/Buenos_Aires")
DEMO_RUN_ID = "qa_demo_20261010"
DEMO_CONVERSATION_ID = "cs_demo_punta_a_punta"
DEMO_SHIPMENT_ID = "sr_demo_confirmado"
DEMO_CARRIER_ID = "car_demo_aprobado"
DEMO_OFFER_ID = "off_demo_interes"
DEMO_ASSIGNMENT_ID = "asg_demo_confirmada"
DEMO_TRIP_ID = "trip_demo_planificado"


def stamp(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=BA)


def seed_demo() -> None:
    reset_app_state()
    state = get_app_state()
    run_id = DEMO_RUN_ID
    origin = state.locations.add(
        Location(
            id="loc_demo_azul",
            original_text="Azul",
            normalized_name="Azul",
            province="Buenos Aires",
            locality="Azul",
            confidence="high",
            is_validated=True,
        )
    )
    destination = state.locations.add(
        Location(
            id="loc_demo_rosario",
            original_text="Rosario",
            normalized_name="Rosario",
            province="Santa Fe",
            locality="Rosario",
            confidence="high",
            is_validated=True,
        )
    )
    carrier = state.carriers.add(
        Carrier(
            id=DEMO_CARRIER_ID,
            name="Transportes del Centro (demo)",
            normalized_phone_number="FICTICIO / SIN CONTACTO",
            company_name="Flota de demostración",
            cuit="00-00000000-0",
            truck_count=2,
            truck_types=["ganadero"],
            is_validated=True,
            validation_status="APPROVED",
            validated_at=stamp(8, 16),
        )
    )
    for index in (1, 2):
        state.vehicles.add(
            Vehicle(
                id=f"veh_demo_{index}",
                carrier_id=carrier.id,
                vehicle_type="Camión jaula (demo)",
                status="ACTIVE",
                validation_status="APPROVED",
            )
        )
    state.documents.add(
        Document(
            id="doc_demo_reference",
            entity_type="carrier",
            entity_id=carrier.id,
            document_type="DEMO_REFERENCE",
            external_uri="demo://synthetic-reference",
            status="APPROVED",
            notes="Referencia ficticia para la demo; no acredita una revisión real.",
        )
    )
    shipment = state.shipment_requests.add(
        ShipmentRequest(
            id=DEMO_SHIPMENT_ID,
            test_run_id=run_id,
            origin_location_id=origin.id,
            destination_location_id=destination.id,
            date_window_start=stamp(16, 8),
            date_window_end=stamp(16, 18),
            cargo_category="LIVESTOCK",
            cargo_type="novillos",
            livestock_type="novillos",
            quantity_estimate=30,
            quantity_unit="HEAD",
            status="ASSIGNED",
            field_confidence={"pickup_date": "high"},
        )
    )
    offer = state.trip_offers.add(
        TripOffer(
            id=DEMO_OFFER_ID,
            test_run_id=run_id,
            shipment_request_id=shipment.id,
            carrier_id=carrier.id,
            response_type="INTERESTED",
            status="RECEIVED",
        )
    )
    assignment = state.assignments.add(
        Assignment(
            id=DEMO_ASSIGNMENT_ID,
            test_run_id=run_id,
            shipment_request_id=shipment.id,
            carrier_id=carrier.id,
            trip_offer_id=offer.id,
            selected_by_user_id="producer_demo",
            confirmed_by_user_id="producer_demo",
            confirmed_at=stamp(9, 18),
            status="CONFIRMED",
            confirmation_notes="Aceptación explícita del productor (escenario ficticio).",
        )
    )
    state.trips.add(
        Trip(
            id=DEMO_TRIP_ID,
            test_run_id=run_id,
            shipment_request_id=shipment.id,
            assignment_id=assignment.id,
            carrier_id=carrier.id,
            status="PLANNED",
            planned_start_at=stamp(16, 8),
            planned_end_at=stamp(16, 18),
        )
    )

    conversation = state.conversation_sessions.add(
        ConversationSession(
            id=DEMO_CONVERSATION_ID,
            channel="local-demo",
            active_test_run_id=run_id,
            role_override="Producer",
            status="OPEN",
            started_at=stamp(9, 9),
            last_message_at=stamp(9, 9),
        )
    )
    transcript = [
        ("inbound", "Producer", "Necesito transportar 30 novillos desde Azul hasta Rosario el viernes 16/10/2026.", "Producer"),
        ("outbound", "Agent", "Resumen: 30 novillos; origen Azul; destino Rosario; fecha viernes 16/10/2026. ¿Confirmás?", "Producer"),
        ("inbound", "Producer", "Confirmo.", "Producer"),
        ("outbound", "Agent", "La carga quedó publicada para transportistas aprobados.", "Producer"),
        ("outbound", "Agent", "Carga disponible: 30 novillos, Azul → Rosario, 16/10/2026. Respondé Me interesa o No puedo.", "Carrier"),
        ("inbound", "Carrier", "Me interesa.", "Carrier"),
        ("outbound", "Agent", "El transportista manifestó interés. ¿Aceptás esta oferta?", "Producer"),
        ("inbound", "Producer", "Acepto la oferta.", "Producer"),
        ("outbound", "Agent", "Match confirmado. El viaje quedó planificado para el 16/10/2026.", "Producer"),
    ]
    for index, (direction, sender, content, role) in enumerate(transcript):
        occurred_at = stamp(9, 9 + index // 3)
        state.messages.add(
            Message(
                conversation_session_id=conversation.id,
                provider="local-demo-mock",
                direction=direction,
                sender_type=sender,
                message_type="text",
                test_run_id=run_id,
                raw_content=content,
                normalized_content=content,
                received_at=occurred_at if direction == "inbound" else None,
                sent_at=occurred_at if direction == "outbound" else None,
                related_entity_ids={"qaRole": role, "shipmentRequestId": shipment.id},
            )
        )

    event_log = state.event_log
    for event_type, entity_type, entity_id, summary, previous, current in [
        ("SHIPMENT_PUBLISHED", "ShipmentRequest", shipment.id, "Carga ficticia publicada.", "DRAFT", "PUBLISHED"),
        ("CARRIER_INTEREST_REGISTERED", "TripOffer", offer.id, "Transportista ficticio manifestó interés.", None, "INTERESTED"),
        ("ASSIGNMENT_CONFIRMED", "Assignment", assignment.id, "Productor ficticio aceptó el match.", "PROPOSED", "CONFIRMED"),
        ("TRIP_PLANNED", "Trip", DEMO_TRIP_ID, "Viaje ficticio planificado.", None, "PLANNED"),
    ]:
        event_log.record(
            event_type=event_type,
            actor_type="SYSTEM",
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            previous_state=previous,
            new_state=current,
            related_entity_ids={"shipmentRequestId": shipment.id, "carrierId": carrier.id},
            source="local_demo_seed",
            test_run_id=run_id,
        )


def main() -> None:
    get_settings.cache_clear()
    seed_demo()
    import uvicorn

    port = int(os.environ.get("LOCAL_DEMO_API_PORT", "8001"))
    print("AGRO local demo: memoria, datos ficticios, WhatsApp mock, IA y descargas desactivadas.")
    print(f"API: http://127.0.0.1:{port}  |  health: http://127.0.0.1:{port}/health")
    print("No se conecta a Kapso, Supabase, OpenAI ni bases persistentes.")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
