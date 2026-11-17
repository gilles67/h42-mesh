import os
from collections.abc import AsyncIterator

import pytest
from tortoise.context import TortoiseContext, tortoise_test_context

from h42mesh.controller.db import MODELS_MODULE

# In-memory SQLite by default; PostgreSQL in roadmap step 6 via this variable.
TEST_DATABASE_URL = os.environ.get("H42_MESH_TEST_DATABASE_URL", "sqlite://:memory:")


@pytest.fixture
async def db() -> AsyncIterator[TortoiseContext]:
    async with tortoise_test_context([MODELS_MODULE], db_url=TEST_DATABASE_URL) as ctx:
        yield ctx
