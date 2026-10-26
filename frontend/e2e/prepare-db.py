"""Create a fresh, isolated SQLite database for the Playwright harness."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.infrastructure.db.base import Base  # noqa: E402
from app.infrastructure.db import models  # noqa: E402,F401
from app.infrastructure.repositories.routing import RoutingOperationRecord  # noqa: E402,F401


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare-db.py DATABASE_PATH")
    path = Path(sys.argv[1]).resolve()
    expected_dir = (ROOT / "frontend" / "test-results").resolve()
    if path.parent != expected_dir or not path.name.startswith("agro-playwright-"):
        raise SystemExit("refusing to create a database outside the Playwright test-results folder")
    if path.exists():
        raise SystemExit("refusing to overwrite an existing Playwright database")
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            models.CarrierRecord(
                id="carrier_pw_seed",
                name="Transportista QA",
                contact_phone="+5491100000001",
                normalized_phone_number="+5491100000001",
                company_name="Flota de prueba",
                truck_count=1,
                truck_types=["jaula"],
                truck_body_type="jaula",
                provider_name="kapso",
                provider_contact_id="pw_contact_seed",
                provider_conversation_id="pw_conversation_seed",
                is_validated=True,
                validation_status="APPROVED",
                service_zone="Pergamino, Buenos Aires; Rosario, Santa Fe",
            )
        )
    table_count = len(inspect(engine).get_table_names())
    engine.dispose()
    print(f"Playwright SQLite database created; tables={table_count}; seeded synthetic carrier=1")


if __name__ == "__main__":
    main()
