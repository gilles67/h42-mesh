"""API routers, mounted under ``/api/v1``."""

from fastapi import APIRouter

from h42mesh.controller.api import (
    agent,
    auth,
    enrollment,
    health,
    inventory,
    meshes,
    tunnels,
    users,
)

API_PREFIX = "/api/v1"

router = APIRouter(prefix=API_PREFIX)
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(meshes.router)
router.include_router(inventory.router)
router.include_router(tunnels.router)
router.include_router(enrollment.router)
router.include_router(agent.router)
