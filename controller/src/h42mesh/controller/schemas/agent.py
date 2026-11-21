"""Messages exchanged with the agents (the agent keeps its own copy of them)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from tortoise.exceptions import ValidationError

from h42mesh.controller.models.validators import PublicKeyValidator


def _check_public_key(value: str) -> str:
    try:
        PublicKeyValidator()(value)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return value


SigningPublicKey = Annotated[
    str,
    Field(min_length=44, max_length=44, description="Ed25519 public key, base64 (32 bytes)"),
    AfterValidator(_check_public_key),
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrollRequest(_Request):
    token: str = Field(min_length=1, max_length=256, description="Single-use enrollment token")
    signing_public_key: SigningPublicKey


class EnrollResponse(BaseModel):
    router_id: UUID = Field(description="Router id: iss and sub of the agent's JWTs")


class SigningKeyRenewal(_Request):
    signing_public_key: SigningPublicKey


class AgentIdentity(BaseModel):
    router_id: UUID
    mesh_id: UUID
    site_nickname: str
    router_number: int


class EnrollmentTokenCreated(BaseModel):
    token: str = Field(description="Shown once; only its digest is stored")
    expires_at: datetime
