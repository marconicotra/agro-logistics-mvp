"""Start the isolated Playwright API with deterministic, local-only AI extraction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402

from app.api.dependencies import get_ai_extraction_client  # noqa: E402
from app.application.ai import LoadDataExtraction  # noqa: E402
from app.application.chat_shipment_parser import parse_chat_shipment_text  # noqa: E402
from app.main import app  # noqa: E402


class DeterministicQAExtractionClient:
    def extract_load_data(self, message_text: str) -> LoadDataExtraction:
        parsed = parse_chat_shipment_text(message_text)
        return LoadDataExtraction(
            raw_text=message_text,
            cargo_category=parsed.cargo_category,
            cargo_type=parsed.cargo_type,
            quantity_unit=parsed.quantity_unit,
            origin=parsed.origin,
            destination=parsed.destination,
            date_window_start=parsed.date_window_start,
            date_window_end=parsed.date_window_end,
            livestock_type=parsed.livestock_type,
            quantity_estimate=parsed.quantity_estimate,
            weight_per_head_kg=parsed.weight_per_head_kg,
            confidence="high",
        )


app.dependency_overrides[get_ai_extraction_client] = DeterministicQAExtractionClient

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004, log_level="warning")
