"""FastAPI application of the controller.

Run locally with ``uvicorn h42mesh.controller.app:create_app --factory``.

Startup (docs/specs/controller.md):
1. read the passphrase;
2. apply the migrations;
3. check that the passphrase decrypts the stored secrets, if any.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from tortoise import Tortoise
from tortoise.contrib.fastapi import RegisterTortoise
from tortoise.migrations.api.migrate import migrate

from h42mesh.controller import __version__, encryption
from h42mesh.controller.api import API_PREFIX
from h42mesh.controller.api import router as api_router
from h42mesh.controller.db import build_tortoise_config
from h42mesh.controller.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def operation_id(route: APIRoute) -> str:
    """Use the endpoint function name as OpenAPI operationId (cleaner generated client)."""
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Settings are read at startup, not at import."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        current = settings or get_settings()
        encryption.configure_from_settings(current)
        config = build_tortoise_config(current.database_url)
        logger.info("applying database migrations")
        await migrate(config=config)
        await Tortoise.close_connections()
        async with RegisterTortoise(app, config=config):
            if await encryption.verify_passphrase():
                logger.info("passphrase checked against a stored secret")
            else:
                logger.info("no stored secret yet: passphrase not checked")
            yield
        encryption.reset()

    app = FastAPI(
        title="h42-mesh controller",
        version=__version__,
        summary="API of the h42-mesh controller (inventory, tunnels, agent configuration).",
        license_info={"name": "MIT", "identifier": "MIT"},
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=operation_id,
    )
    app.include_router(api_router)
    return app
