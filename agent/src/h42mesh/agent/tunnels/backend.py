"""Interface of the WireGuard tunnel management (the tunnel *backend*).

The rest of the agent (reconciliation, IPC, main process) only knows this
interface: the implementation (wireguard-go today, maybe the kernel module in a
network namespace tomorrow) is chosen in one place, the factory of the
connection instance (h42mesh.agent.worker).

A backend manages the tunnels of one internet connection: it runs in the
instance of that connection, in its VRF.
"""

import ipaddress
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from h42mesh.agent.config.names import TUNNEL_NAME_PATTERN
from h42mesh.agent.messages import AddressFamily, Key, Port, TunnelSide

KEEPALIVE = 25  # seconds, on the side that initiates (b)
ALLOWED_IPS = ("0.0.0.0/0", "::/0")  # WireGuard installs no route: BGP chooses

TunnelName = Annotated[str, Field(pattern=TUNNEL_NAME_PATTERN)]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PeerEndpoint(_Frozen):
    """A public address and port of the other end (a), for b."""

    family: AddressFamily
    address: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: Port

    @model_validator(mode="after")
    def _family_matches(self) -> "PeerEndpoint":
        if self.address.version != (4 if self.family is AddressFamily.IPV4 else 6):
            raise ValueError(f"{self.address} is not an {self.family} address")
        return self

    def text(self) -> str:
        """As written by WireGuard: ``198.51.100.1:42000`` or ``[2001:db8::1]:42000``."""
        if self.address.version == 6:
            return f"[{self.address}]:{self.port}"
        return f"{self.address}:{self.port}"


class TunnelSpec(_Frozen):
    """Wanted state of one tunnel end. Secrets are kept out of ``repr``."""

    tunnel_id: UUID
    name: TunnelName
    side: TunnelSide
    private_key: Key = Field(repr=False)
    listen_port: Port
    peer_public_key: Key
    preshared_key: Key = Field(repr=False)
    local_ipv4: ipaddress.IPv4Interface  # 169.254.x.y/31
    local_ipv6: ipaddress.IPv6Interface  # fe80::a9fe:…/127
    # Side b only, in order of preference (IPv6 first); one per family at most.
    peer_endpoints: tuple[PeerEndpoint, ...] = ()
    keepalive: Annotated[int, Field(ge=1, le=65535)] | None = None
    fallback_delay: Annotated[int, Field(ge=1)] = 30  # seconds
    ipv6_retry: Annotated[int, Field(ge=1)] = 600  # seconds

    @model_validator(mode="after")
    def _consistent(self) -> "TunnelSpec":
        if self.local_ipv4.network.prefixlen != 31 or self.local_ipv6.network.prefixlen != 127:
            raise ValueError("tunnel addresses are a /31 and a /127")
        families = [e.family for e in self.peer_endpoints]
        if len(set(families)) != len(families):
            raise ValueError("at most one peer endpoint per family")
        if self.side is TunnelSide.A and self.peer_endpoints:
            raise ValueError("side a listens: no peer endpoint")
        if self.side is TunnelSide.B and not self.peer_endpoints:
            raise ValueError("side b initiates: at least one peer endpoint")
        return self


class TunnelStatus(_Frozen):
    """Observed state of one tunnel interface."""

    name: str
    tunnel_id: UUID | None  # None: an interface this backend does not manage
    running: bool  # the process (or the interface) is up
    family_in_use: AddressFamily | None = None  # with a recent handshake
    endpoint: str | None = None  # current address and port of the other end
    last_handshake_at: datetime | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    restarts: int = 0


class TunnelError(Exception):
    """A tunnel could not be created, updated or deleted."""


class TunnelBackend(Protocol):
    """Management of the tunnels of one connection."""

    async def create(self, spec: TunnelSpec) -> None:
        """Interface, keys, PSK, peer, addresses; supervised until deleted."""

    async def update(self, spec: TunnelSpec) -> None:
        """Apply the differences with the current state (peer, endpoints, delays)."""

    async def delete(self, name: str) -> None:
        """Stop the tunnel and remove its interface (also one it does not manage)."""

    async def status(self, name: str) -> TunnelStatus | None:
        """None if the tunnel does not exist."""

    async def list(self) -> list[str]:
        """Names of the existing tunnels of the connection, managed or left over."""

    async def close(self) -> None:
        """Stop every tunnel (the instance is stopping)."""
