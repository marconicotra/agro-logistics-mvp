from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.infrastructure.db.session import get_session_factory

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/health/db")
def db_health_check() -> dict[str, str]:
    settings = get_settings()
    storage_backend = settings.storage_backend.lower()
    if storage_backend == "memory":
        return {"status": "ok", "storage_backend": "memory", "database": "not_configured"}
    if storage_backend != "sql":
        return {"status": "error", "storage_backend": settings.storage_backend, "database": "unsupported"}

    try:
        session_factory = get_session_factory(settings.database_url)
        with session_factory() as session:
            session.execute(text("select 1"))
            inspector = inspect(session.get_bind())
            if not inspector.has_table("alembic_version"):
                current_revision = "unversioned"
            else:
                row = session.execute(text("select version_num from alembic_version")).first()
                current_revision = row[0] if row else "unversioned"
    except SQLAlchemyError:
        return {"status": "error", "storage_backend": "sql", "database": "unreachable"}

    root = Path(__file__).resolve().parents[4]
    alembic_config = Config(str(root / "alembic.ini"))
    expected_revision = ScriptDirectory.from_config(alembic_config).get_current_head()
    schema_status = "current" if current_revision == expected_revision else "outdated"
    return {
        "status": "ok" if schema_status == "current" else "degraded",
        "storage_backend": "sql",
        "database": "reachable",
        "schema": schema_status,
        "schema_revision": current_revision,
        "expected_revision": expected_revision or "unknown",
    }


@router.get("/health/whatsapp")
def whatsapp_health_check() -> dict[str, str | bool | None]:
    settings = get_settings()
    provider = settings.whatsapp_provider.lower()
    using_real_kapso = provider == "kapso" and settings.enable_real_whatsapp
    return {
        "status": "ok",
        "provider": provider,
        "enable_real_whatsapp": settings.enable_real_whatsapp,
        "using_real_kapso": using_real_kapso,
        "kapso_phone_number_id": settings.kapso_phone_number_id,
        "new_load_template_configured": bool(settings.effective_kapso_new_load_template_name),
        "new_load_template_name": settings.effective_kapso_new_load_template_name,
        "template_language_code": settings.kapso_template_language_code,
    }
