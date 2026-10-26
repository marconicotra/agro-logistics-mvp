from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    route_operations_enabled: bool = Field(default=True, alias="ROUTE_OPERATIONS_ENABLED")
    google_routes_api_key: str | None = Field(default=None, alias="GOOGLE_ROUTES_API_KEY")
    google_maps_browser_key: str | None = Field(default=None, alias="GOOGLE_MAPS_BROWSER_KEY")
    google_routes_daily_limit: int = Field(default=100, ge=1, alias="GOOGLE_ROUTES_DAILY_LIMIT")

    app_name: str = Field(default="agro-logistics", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    storage_backend: str = Field(default="memory", alias="STORAGE_BACKEND")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/agro_logistics",
        alias="DATABASE_URL",
    )
    kapso_webhook_secret: str = Field(default="local-dev-secret", alias="KAPSO_WEBHOOK_SECRET")
    internal_api_key: str | None = Field(default=None, alias="INTERNAL_API_KEY")
    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")
    supabase_bootstrap_admin_user_id: str | None = Field(
        default=None,
        alias="SUPABASE_BOOTSTRAP_ADMIN_USER_ID",
    )
    kapso_timestamp_tolerance_seconds: int = Field(
        default=300,
        alias="KAPSO_TIMESTAMP_TOLERANCE_SECONDS",
    )
    kapso_api_key: str | None = Field(default=None, alias="KAPSO_API_KEY")
    kapso_base_url: str | None = Field(default=None, alias="KAPSO_BASE_URL")
    kapso_phone_number_id: str | None = Field(default=None, alias="KAPSO_PHONE_NUMBER_ID")
    kapso_send_message_path: str = Field(default="/messages", alias="KAPSO_SEND_MESSAGE_PATH")
    kapso_new_load_template_name: str | None = Field(default=None, alias="KAPSO_NEW_LOAD_TEMPLATE_NAME")
    kapso_template_language_code: str = Field(default="es_AR", alias="KAPSO_TEMPLATE_LANGUAGE_CODE")
    kapso_interactive_enabled: bool = Field(default=False, alias="KAPSO_INTERACTIVE_ENABLED")
    whatsapp_provider: str = Field(default="mock", alias="WHATSAPP_PROVIDER")
    enable_real_whatsapp: bool = Field(default=False, alias="ENABLE_REAL_WHATSAPP")
    whatsapp_dev_allowlist: str = Field(default="", alias="WHATSAPP_DEV_ALLOWLIST")
    whatsapp_allowlist_source: str = Field(default="db_then_env", alias="WHATSAPP_ALLOWLIST_SOURCE")
    whatsapp_allowlist_default_allow: bool = Field(
        default=False,
        alias="WHATSAPP_ALLOWLIST_DEFAULT_ALLOW",
    )
    enable_test_role_switching: bool = Field(default=False, alias="ENABLE_TEST_ROLE_SWITCHING")
    media_storage_dir: str = Field(default="var/media", alias="MEDIA_STORAGE_DIR")
    media_download_enabled: bool = Field(default=False, alias="MEDIA_DOWNLOAD_ENABLED")
    media_max_download_bytes: int = Field(default=10_000_000, alias="MEDIA_MAX_DOWNLOAD_BYTES")
    ai_provider: str = Field(default="openai", alias="AI_PROVIDER")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    stt_provider: str = Field(default="openai", alias="STT_PROVIDER")
    stt_model: str = Field(default="gpt-4o-mini-transcribe", alias="STT_MODEL")
    stt_enabled: bool = Field(default=False, alias="STT_ENABLED")
    stt_timeout_seconds: int = Field(default=45, alias="STT_TIMEOUT_SECONDS")
    stt_max_audio_bytes: int = Field(default=25_000_000, alias="STT_MAX_AUDIO_BYTES")

    @property
    def debug(self) -> bool:
        return self.app_env.lower() in {"local", "development", "dev"}

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def effective_kapso_new_load_template_name(self) -> str | None:
        value = self.kapso_new_load_template_name
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @property
    def whatsapp_allowlist(self) -> set[str]:
        return {
            item.strip()
            for item in self.whatsapp_dev_allowlist.split(",")
            if item.strip()
        }

    @property
    def effective_whatsapp_allowlist_source(self) -> str:
        if self.is_production:
            return "db"
        value = self.whatsapp_allowlist_source.strip().lower()
        if value not in {"db", "env", "db_then_env"}:
            return "db_then_env"
        return value

    @property
    def effective_whatsapp_allowlist_default_allow(self) -> bool:
        if self.is_production:
            return False
        return self.whatsapp_allowlist_default_allow


@lru_cache
def get_settings() -> Settings:
    return Settings()
