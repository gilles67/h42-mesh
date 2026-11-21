"""Tunnels as seen by the GUI: computed by the controller, never the PSK."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from h42mesh.controller.models import AddressFamily, ConnectionRole


class TunnelEnd(BaseModel):
    connection_id: UUID
    site_id: UUID
    site_nickname: str
    router_id: UUID
    router_number: int
    connection_number: int
    public_key: str | None = Field(description="WireGuard public key, reported by the agent")
    port: int | None = Field(description="Port chosen and reported by the agent")


class TunnelRead(BaseModel):
    id: UUID
    mesh_id: UUID
    a: TunnelEnd = Field(description="Listening end; first address of each pair")
    b: TunnelEnd = Field(description="Initiating end; second address of each pair")
    ipv4_network: str
    ipv6_network: str
    role: ConnectionRole = Field(description="Weaker role of both ends")
    families: list[AddressFamily] = Field(
        description="Families in which a accepts inbound connections, IPv6 first"
    )
    created_at: datetime
