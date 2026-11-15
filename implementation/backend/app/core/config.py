"""Application settings loaded from VCC_* environment variables."""

from functools import lru_cache
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, PrivateAttr, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_BRANDING_PATH = _REPO_ROOT / "config" / "branding.json"


def validated_credential(value: str | SecretStr | None) -> str | None:
    """Reject templates without returning or logging the rejected credential."""
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    normalized = re.sub(r"[^a-z0-9]", "", raw.lower())
    markers = ("yourapikey", "yourgnani", "yourgroq", "replace", "placeholder", "insertactual", "changeme", "example")
    if raw.startswith(("<", "${")) or any(marker in normalized for marker in markers):
        return None
    if normalized in {"apikey", "gnaniapikey", "none", "null", "todo", "secret", "yourkey"}:
        return None
    return raw


class Settings(BaseSettings):
    """Brand-independent coordinator configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VCC_",
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **values):
        # Explicit file selection is authoritative for credentials, not the ambient
        # shell's account. Explicit constructor values (including None) still win.
        selected = values.get("_env_file")
        if isinstance(selected, (str, Path)):
            from dotenv import dotenv_values
            credentials = dotenv_values(selected, interpolate=False)
            for field in ("gnani_api_key", "groq_api_key", "internal_worker_secret", "operations_token"):
                canonical = "VCC_" + field.upper()
                if field not in values and canonical not in values:
                    credential = credentials.get(canonical)
                    if field == "gnani_api_key" and canonical not in credentials:
                        credential = credentials.get("GNANI_API_KEY")
                    values = {**values, (canonical if field == "gnani_api_key" else field): credential}
        # Aliased env settings must not override explicit None used by previews/tests.
        if "gnani_api_key" in values and "VCC_GNANI_API_KEY" not in values:
            values = {**values, "VCC_GNANI_API_KEY": values["gnani_api_key"]}
            values.pop("gnani_api_key")
        super().__init__(**values)

    env: Literal["development", "staging", "production", "test"] = "development"
    api_version: str = "0.1.0-phase0"
    log_level: str = "INFO"

    branding_config_path: Path = Field(default=_DEFAULT_BRANDING_PATH)
    database_path: Path = Field(default=Path("./data/vcc.db"))
    database_url: SecretStr | None = None
    database_sslrootcert: Path | None = None
    database_schema: str = "viva_app"
    cloud_runtime: bool = False
    cors_origins: str = "http://localhost:5173"

    allow_public_custom_code: bool = False
    execution_runtime: Literal['gvisor', 'vercel_sandbox'] = 'gvisor'
    public_execution_enabled: bool = False
    vercel_sandbox_acceptance_path: Path | None = None
    vercel_sandbox_acceptance_sha256: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    _trusted_worker: object | None = PrivateAttr(default=None)
    _trusted_worker_configuration: tuple | None = PrivateAttr(default=None)
    isolation_acceptance_file: Path | None = None
    exec_worker_url: str = "http://exec-worker:8001"
    internal_worker_secret: SecretStr | None = None
    operations_token: SecretStr | None = None

    gnani_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("VCC_GNANI_API_KEY", "GNANI_API_KEY"),
    )
    gnani_base_url: str = "https://api.vachana.ai"
    gnani_stt_model: Literal["prisma-v3.0"] = "prisma-v3.0"
    gnani_tts_model: Literal["timbre-v3.0"] = "timbre-v3.0"
    gnani_tts_voice: str = "Avinash"
    gnani_stt_transport: Literal["rest", "websocket"] = "rest"
    gnani_max_concurrency: int = Field(default=1, ge=1, le=1)

    max_stt_seconds_per_session: int = Field(default=180, ge=1)
    max_tts_chars_per_session: int = Field(default=4000, ge=1)
    global_daily_call_limit: int = Field(default=800, ge=1)
    tts_cache_dir: Path = Field(default=Path("./data/tts_cache"))
    tts_cache_max_bytes: int = Field(default=32 * 1024 * 1024, ge=1)
    tts_cache_max_age_seconds: int = Field(default=86400, ge=1)
    retention_interval_seconds: float = Field(default=60.0, ge=1, le=86400)
    retention_batch_size: int = Field(default=100, ge=1, le=1000)
    request_window_seconds: int = Field(default=60, ge=1, le=3600)
    per_ip_request_limit: int = Field(default=180, ge=1)
    per_session_request_limit: int = Field(default=120, ge=1)
    global_request_limit: int = Field(default=900, ge=1)
    session_creation_limit: int = Field(default=6, ge=1)
    max_inflight_requests: int = Field(default=32, ge=1, le=256)

    llm_provider: str = "groq"
    groq_api_key: SecretStr | None = None
    llm_model: str = ""
    llm_timeout_ms: int = Field(default=1200, ge=100)
    conversation_timeout_ms: int = Field(default=5000, ge=100, le=10000)
    model_daily_call_limit: int = Field(default=40, ge=1, le=10000)
    model_session_call_limit: int = Field(default=12, ge=1, le=1000)
    model_max_concurrency: int = Field(default=1, ge=1, le=1)

    @property
    def database_target(self):
        """Keep credentials inside a secret-safe database target."""
        if self.database_url is not None:
            from backend.app.db.postgres.runtime import PostgresTarget
            dsn = self.database_url.get_secret_value()
            if self.database_sslrootcert is not None:
                from psycopg.conninfo import make_conninfo
                try:
                    dsn = make_conninfo(dsn, sslrootcert=str(self.database_sslrootcert))
                except Exception:
                    raise ValueError('Invalid PostgreSQL connection configuration') from None
            return PostgresTarget(dsn, schema=self.database_schema)
        if self.cloud_runtime:
            raise RuntimeError("Cloud deployment requires a shared PostgreSQL database.")
        return self.database_path

    @field_validator("gnani_api_key", "groq_api_key", "internal_worker_secret", "operations_token", mode="before")
    @classmethod
    def discard_placeholder_credentials(cls, value: str | SecretStr | None) -> SecretStr | None:
        credential = validated_credential(value)
        return SecretStr(credential) if credential else None

    @field_validator("branding_config_path")
    @classmethod
    def resolve_branding_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else _REPO_ROOT / value

    @field_validator('database_sslrootcert')
    @classmethod
    def resolve_database_certificate(cls, value: Path | None) -> Path | None:
        if value is None or value.is_absolute():
            return value
        return _REPO_ROOT / value

    @field_validator('vercel_sandbox_acceptance_path')
    @classmethod
    def resolve_sandbox_acceptance(cls, value: Path | None) -> Path | None:
        if value is None or value.is_absolute():
            return value
        return _REPO_ROOT / value

    @property
    def cors_origins_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw:
            return []
        if raw.startswith("["):
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(origin).strip() for origin in parsed if str(origin).strip()]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    # No cwd-based discovery. Only the server process's explicit opt-in loads a file.
    path = os.environ.get("VCC_ENV_FILE", "").strip()
    if path and not Path(path).is_file():
        raise RuntimeError("The explicitly selected server environment file is unavailable.")
    return Settings(_env_file=path or None)


def clear_settings_cache() -> None:
    """Clear cached settings (intended for tests)."""
    get_settings.cache_clear()


from contextvars import ContextVar
request_settings: ContextVar[Settings | None] = ContextVar("vcc_request_settings", default=None)

def get_request_settings() -> Settings:
    return request_settings.get() or get_settings()
