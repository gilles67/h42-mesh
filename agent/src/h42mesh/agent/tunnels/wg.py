"""Text exchanged with ``wg`` (wireguard-tools, a separate GPL program): pure functions.

- the configuration given to ``wg syncconf <iface> /dev/stdin``: secrets go
  through the standard input, never through a file; ``syncconf`` only applies
  the differences;
- the output of ``wg show <iface> dump``.
"""

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime

from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.tunnels.backend import ALLOWED_IPS, PeerEndpoint, TunnelSpec


def render_config(spec: TunnelSpec, endpoint: PeerEndpoint | None) -> str:
    """Configuration of the interface and of its single peer."""
    lines = [
        "[Interface]",
        f"PrivateKey = {spec.private_key}",
        f"ListenPort = {spec.listen_port}",
        "",
        "[Peer]",
        f"PublicKey = {spec.peer_public_key}",
        f"PresharedKey = {spec.preshared_key}",
        f"AllowedIPs = {', '.join(ALLOWED_IPS)}",
    ]
    if endpoint is not None:
        lines.append(f"Endpoint = {endpoint.text()}")
    if spec.keepalive is not None:
        lines.append(f"PersistentKeepalive = {spec.keepalive}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class PeerDump:
    public_key: str
    endpoint: str | None
    latest_handshake: float | None  # UNIX time; None: never
    rx_bytes: int
    tx_bytes: int

    @property
    def last_handshake_at(self) -> datetime | None:
        if self.latest_handshake is None:
            return None
        return datetime.fromtimestamp(self.latest_handshake, UTC)


@dataclass(frozen=True)
class InterfaceDump:
    public_key: str
    listen_port: int
    peers: list[PeerDump]


class DumpError(ValueError):
    pass


def parse_dump(text: str) -> InterfaceDump:
    """``wg show <iface> dump``: one tab-separated line for the interface, then one per peer.

    interface: private-key public-key listen-port fwmark
    peer:      public-key preshared-key endpoint allowed-ips latest-handshake
               transfer-rx transfer-tx persistent-keepalive
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise DumpError("empty output")
    head = lines[0].split("\t")
    if len(head) != 4:
        raise DumpError("unexpected interface line")
    peers = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 8:
            raise DumpError("unexpected peer line")
        try:
            handshake = int(fields[4])
            peers.append(
                PeerDump(
                    public_key=fields[0],
                    endpoint=None if fields[2] == "(none)" else fields[2],
                    latest_handshake=float(handshake) if handshake > 0 else None,
                    rx_bytes=int(fields[5]),
                    tx_bytes=int(fields[6]),
                )
            )
        except ValueError as exc:
            raise DumpError(f"unexpected peer line: {exc}") from exc
    try:
        port = int(head[2])
    except ValueError as exc:
        raise DumpError("unexpected listen port") from exc
    return InterfaceDump(public_key=head[1], listen_port=port, peers=peers)


def endpoint_family(endpoint: str | None) -> AddressFamily | None:
    """Family of ``198.51.100.1:42000`` or ``[2001:db8::1]:42000``."""
    if not endpoint:
        return None
    host = endpoint.rsplit(":", 1)[0].strip("[]")
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None
    return AddressFamily.IPV4 if address.version == 4 else AddressFamily.IPV6
