from pathlib import Path

import pytest

from h42mesh.controller.db import build_tortoise_config
from h42mesh.controller.settings import get_settings


def test_default_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("H42_MESH_DATABASE_URL", raising=False)
    assert get_settings().database_url.startswith("sqlite://")


def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgres://h42:secret@localhost:5432/h42mesh"
    monkeypatch.setenv("H42_MESH_DATABASE_URL", url)
    assert get_settings().database_url == url


def test_tortoise_config_is_utc_with_migrations() -> None:
    config = build_tortoise_config("sqlite://:memory:")
    assert config["use_tz"] is True
    assert config["timezone"] == "UTC"
    assert config["apps"]["models"]["migrations"] == "h42mesh.controller.migrations"


def test_passphrase_file_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("H42_MESH_PASSPHRASE_FILE", raising=False)
    assert get_settings().passphrase_file is None
    monkeypatch.setenv("H42_MESH_PASSPHRASE_FILE", str(tmp_path / "passphrase"))
    assert get_settings().passphrase_file == tmp_path / "passphrase"
