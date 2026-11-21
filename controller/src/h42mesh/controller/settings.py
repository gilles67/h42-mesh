"""Controller settings, read from the environment (``H42_MESH_`` prefix)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="H42_MESH_")

    # Single setting that selects the database: sqlite://… or postgres://…
    database_url: str = "sqlite://h42-mesh.db"
    # File holding the passphrase that encrypts secrets in the database
    # (a Podman secret on the VPS). Required to start the controller; optional
    # here so that tools that never touch secrets (migrations) can run without it.
    passphrase_file: Path | None = None

    # GUI sessions.
    session_lifetime_minutes: int = Field(default=12 * 60, gt=0)  # absolute
    session_idle_minutes: int = Field(default=30, gt=0)  # inactivity
    pending_login_minutes: int = Field(default=5, gt=0)  # between password and TOTP
    # False only for local development over plain HTTP.
    session_cookie_secure: bool = True

    # Login attempt limiting (per user, password and TOTP failures alike).
    max_failed_logins: int = Field(default=5, gt=0)
    lockout_minutes: int = Field(default=15, gt=0)


def get_settings() -> Settings:
    return Settings()
