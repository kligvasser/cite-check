"""Layered settings: CLI flags > env vars > ~/.config/cite-check/config.toml > defaults."""

from pathlib import Path
from typing import Any

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CONFIG_FILE = Path.home() / ".config" / "cite-check" / "config.toml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CITECHECK_",
        env_file=".env",
        toml_file=CONFIG_FILE,
        extra="ignore",
    )

    backend: str = "scholarly"  # "scholarly" | "serpapi"
    serpapi_key: str | None = None
    scholar_only: bool = False  # disable Crossref/Semantic Scholar corroboration
    cache_path: Path = Path.home() / ".cache" / "cite-check" / "cache.db"
    min_interval_s: float = 3.0  # polite delay between Scholar requests
    results_per_query: int = 5
    grobid_url: str = "http://localhost:8070"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_settings(**overrides: Any) -> Settings:
    """Build settings, dropping ``None`` overrides so lower layers win."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})
