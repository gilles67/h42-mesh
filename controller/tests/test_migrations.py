from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from tortoise import Tortoise
from tortoise.connection import get_connection
from tortoise.context import tortoise_test_context
from tortoise.migrations.api.migrate import migrate
from tortoise.migrations.autodetector import MigrationAutodetector

from h42mesh.controller.db import APP_LABEL, MODELS_MODULE, build_tortoise_config
from h42mesh.controller.models import ConnectionRole, InternetConnection, Router, Site, SiteKind
from h42mesh.controller.models.validators import asn_for


@pytest.fixture
async def migrated_sqlite(tmp_path: Path) -> AsyncIterator[None]:
    """Blank on-disk SQLite database, schema created by migrations only."""
    config = build_tortoise_config(f"sqlite://{tmp_path / 'h42-mesh.db'}")
    await migrate(config=config)
    await Tortoise.close_connections()
    # Regular init, without generate_schemas: the schema comes from migrations.
    await Tortoise.init(config=config)
    try:
        yield
    finally:
        await Tortoise.close_connections()


async def test_migrations_create_usable_schema(migrated_sqlite: None) -> None:
    site = await Site.create(
        name="home-1", kind=SiteKind.HOME, number=1, asn=asn_for(SiteKind.HOME, 1)
    )
    router = await Router.create(site=site, name="r1", router_id_address="10.254.0.1")
    await InternetConnection.create(router=router, name="fiber", role=ConnectionRole.ACTIVE)

    await site.delete()  # cascade must come from the foreign keys created by the migration
    assert await InternetConnection.all().count() == 0


async def test_sqlite_pragmas(migrated_sqlite: None) -> None:
    # Reads SQLite-specific pragmas: diagnostic SQL, confined to this test.
    conn = get_connection("default")
    journal = await conn.execute_query_dict("PRAGMA journal_mode")
    foreign_keys = await conn.execute_query_dict("PRAGMA foreign_keys")
    assert journal[0]["journal_mode"] == "wal"
    assert foreign_keys[0]["foreign_keys"] == 1


async def test_models_and_migrations_in_sync() -> None:
    """Fails if a model changed without running `tortoise makemigrations`."""
    apps_config = build_tortoise_config("sqlite://:memory:")["apps"]
    async with tortoise_test_context([MODELS_MODULE], app_label=APP_LABEL) as ctx:
        assert ctx.apps is not None
        writers = await MigrationAutodetector(ctx.apps, apps_config).changes()
    pending = [w.name for w in writers]
    assert pending == [], f"missing migrations: run `tortoise makemigrations` ({pending})"
