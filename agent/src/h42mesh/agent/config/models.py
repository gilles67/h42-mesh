"""Local configuration of the agent (/etc/h42-mesh/agent.toml).

Static validation only (types, formats, bounds, duplicates). Consistency with
the machine and the controller (interfaces and VRFs exist, UIDs match the
router's connections, port ranges overlap the router's range) is checked by
the agent at run time.
"""

import ipaddress
from collections import Counter
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, model_validator

from h42mesh.agent.config.names import check_device_name, check_vrf_name

DEFAULT_DNS_SERVERS = (
    "1.1.1.1",
    "2606:4700:4700::1111",
    "8.8.8.8",
    "2001:4860:4860::8888",
)
DEFAULT_STATE_DIR = PurePosixPath("/var/lib/h42-mesh")
DEFAULT_JWT_AUDIENCE = "h42-mesh-controller"
LINK_LOCAL = ipaddress.IPv6Network("fe80::/10")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _duplicates(values: Iterable[object]) -> list[object]:
    return [value for value, count in Counter(values).items() if count > 1]


# --- field types -------------------------------------------------------------


def controller_url(value: str) -> str:
    """An HTTPS origin: https://host[:port], nothing else; normalised."""
    parts = urlsplit(value.strip())
    if parts.scheme.lower() != "https":
        raise ValueError(f"{value!r}: only https:// is accepted")
    if not parts.hostname:
        raise ValueError(f"{value!r}: missing host name")
    if parts.username or parts.password:
        raise ValueError(f"{value!r}: credentials are not allowed in the URL")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError(f"{value!r}: give the origin only (https://name[:port])")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"{value!r}: invalid port") from exc
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    return f"https://{host}" + (f":{port}" if port not in (None, 443) else "")


ControllerUrl = Annotated[str, AfterValidator(controller_url)]
DeviceName = Annotated[str, AfterValidator(check_device_name)]
VrfName = Annotated[str, AfterValidator(check_vrf_name)]


def _absolute(value: PurePosixPath) -> PurePosixPath:
    if not value.is_absolute():
        raise ValueError(f"{value} is not an absolute path")
    return value


AbsolutePath = Annotated[PurePosixPath, AfterValidator(_absolute)]


def _link_local(value: ipaddress.IPv6Address) -> ipaddress.IPv6Address:
    if value not in LINK_LOCAL or value.scope_id is not None:
        raise ValueError(f"{value} is not a link-local address (fe80::/10, without zone)")
    return value


def _public_ipv4(value: ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    if not value.is_global or value.is_multicast:
        raise ValueError(f"{value} is not a public IPv4 address")
    return value


def _global_ipv6(value: ipaddress.IPv6Address) -> ipaddress.IPv6Address:
    if not value.is_global or value.is_multicast or value.scope_id is not None:
        raise ValueError(f"{value} is not a global IPv6 address")
    return value


# --- models ------------------------------------------------------------------


class PortRange(_Model):
    """Ports a connection may use (shared IPv4, ports opened by a box), both families."""

    min: Annotated[StrictInt, Field(ge=1, le=65535)]
    max: Annotated[StrictInt, Field(ge=1, le=65535)]

    @model_validator(mode="after")
    def _ordered(self) -> "PortRange":
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) is greater than max ({self.max})")
        return self


class InternalLink(_Model):
    """Link to the other router of a two-router site (iBGP session)."""

    interface: DeviceName
    peer_link_local: Annotated[ipaddress.IPv6Address, AfterValidator(_link_local)]


class ConnectionSettings(_Model):
    """Local settings of an internet connection, designated by its controller UID."""

    uid: UUID
    interface: DeviceName
    vrf: VrfName
    ports: PortRange | None = None
    force_ipv4: Annotated[ipaddress.IPv4Address, AfterValidator(_public_ipv4)] | None = None
    force_ipv6: Annotated[ipaddress.IPv6Address, AfterValidator(_global_ipv6)] | None = None
    fallback_delay: Annotated[StrictInt, Field(ge=5, le=3600)] = 30  # seconds
    ipv6_retry: Annotated[StrictInt, Field(ge=60, le=86400)] = 600  # seconds


class AgentConfig(_Model):
    """The whole agent.toml file."""

    controllers: Annotated[list[ControllerUrl], Field(min_length=1, max_length=2)]
    mesh_number: Annotated[StrictInt, Field(ge=0, le=9)] = 0
    dns_servers: Annotated[
        list[ipaddress.IPv4Address | ipaddress.IPv6Address], Field(min_length=1)
    ] = Field(default_factory=lambda: [ipaddress.ip_address(a) for a in DEFAULT_DNS_SERVERS])
    state_dir: AbsolutePath = DEFAULT_STATE_DIR
    # Expected "aud" of the agent JWTs (H42_MESH_AGENT_JWT_AUDIENCE of the controller).
    jwt_audience: Annotated[str, Field(min_length=1, max_length=255)] = DEFAULT_JWT_AUDIENCE
    internal_link: InternalLink | None = None
    connections: list[ConnectionSettings] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicates(self) -> "AgentConfig":
        checks: list[tuple[str, list[object]]] = [
            ("controllers", list(self.controllers)),
            ("dns_servers", list(self.dns_servers)),
            ("connections: uid", [c.uid for c in self.connections]),
            ("connections: interface", [c.interface for c in self.connections]),
            ("connections: vrf", [c.vrf for c in self.connections]),
        ]
        for name, values in checks:
            duplicates = _duplicates(values)
            if duplicates:
                listed = ", ".join(str(d) for d in duplicates)
                raise ValueError(f"{name}: duplicate value {listed}")
        if self.internal_link is not None:
            shared = [c for c in self.connections if c.interface == self.internal_link.interface]
            if shared:
                raise ValueError(
                    f"connections: interface {self.internal_link.interface} is the internal link"
                )
        return self
