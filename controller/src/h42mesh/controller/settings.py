"""Controller settings, read from the environment (``H42_MESH_`` prefix)."""

import ipaddress
from pathlib import Path

from pydantic import Field, field_validator
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

    # Agents: enrollment tokens and signed JWTs.
    enrollment_token_hours: int = Field(default=4, gt=0)
    agent_jwt_audience: str = "h42-mesh-controller"
    agent_jwt_max_lifetime_seconds: int = Field(default=300, gt=0)  # exp at most this far
    agent_jwt_leeway_seconds: int = Field(default=30, ge=0)  # clock skew tolerance

    # Networks allowed to pass the client address in X-Forwarded-For (Traefik),
    # as JSON: H42_MESH_TRUSTED_PROXIES='["10.89.0.0/24"]'. Empty: never trusted.
    trusted_proxies: list[str] = Field(default_factory=list)
    # MaxMind GeoLite2 ASN database (optional): fills Connection.isp.
    geolite2_asn_file: Path | None = None

    @field_validator("trusted_proxies")
    @classmethod
    def _networks(cls, value: list[str]) -> list[str]:
        return [str(ipaddress.ip_network(network, strict=False)) for network in value]


def get_settings() -> Settings:
    return Settings()
