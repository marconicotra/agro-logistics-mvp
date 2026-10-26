import logging

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_health_check_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["app"] == "agro-logistics"


def test_whatsapp_health_check_exposes_template_configuration(monkeypatch) -> None:
    monkeypatch.setenv("WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "true")
    monkeypatch.setenv("KAPSO_PHONE_NUMBER_ID", "test-phone-number-id")
    monkeypatch.setenv("KAPSO_NEW_LOAD_TEMPLATE_NAME", "agro_new_load_available")
    monkeypatch.setenv("KAPSO_TEMPLATE_LANGUAGE_CODE", "es_AR")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())

        response = client.get("/health/whatsapp")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "provider": "kapso",
            "enable_real_whatsapp": True,
            "using_real_kapso": True,
            "kapso_phone_number_id": "test-phone-number-id",
            "new_load_template_configured": True,
            "new_load_template_name": "agro_new_load_available",
            "template_language_code": "es_AR",
        }
    finally:
        get_settings.cache_clear()


def test_create_app_logs_warning_when_real_kapso_enabled_without_template(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setenv("ENABLE_REAL_WHATSAPP", "true")
    monkeypatch.setenv("KAPSO_API_KEY", "test-key")
    monkeypatch.setenv("KAPSO_BASE_URL", "https://api.kapso.ai/meta/whatsapp/v24.0")
    monkeypatch.setenv("KAPSO_PHONE_NUMBER_ID", "test-phone-number-id")
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("KAPSO_NEW_LOAD_TEMPLATE_NAME", "   ")
    get_settings.cache_clear()
    try:
        with caplog.at_level(logging.WARNING):
            create_app()

        assert "kapso_new_load_template_missing" in caplog.text
    finally:
        get_settings.cache_clear()
