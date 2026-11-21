import logging
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from tortoise.context import TortoiseContext, tortoise_test_context

from api_helpers import (
    ADMIN_NEW_PASSWORD,
    Env,
    admin_password_from_log,
    first_login,
    install_clock,
    make_settings,
    start,
)
from h42mesh.controller.db import MODELS_MODULE

# In-memory SQLite by default; PostgreSQL in roadmap step 6 via this variable.
TEST_DATABASE_URL = os.environ.get("H42_MESH_TEST_DATABASE_URL", "sqlite://:memory:")


@pytest.fixture
async def db() -> AsyncIterator[TortoiseContext]:
    async with tortoise_test_context([MODELS_MODULE], db_url=TEST_DATABASE_URL) as ctx:
        yield ctx


@pytest.fixture
def env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Iterator[Env]:
    """Running application on a fresh database, with a controllable clock."""
    clock = install_clock(monkeypatch)
    settings = make_settings(tmp_path)
    caplog.set_level(logging.INFO, logger="h42mesh")
    for client in start(settings):
        yield Env(client, clock, settings, admin_password_from_log(caplog))


@pytest.fixture
def admin(env: Env) -> Env:
    """Administrator logged in, first-login setup done."""
    first_login(env.client, env.clock, "admin", env.admin_password, ADMIN_NEW_PASSWORD)
    return env
