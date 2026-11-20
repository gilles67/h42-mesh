"""Controller settings, read from the environment (``H42_MESH_`` prefix)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="H42_MESH_")

    # Single setting that selects the database: sqlite://… or postgres://…
    database_url: str = "sqlite://h42-mesh.db"
    # File holding the passphrase that encrypts secrets in the database
    # (a Podman secret on the VPS). Required to start the controller; optional
    # here so that tools that never touch secrets (migrations) can run without it.
    passphrase_file: Path | None = None


def get_settings() -> Settings:
    return Settings()
