from fastapi import APIRouter, Response, status
from tortoise.exceptions import BaseORMException

from h42mesh.controller import __version__
from h42mesh.controller.models import User
from h42mesh.controller.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    summary="Controller health",
)
async def get_health(response: Response) -> HealthResponse:
    """Liveness and database reachability, without authentication."""
    try:
        await User.exists()
    except (BaseORMException, OSError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unavailable", version=__version__)
    return HealthResponse(status="ok", version=__version__)
