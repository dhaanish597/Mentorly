"""Loader and cache for config/branding.json."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings


class BrandingConfig(BaseModel):
    """Single source of truth for user-facing product branding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    productName: str = Field(min_length=1, max_length=120)
    productNameStatus: str = Field(min_length=1, max_length=64)
    shortName: str = Field(min_length=1, max_length=32)
    tagline: str = Field(min_length=1, max_length=240)


_BRANDING_CACHE: dict[Path, BrandingConfig] = {}


def load_branding(config_path: Path | None = None) -> BrandingConfig:
    """Read and validate branding JSON from disk without caching."""
    target_path = (config_path or get_settings().branding_config_path).expanduser().resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"Branding config file not found: {target_path}")
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    return BrandingConfig.model_validate(payload)


def get_branding(config_path: Path | None = None) -> BrandingConfig:
    """Return cached BrandingConfig for the configured or specified path."""
    target_path = (config_path or get_settings().branding_config_path).expanduser().resolve()
    cached = _BRANDING_CACHE.get(target_path)
    if cached is not None:
        return cached
    branding = load_branding(target_path)
    _BRANDING_CACHE[target_path] = branding
    return branding


def clear_branding_cache() -> None:
    """Clear the in-memory branding cache (intended for tests)."""
    _BRANDING_CACHE.clear()
