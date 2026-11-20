import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from factories import make_user
from h42mesh.controller import __version__, encryption
from h42mesh.controller.app import create_app
from h42mesh.controller.db import build_tortoise_config
from h42mesh.controller.encryption import PassphraseError, SecretBox
from h42mesh.controller.models import User
from h42mesh.controller.settings import Settings

PASSPHRASE = "test passphrase"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    passphrase_file = tmp_path / "passphrase"
    passphrase_file.write_text(PASSPHRASE + "\n")
    return Settings(
        database_url=f"sqlite://{tmp_path / 'h42-mesh.db'}",
        passphrase_file=passphrase_file,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # Entering the client runs the lifespan: passphrase, migrations, check.
    with TestClient(create_app(settings)) as client:
        yield client


def store_totp_secret(settings: Settings, passphrase: str) -> None:
    """Prepare a migrated database holding one secret encrypted with `passphrase`."""
    with TestClient(create_app(settings)):
        pass  # runs the migrations

    async def insert() -> None:
        await Tortoise.init(config=build_tortoise_config(settings.database_url))
        try:
            await make_user(totp_secret=SecretBox(passphrase).encrypt("JBSWY3DPEHPK3PXP"))
        finally:
            await Tortoise.close_connections()

    asyncio.run(insert())


# --- health ------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_reports_database_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_exists(*args: object, **kwargs: object) -> bool:
        raise OperationalError("database is down")

    monkeypatch.setattr(User, "exists", failing_exists)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_routes_are_under_api_prefix(client: TestClient) -> None:
    assert client.get("/health").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 200
    assert client.get("/api/v1/docs").status_code == 200


# --- startup -----------------------------------------------------------------


def test_startup_configures_encryption(client: TestClient) -> None:
    payload = encryption.encrypt_secret("secret")
    assert SecretBox(PASSPHRASE).decrypt(payload) == "secret"


def test_startup_accepts_right_passphrase(settings: Settings) -> None:
    store_totp_secret(settings, PASSPHRASE)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_startup_refuses_wrong_passphrase(settings: Settings) -> None:
    store_totp_secret(settings, "another passphrase")
    with (
        pytest.raises(PassphraseError, match="does not decrypt"),
        TestClient(create_app(settings)),
    ):
        pass


def test_startup_refuses_missing_passphrase_file(settings: Settings, tmp_path: Path) -> None:
    settings.passphrase_file = tmp_path / "absent"
    with pytest.raises(PassphraseError, match="cannot read"), TestClient(create_app(settings)):
        pass


def test_startup_refuses_unset_passphrase_file(settings: Settings) -> None:
    settings.passphrase_file = None
    with pytest.raises(PassphraseError, match="not set"), TestClient(create_app(settings)):
        pass
