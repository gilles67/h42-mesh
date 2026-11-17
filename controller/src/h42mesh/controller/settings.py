"""Controller settings, read from the environment (``H42_MESH_`` prefix)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="H42_MESH_")

    # Single setting that selects the database: sqlite://… or postgres://…
    database_url: str = "sqlite://h42-mesh.db"


def get_settings() -> Settings:
    return Settings()
