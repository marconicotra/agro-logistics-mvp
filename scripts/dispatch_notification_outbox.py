#!/usr/bin/env python3
"""Run the SQL notification outbox dispatcher as a separate worker process."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.dependencies import get_whatsapp_provider  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.infrastructure.db.notification_outbox import NotificationOutboxDispatcher  # noqa: E402
from app.infrastructure.db.session import get_session_factory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="dispatch currently due messages, then exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds < 0.2:
        parser.error("--poll-seconds must be at least 0.2")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if settings.storage_backend.lower() != "sql":
        parser.error("notification outbox worker requires STORAGE_BACKEND=sql")

    dispatcher = NotificationOutboxDispatcher(
        session_factory=get_session_factory(settings.database_url),
        provider=get_whatsapp_provider(),
    )
    while True:
        outcome = dispatcher.dispatch_one()
        if outcome is None:
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
            continue
        logging.info("notification_outbox_dispatch outcome=%s", outcome)


if __name__ == "__main__":
    raise SystemExit(main())
