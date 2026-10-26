import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    _log_whatsapp_template_configuration(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )

    if not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
            ],
            allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):[0-9]+$",
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router)
    return app


def _log_whatsapp_template_configuration(settings: Settings) -> None:
    provider = settings.whatsapp_provider.lower()
    if provider != "kapso" or not settings.enable_real_whatsapp:
        return

    if settings.effective_kapso_new_load_template_name:
        logger.info(
            "kapso_new_load_template_configured template_name=%s language=%s",
            settings.effective_kapso_new_load_template_name,
            settings.kapso_template_language_code,
        )
        return

    logger.warning(
        "kapso_new_load_template_missing real outbound is enabled but "
        "KAPSO_NEW_LOAD_TEMPLATE_NAME is empty; notifications outside the 24-hour window "
        "will fail until a WhatsApp template is configured"
    )


app = create_app()
