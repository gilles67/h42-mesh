"""GUI side of router enrollment: tokens and revocation (manage access)."""

from fastapi import APIRouter, status

from h42mesh.controller.api.deps import CurrentUser, SettingsDep
from h42mesh.controller.api.inventory import to_router_read
from h42mesh.controller.api.rights import ManagedRouter
from h42mesh.controller.auth import enrollment
from h42mesh.controller.errors import error_responses
from h42mesh.controller.schemas.agent import EnrollmentTokenCreated
from h42mesh.controller.schemas.inventory import RouterRead

router = APIRouter(tags=["inventory"])
WRITE_ERRORS = error_responses(401, 403, 404)


@router.post(
    "/routers/{router_id}/enrollment-tokens",
    response_model=EnrollmentTokenCreated,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
    summary="Create an enrollment token for a router",
)
async def create_enrollment_token(
    router_: ManagedRouter, user: CurrentUser, settings: SettingsDep
) -> EnrollmentTokenCreated:
    """Single use, valid a few hours, shown once. Previous unused tokens are deleted."""
    token, expires_at = await enrollment.create_token(router_, user, settings)
    return EnrollmentTokenCreated(token=token, expires_at=expires_at)


@router.post(
    "/routers/{router_id}/revoke",
    response_model=RouterRead,
    responses=WRITE_ERRORS,
    summary="Revoke the signing key of a router",
)
async def revoke_router(router_: ManagedRouter) -> RouterRead:
    """The agent is refused from its next request on; a new enrollment lifts it."""
    router_.signing_key_revoked = True
    await router_.save(update_fields=["signing_key_revoked"])
    return to_router_read(router_)
