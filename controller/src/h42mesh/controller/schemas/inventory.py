"""Sites, routers and internet connections, as seen by the GUI."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from h42mesh.controller.models import ConnectionRole, DirectMode
from h42mesh.controller.models.validators import ASN_MAX, ASN_MIN
from h42mesh.controller.schemas.meshes import Name, PatchRequest

Nickname = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{4}$")]
Location = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
Asn = Annotated[int, Field(ge=ASN_MIN, le=ASN_MAX)]
Description = Annotated[str, StringConstraints(max_length=2000)]
Priority = Annotated[int, Field(ge=0, le=1_000_000)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- sites -------------------------------------------------------------------


class SiteCreate(_Request):
    name: Name
    nickname: Nickname = Field(description="Four-letter code, unique in the mesh")
    location: Location | None = None
    asn: Asn = Field(description="Private 4-byte AS, unique in the mesh")


class SiteUpdate(PatchRequest):
    required_fields = frozenset({"name", "nickname", "asn"})

    name: Name | None = None
    nickname: Nickname | None = None
    location: Location | None = None
    asn: Asn | None = None


class SiteRead(BaseModel):
    id: UUID
    mesh_id: UUID
    name: str
    nickname: str
    location: str | None
    asn: int
    created_at: datetime


# --- routers -----------------------------------------------------------------


class RouterCreate(_Request):
    number: int = Field(ge=0, le=1, description="r0 or r1; cannot be changed afterwards")
    name: Name


class RouterUpdate(PatchRequest):
    required_fields = frozenset({"name"})

    name: Name | None = None


class RouterRead(BaseModel):
    id: UUID
    site_id: UUID
    number: int
    name: str
    enrolled: bool  # an agent signing key is known
    signing_key_revoked: bool
    enrolled_at: datetime | None
    last_seen_at: datetime | None
    routes_reported_at: datetime | None
    created_at: datetime


# --- connections -------------------------------------------------------------


class ConnectionCreate(_Request):
    number: int = Field(ge=0, le=9, description="c0 to c9; cannot be changed afterwards")
    name: Name
    role: ConnectionRole
    priority: Priority | None = None
    direct: DirectMode = DirectMode.NONE
    description: Description | None = None


class ConnectionUpdate(PatchRequest):
    required_fields = frozenset({"name", "role", "direct"})

    name: Name | None = None
    role: ConnectionRole | None = None
    priority: Priority | None = None
    direct: DirectMode | None = None
    description: Description | None = None


class ConnectionRead(BaseModel):
    id: UUID
    router_id: UUID
    number: int
    name: str
    role: ConnectionRole
    priority: int | None
    direct: DirectMode
    description: str | None
    # Reported by the agent and the controller, never entered by hand.
    isp: str | None
    public_ipv4: str | None
    public_ipv4_updated_at: datetime | None
    public_ipv6: str | None
    public_ipv6_updated_at: datetime | None
    created_at: datetime
