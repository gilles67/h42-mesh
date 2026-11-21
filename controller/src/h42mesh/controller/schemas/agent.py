"""Messages exchanged with the agents (the agent keeps its own copy of them)."""

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from tortoise.exceptions import ValidationError

from h42mesh.controller.models import AddressFamily, BgpRouteSource, ConnectionRole, DirectMode
from h42mesh.controller.models.validators import PublicKeyValidator


class TunnelSide(StrEnum):
    A = "a"  # listens
    B = "b"  # initiates


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


# --- router configuration ----------------------------------------------------


class ConfigMesh(BaseModel):
    id: UUID
    name: str


class ConfigSite(BaseModel):
    id: UUID
    nickname: str
    asn: int


class ConfigRouter(BaseModel):
    id: UUID
    number: int
    name: str


class ConfigConnection(BaseModel):
    id: UUID
    number: int
    name: str
    role: ConnectionRole
    priority: int | None
    direct: DirectMode
    public_ipv4: str | None
    public_ipv6: str | None


class Endpoint(BaseModel):
    family: AddressFamily
    address: str


class ConfigPeer(BaseModel):
    connection_id: UUID
    site_nickname: str
    site_asn: int
    router_number: int
    connection_number: int
    public_key: str | None = Field(description="Peer WireGuard public key, once reported")
    port: int | None = Field(description="Port of a, sent to b only")
    endpoints: list[Endpoint] = Field(
        description="Public addresses of a, for b only: families a accepts, IPv6 first"
    )


class ConfigTunnel(BaseModel):
    id: UUID
    side: TunnelSide
    role: ConnectionRole
    families: list[AddressFamily]
    local_connection_id: UUID
    ipv4_network: str
    ipv6_network: str
    local_ipv4: str
    local_ipv6: str
    peer_ipv4: str
    peer_ipv6: str
    local_public_key: str | None = Field(description="As registered by the controller")
    local_port: int | None = Field(description="As registered: reuse it")
    preshared_key: str
    peer: ConfigPeer


class RouterConfig(BaseModel):
    format: int = Field(description="Version of this format")
    fingerprint: str = Field(description="SHA-256 of the configuration; also the ETag")
    mesh: ConfigMesh
    site: ConfigSite
    router: ConfigRouter
    connections: list[ConfigConnection]
    tunnels: list[ConfigTunnel]


# --- reports -----------------------------------------------------------------


class PublicAddressReport(_Request):
    connection_id: UUID
    family: AddressFamily
    forced_address: str | None = Field(
        default=None, max_length=45, description="Recorded instead of the source address"
    )


class PublicAddressResult(BaseModel):
    family: AddressFamily
    address: str
    isp: str | None


Port = Annotated[int, Field(ge=1, le=65535)]


class TunnelKeyReport(_Request):
    tunnel_id: UUID
    public_key: SigningPublicKey  # same format as WireGuard keys: base64 of 32 bytes
    port: Port


class TunnelKeysReport(_Request):
    tunnels: list[TunnelKeyReport] = Field(max_length=1000)


class TunnelStatusReport(_Request):
    tunnel_id: UUID
    family_in_use: AddressFamily | None = None
    last_handshake_at: datetime | None = None
    bgp_established: bool = False


class TunnelStatusesReport(_Request):
    tunnels: list[TunnelStatusReport] = Field(max_length=1000)


class BgpRouteReport(_Request):
    prefix: str = Field(max_length=43)
    source: BgpRouteSource
    tunnel_id: UUID | None = None
    as_path: list[Annotated[int, Field(ge=0, le=4_294_967_295)]] = Field(max_length=255)
    origin_asn: int | None = Field(default=None, ge=0, le=4_294_967_295)
    is_best: bool
    is_backup: bool
    local_pref: int | None = Field(default=None, ge=0, le=4_294_967_295)

    @field_validator("prefix")
    @classmethod
    def _canonical_network(cls, value: str) -> str:
        try:
            network = ipaddress.ip_network(value, strict=True)
        except ValueError as exc:
            raise ValueError(f"{value!r} is not a network") from exc
        if str(network) != value:
            raise ValueError(f"{value!r} is not in canonical form ({network})")
        return value

    @model_validator(mode="after")
    def _tunnel_iff_source_tunnel(self) -> "BgpRouteReport":
        if (self.tunnel_id is not None) != (self.source is BgpRouteSource.TUNNEL):
            raise ValueError("tunnel_id is required if and only if source is 'tunnel'")
        return self


class BgpRoutesReport(_Request):
    routes: list[BgpRouteReport] = Field(max_length=10_000)
