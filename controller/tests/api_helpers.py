"""Helpers for API tests: application client, controllable clock, login steps."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyotp
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx2 import Response

from h42mesh.controller.api import auth as auth_api
from h42mesh.controller.api import deps
from h42mesh.controller.app import create_app
from h42mesh.controller.auth import passwords, sessions, totp
from h42mesh.controller.auth.sessions import COOKIE_NAME
from h42mesh.controller.settings import Settings

PASSPHRASE = "test passphrase"
ADMIN_NEW_PASSWORD = "admin password 2026"
API = "/api/v1"


@dataclass
class Clock:
    """Time seen by sessions, attempt limiting and TOTP."""

    current: datetime = field(default_factory=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


def install_clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    for module in (sessions, deps, auth_api):
        monkeypatch.setattr(module, "now", clock.now)
    monkeypatch.setattr(totp, "_now", lambda: clock.current.timestamp())
    # Cheap Argon2 parameters: tests hash many passwords.
    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )
    return clock


def make_settings(tmp_path: Path) -> Settings:
    passphrase_file = tmp_path / "passphrase"
    passphrase_file.write_text(PASSPHRASE + "\n")
    return Settings(
        database_url=f"sqlite://{tmp_path / 'h42-mesh.db'}",
        passphrase_file=passphrase_file,
    )


def admin_password_from_log(caplog: pytest.LogCaptureFixture) -> str:
    for record in caplog.records:
        if record.name == "h42mesh.controller.bootstrap" and "administrator created" in (
            record.getMessage()
        ):
            match = re.search(r"password '([^']+)'", record.getMessage())
            assert match is not None
            return match.group(1)
    raise AssertionError("administrator password not logged")


@dataclass
class Env:
    client: TestClient
    clock: Clock
    settings: Settings
    admin_password: str


def start(settings: Settings) -> Iterator[TestClient]:
    # https: the session cookie is Secure, httpx would not send it over http.
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client


def login(client: TestClient, username: str, password: str) -> Response:
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def code(secret: str, clock: Clock) -> str:
    return pyotp.TOTP(secret).at(clock.current)


def session_token(client: TestClient) -> str | None:
    return client.cookies.get(COOKIE_NAME)


def use_token(client: TestClient, token: str | None) -> None:
    client.cookies.clear()
    if token is not None:
        client.cookies.set(COOKIE_NAME, token, domain="testserver.local", path="/api")


def first_login(
    client: TestClient, clock: Clock, username: str, password: str, new_password: str
) -> str:
    """Full first login (password change, TOTP setup); returns the TOTP secret."""
    assert login(client, username, password).json() == {"next_step": "change_password"}
    response = client.post(
        f"{API}/auth/password",
        json={"current_password": password, "new_password": new_password},
    )
    assert response.status_code == 204, response.text
    secret: str = client.post(f"{API}/auth/totp/setup").json()["secret"]
    response = client.post(
        f"{API}/auth/totp/confirm", json={"secret": secret, "code": code(secret, clock)}
    )
    assert response.status_code == 204, response.text
    return secret


def full_login(
    client: TestClient, clock: Clock, username: str, password: str, secret: str
) -> Response:
    """Password then TOTP, one TOTP step later than any previous login (no replay)."""
    clock.advance(seconds=totp.INTERVAL)
    assert login(client, username, password).json() == {"next_step": "totp"}
    return client.post(f"{API}/auth/totp", json={"code": code(secret, clock)})
