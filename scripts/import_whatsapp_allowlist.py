from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.application.whatsapp_allowlist import (
    WhatsappAllowedContactInput,
    WhatsappAllowlistError,
    WhatsappAllowlistService,
)
from app.core.config import get_settings
from app.infrastructure.db.repositories import SqlWhatsappAllowedContactRepository
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.db.event_log import SqlEventLogService


def main() -> int:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to import WHATSAPP_DEV_ALLOWLIST in production.", file=sys.stderr)
        return 1
    if not settings.whatsapp_allowlist:
        print("No numbers found in WHATSAPP_DEV_ALLOWLIST.")
        return 0
    if settings.storage_backend.lower() != "sql":
        print("This import script requires STORAGE_BACKEND=sql.", file=sys.stderr)
        return 1

    session_factory = get_session_factory(settings.database_url)
    created = 0
    existing = 0
    with session_factory() as session, session.begin():
        service = WhatsappAllowlistService(
            contacts=SqlWhatsappAllowedContactRepository(session),
            event_log=SqlEventLogService(session),
            environment=settings.app_env.lower(),
            source=settings.effective_whatsapp_allowlist_source,
            default_allow=settings.effective_whatsapp_allowlist_default_allow,
            env_allowlist=settings.whatsapp_allowlist,
        )
        for phone_number in sorted(settings.whatsapp_allowlist):
            try:
                service.create_contact(
                    operator_user_id="script_import_whatsapp_allowlist",
                    data=WhatsappAllowedContactInput(
                        phone_number=phone_number,
                        label="Imported from WHATSAPP_DEV_ALLOWLIST",
                        environment="staging",
                        provider="kapso",
                        status="ACTIVE",
                        notes="Imported from legacy env allowlist",
                    ),
                )
            except WhatsappAllowlistError:
                existing += 1
            else:
                created += 1

    print(f"Imported whatsapp allowlist contacts: created={created} existing={existing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
