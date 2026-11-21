"""Messages exchanged with the controller: the agent's own copy of the models.

There is no package shared with the controller; the reference is the
controller's OpenAPI description (openapi/controller.json), checked by
tests/test_openapi_compat.py.

- Responses of the controller ignore unknown fields (``extra="ignore"``):
  a newer controller adding a field does not break an older agent.
- Requests built by the agent forbid unknown fields (``extra="forbid"``):
  a typo in the agent's code fails here rather than at the controller.
"""

import base64
import binascii
import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

API_PREFIX = "/api/v1"


class Response(BaseModel):
    """Base of every message received from the controller."""

    model_config = ConfigDict(extra="ignore")


class Request(BaseModel):
    """Base of every message sent to the controller."""

    model_config = ConfigDict(extra="forbid")


def _base64_key(value: str) -> str:
    """Base64 of a 32-byte key (WireGuard, Ed25519, PSK): 44 characters."""
    try:
        raw = base64.b64decode(value, validate=True)
    except binascii.Error as exc:
        raise ValueError("not valid base64") from exc
    if len(raw) != 32:
        raise ValueError("not a 32-byte key")
    return value


Key = Annotated[str, AfterValidator(_base64_key)]
Uint32 = Annotated[int, Field(ge=0, le=4_294_967_295)]
Port = Annotated[int, Field(ge=1, le=65535)]


# --- enumerations ------------------------------------------------------------


class AddressFamily(StrEnum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"


class ConnectionRole(StrEnum):
    ACTIVE = "active"
    BACKUP = "backup"


class DirectMode(StrEnum):
    NONE = "none"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    BOTH = "both"


class TunnelSide(StrEnum):
    A = "a"  # listens
    B = "b"  # initiates


class BgpRouteSource(StrEnum):
    LOCAL = "local"
    TUNNEL = "tunnel"
    INTERNAL = "internal"


# --- errors and identity -----------------------------------------------------


class ErrorResponse(Response):
    code: str
    message: str


class EnrollRequest(Request):
    token: str = Field(min_length=1, max_length=256)
    signing_public_key: Key


class EnrollResponse(Response):
    router_id: UUID


class SigningKeyRenewal(Request):
    signing_public_key: Key


class AgentIdentity(Response):
    router_id: UUID
    mesh_id: UUID
    site_nickname: str
    router_number: int


# --- router configuration ----------------------------------------------------


class ConfigMesh(Response):
    id: UUID
    name: str


class ConfigSite(Response):
    id: UUID
    nickname: str
    asn: int


class ConfigRouter(Response):
    id: UUID
    number: int
    name: str


class ConfigConnection(Response):
    id: UUID
    number: int
    name: str
    role: ConnectionRole
    priority: int | None
    direct: DirectMode
    public_ipv4: ipaddress.IPv4Address | None
    public_ipv6: ipaddress.IPv6Address | None


class Endpoint(Response):
    family: AddressFamily
    address: ipaddress.IPv4Address | ipaddress.IPv6Address

    @model_validator(mode="after")
    def _family_matches(self) -> "Endpoint":
        expected = 4 if self.family is AddressFamily.IPV4 else 6
        if self.address.version != expected:
            raise ValueError(f"{self.address} is not an {self.family} address")
        return self


class ConfigPeer(Response):
    connection_id: UUID
    site_nickname: str
    site_asn: int
    router_number: int
    connection_number: int
    public_key: Key | None
    port: Port | None  # port of a, for b only
    endpoints: list[Endpoint]  # public addresses of a, for b only


class ConfigTunnel(Response):
    id: UUID
    side: TunnelSide
    role: ConnectionRole
    families: list[AddressFamily]
    local_connection_id: UUID
    ipv4_network: ipaddress.IPv4Network
    ipv6_network: ipaddress.IPv6Network
    local_ipv4: ipaddress.IPv4Address
    local_ipv6: ipaddress.IPv6Address
    peer_ipv4: ipaddress.IPv4Address
    peer_ipv6: ipaddress.IPv6Address
    local_public_key: Key | None
    local_port: Port | None
    preshared_key: Key
    peer: ConfigPeer


class RouterConfig(Response):
    format: int
    fingerprint: str
    mesh: ConfigMesh
    site: ConfigSite
    router: ConfigRouter
    connections: list[ConfigConnection]
    tunnels: list[ConfigTunnel]


# --- reports -----------------------------------------------------------------


class PublicAddressReport(Request):
    connection_id: UUID
    family: AddressFamily
    forced_address: str | None = Field(default=None, max_length=45)


class PublicAddressResult(Response):
    family: AddressFamily
    address: ipaddress.IPv4Address | ipaddress.IPv6Address
    isp: str | None


class TunnelKeyReport(Request):
    tunnel_id: UUID
    public_key: Key
    port: Port


class TunnelKeysReport(Request):
    tunnels: list[TunnelKeyReport] = Field(max_length=1000)


class TunnelStatusReport(Request):
    tunnel_id: UUID
    family_in_use: AddressFamily | None = None
    last_handshake_at: datetime | None = None
    bgp_established: bool = False


class TunnelStatusesReport(Request):
    tunnels: list[TunnelStatusReport] = Field(max_length=1000)


class BgpRouteReport(Request):
    prefix: str = Field(max_length=43)
    source: BgpRouteSource
    tunnel_id: UUID | None = None
    as_path: list[Uint32] = Field(max_length=255)
    origin_asn: Uint32 | None = None
    is_best: bool
    is_backup: bool
    local_pref: Uint32 | None = None

    @model_validator(mode="after")
    def _tunnel_iff_source_tunnel(self) -> "BgpRouteReport":
        if (self.tunnel_id is not None) != (self.source is BgpRouteSource.TUNNEL):
            raise ValueError("tunnel_id is required if and only if source is 'tunnel'")
        return self


class BgpRoutesReport(Request):
    routes: list[BgpRouteReport] = Field(max_length=10_000)


# --- endpoints used by the agent ---------------------------------------------

# (method, path) -> (request model, response model); None: no body.
ENDPOINTS: dict[tuple[str, str], tuple[type[Request] | None, type[Response] | None]] = {
    ("POST", "/agent/enroll"): (EnrollRequest, EnrollResponse),
    ("GET", "/agent/me"): (None, AgentIdentity),
    ("PUT", "/agent/signing-key"): (SigningKeyRenewal, None),
    ("GET", "/agent/config"): (None, RouterConfig),
    ("POST", "/agent/public-address"): (PublicAddressReport, PublicAddressResult),
    ("POST", "/agent/tunnels"): (TunnelKeysReport, None),
    ("PUT", "/agent/tunnel-status"): (TunnelStatusesReport, None),
    ("PUT", "/agent/bgp-routes"): (BgpRoutesReport, None),
}
