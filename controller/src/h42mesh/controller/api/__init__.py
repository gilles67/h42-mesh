"""API routers, mounted under ``/api/v1``."""

from fastapi import APIRouter

from h42mesh.controller.api import auth, health, users

API_PREFIX = "/api/v1"

router = APIRouter(prefix=API_PREFIX)
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(users.router)
