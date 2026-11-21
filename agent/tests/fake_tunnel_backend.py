"""In-memory implementation of TunnelBackend, for the tests of the loop."""

import base64
import ipaddress
import uuid
from typing import Any

from h42mesh.agent.messages import AddressFamily, TunnelSide
from h42mesh.agent.tunnels.backend import (
    KEEPALIVE,
    PeerEndpoint,
    TunnelBackend,
    TunnelError,
    TunnelSpec,
    TunnelStatus,
)


def key(byte: int) -> str:
    return base64.b64encode(bytes([byte]) * 32).decode()


def make_spec(**overrides: Any) -> TunnelSpec:
    """A valid side-b spec; override any field."""
    values: dict[str, Any] = {
        "tunnel_id": uuid.UUID(int=7),
        "name": "wd0c0parir0c0",
        "side": TunnelSide.B,
        "private_key": key(1),
        "listen_port": 42001,
        "peer_public_key": key(2),
        "preshared_key": key(3),
        "local_ipv4": ipaddress.IPv4Interface("169.254.12.35/31"),
        "local_ipv6": ipaddress.IPv6Interface("fe80::a9fe:c23/127"),
        "peer_endpoints": (
            PeerEndpoint(
                family=AddressFamily.IPV6, address=ipaddress.ip_address("2001:db8::1"), port=42000
            ),
            PeerEndpoint(
                family=AddressFamily.IPV4, address=ipaddress.ip_address("198.51.100.1"), port=42000
            ),
        ),
        "keepalive": KEEPALIVE,
    }
    values.update(overrides)
    if values["side"] is TunnelSide.A and "peer_endpoints" not in overrides:
        values["peer_endpoints"] = ()
        values["keepalive"] = None
    return TunnelSpec(**values)


class FakeTunnelBackend:
    """Tunnels in a dict; ``None`` marks an interface left over (not managed)."""

    def __init__(self, prefix: str = "wd0c0", left_over: tuple[str, ...] = ()) -> None:
        self.prefix = prefix
        self.tunnels: dict[str, TunnelSpec | None] = dict.fromkeys(left_over)
        self.calls: list[tuple[str, str]] = []
        self.failing: set[str] = set()  # names whose operations fail
        self.closed = False

    def _check(self, operation: str, name: str) -> None:
        self.calls.append((operation, name))
        if name in self.failing:
            raise TunnelError(f"{name}: {operation} failed")

    async def create(self, spec: TunnelSpec) -> None:
        self._check("create", spec.name)
        if spec.name in self.tunnels:
            raise TunnelError(f"{spec.name}: already exists")
        self.tunnels[spec.name] = spec

    async def update(self, spec: TunnelSpec) -> None:
        self._check("update", spec.name)
        if self.tunnels.get(spec.name) is None:
            raise TunnelError(f"{spec.name}: not managed")
        self.tunnels[spec.name] = spec

    async def delete(self, name: str) -> None:
        self._check("delete", name)
        self.tunnels.pop(name, None)

    async def status(self, name: str) -> TunnelStatus | None:
        if name not in self.tunnels:
            return None
        spec = self.tunnels[name]
        return TunnelStatus(
            name=name, tunnel_id=spec.tunnel_id if spec else None, running=spec is not None
        )

    async def list(self) -> list[str]:
        return sorted(self.tunnels)

    async def close(self) -> None:
        self.closed = True
        self.tunnels.clear()


_: TunnelBackend = FakeTunnelBackend()  # checked by mypy against the interface
