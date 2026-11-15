"""Application settings loaded from VCC_* environment variables."""

from functools import lru_cache
import json
import os
import re
import stat
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from backend.app.core.local_config import local_development

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_BRANDING_PATH = _REPO_ROOT / "config" / "branding.json"


def validate_env_file(value: str | Path) -> Path:
    """Validate explicit server configuration without disclosing its contents."""
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Explicit environment file must be an absolute, non-symlink path.")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise ValueError("Explicit environment file is unavailable.") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o022:
        raise ValueError("Explicit environment file must be regular and not writable by other users.")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise ValueError("Explicit environment file must belong to the current user.")
    return path


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
        hide_input_in_errors=True,
    )

    def __init__(self, **values):
        # Explicit file selection is authoritative for credentials, not the ambient
        # shell's account. Explicit constructor values (including None) still win.
        selected = values.get("_env_file")
        if isinstance(selected, (str, Path)):
            selected = validate_env_file(selected)
            values = {**values, "_env_file": selected}
            from dotenv import dotenv_values
            credentials = dotenv_values(selected, interpolate=False)
            for field in ("gnani_api_key", "groq_api_key", "internal_worker_secret", "operations_token", "database_url"):
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
    database_schema: str = "viva_app"
    cloud_runtime: bool = False
    cors_origins: str = Field(default_factory=lambda: local_development().cors_origins)

    allow_public_custom_code: bool = False
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
    gnani_max_concurrency: int = Field(default=1, ge=1, le=32)
    # This is an operator attestation after account verification, never a probe
    # inferred from successful calls or an automatically discovered entitlement.
    gnani_verified_concurrency: int = Field(default=1, ge=1, le=32)

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
    llm_feedback_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    conversation_timeout_ms: int = Field(default=5000, ge=100, le=10000)
    model_daily_call_limit: int = Field(default=40, ge=1, le=10000)
    model_session_call_limit: int = Field(default=12, ge=1, le=1000)
    model_max_concurrency: int = Field(default=1, ge=1, le=1)

    @property
    def gnani_effective_concurrency(self) -> int:
        return min(self.gnani_max_concurrency, self.gnani_verified_concurrency)

    @field_validator('database_url', mode='before')
    @classmethod
    def validate_database_url(cls, value):
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if raw is None or isinstance(raw, str) and not raw.strip():
            return None
        try:
            parsed = urlsplit(raw)
            if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname or parsed.fragment:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError('Shared database URL must be a valid PostgreSQL URL') from exc
        return SecretStr(raw)

    @field_validator('llm_model')
    @classmethod
    def validate_model_identifier(cls, value: str) -> str:
        value=value.strip()
        if value and (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.\-/]{0,199}',value) or value.startswith(('gsk_','sk-'))):
            raise ValueError('Model must be a provider model identifier')
        return value

    @property
    def database_target(self):
        """Keep credentials inside a secret-safe database target."""
        if self.database_url is not None:
            from backend.app.db.postgres.runtime import PostgresTarget
            return PostgresTarget(self.database_url.get_secret_value(), schema=self.database_schema)
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
    if path:
        try:
            validate_env_file(path)
        except ValueError as exc:
            raise RuntimeError("The explicitly selected server environment file is invalid or unavailable.") from exc
    return Settings(_env_file=path or None)


def clear_settings_cache() -> None:
    """Clear cached settings (intended for tests)."""
    get_settings.cache_clear()


from contextvars import ContextVar
request_settings: ContextVar[Settings | None] = ContextVar("vcc_request_settings", default=None)

def get_request_settings() -> Settings:
    return request_settings.get() or get_settings()
