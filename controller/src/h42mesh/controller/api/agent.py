"""Agent API: enrollment, identity and signing key renewal.

Every call but enrollment is authenticated by a short-lived JWT signed by the
agent (``Authorization: Bearer …``).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from tortoise.exceptions import IntegrityError

from h42mesh.controller.api.deps import SettingsDep
from h42mesh.controller.auth import agent_jwt, enrollment
from h42mesh.controller.errors import ApiError, conflict, error_responses
from h42mesh.controller.models import Router
from h42mesh.controller.schemas.agent import (
    AgentIdentity,
    EnrollRequest,
    EnrollResponse,
    SigningKeyRenewal,
)

router = APIRouter(prefix="/agent", tags=["agent"])
AGENT_ERRORS = error_responses(401, 403)


def _invalid_token() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "invalid_agent_token",
        "Invalid agent token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate_agent(request: Request, settings: SettingsDep) -> Router:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _invalid_token()
    try:
        return await agent_jwt.authenticate(token.strip(), settings)
    except agent_jwt.InvalidAgentTokenError as exc:
        raise _invalid_token() from exc
    except agent_jwt.RouterRevokedError as exc:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "router_revoked", "The router's signing key is revoked"
        ) from exc


AgentRouter = Annotated[Router, Depends(authenticate_agent)]


def _key_in_use() -> ApiError:
    return conflict("signing_key_in_use", "This key is the signing key of another router")


@router.post(
    "/enroll",
    response_model=EnrollResponse,
    responses=error_responses(401, 409),
    summary="Enroll a router with a single-use token",
)
async def enroll_router(body: EnrollRequest) -> EnrollResponse:
    """The agent sends its new Ed25519 public key with the token; the token is used up."""
    try:
        router_ = await enrollment.enroll(body.token, body.signing_public_key)
    except enrollment.InvalidEnrollmentTokenError as exc:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_enrollment_token",
            "Unknown, expired or already used enrollment token",
        ) from exc
    except enrollment.SigningKeyInUseError as exc:
        raise _key_in_use() from exc
    return EnrollResponse(router_id=router_.id)


@router.get("/me", response_model=AgentIdentity, responses=AGENT_ERRORS, summary="Who am I")
async def get_agent_identity(router_: AgentRouter) -> AgentIdentity:
    return AgentIdentity(
        router_id=router_.id,
        mesh_id=router_.site.mesh_id,
        site_nickname=router_.site.nickname,
        router_number=router_.number,
    )


@router.put(
    "/signing-key",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AGENT_ERRORS | error_responses(409),
    summary="Renew the signing key",
)
async def renew_signing_key(body: SigningKeyRenewal, router_: AgentRouter) -> None:
    """Authenticated with the current key; the new one replaces it, without history.

    JWTs signed with the previous key are refused from the next request on.
    """
    if (
        await Router.filter(signing_public_key=body.signing_public_key)
        .exclude(id=router_.id)
        .exists()
    ):
        raise _key_in_use()
    router_.signing_public_key = body.signing_public_key
    try:
        await router_.save(update_fields=["signing_public_key"])
    except IntegrityError as exc:
        raise _key_in_use() from exc
