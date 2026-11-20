from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from tortoise import Tortoise
from tortoise.connection import get_connection
from tortoise.context import tortoise_test_context
from tortoise.exceptions import IntegrityError
from tortoise.migrations.api.migrate import migrate
from tortoise.migrations.autodetector import MigrationAutodetector

from factories import Topology, make_mesh, make_site, make_tunnel
from h42mesh.controller.db import APP_LABEL, MODELS_MODULE, build_tortoise_config
from h42mesh.controller.models import Tunnel, TunnelStatus


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
    topo = await Topology.create()
    tunnel = await make_tunnel(topo.mesh, topo.conn_a, topo.conn_b)
    await TunnelStatus.create(tunnel=tunnel, router=topo.router_a, reported_at=tunnel.created_at)

    # Cascade must come from the foreign keys created by the migration.
    await topo.router_b.delete()
    assert await Tunnel.all().count() == 0
    assert await TunnelStatus.all().count() == 0


async def test_migrations_restrict_and_unique_per_mesh(migrated_sqlite: None) -> None:
    mesh = await make_mesh()
    await make_site(mesh, "pari", 4_200_000_001)
    with pytest.raises(IntegrityError):
        await mesh.delete()
    with pytest.raises(IntegrityError):
        await make_site(mesh, "pari", 4_200_000_002, name="Other")


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


def test_table_descriptions_have_no_semicolon() -> None:
    """Tortoise turns a model docstring's first line into a SQL comment and splits
    migration statements on ';': a semicolon there breaks `tortoise migrate`."""
    import h42mesh.controller.models as models

    for name in models.__all__:
        model = getattr(models, name)
        meta = getattr(model, "_meta", None)
        if meta is not None:
            assert ";" not in (meta.table_description or ""), name
