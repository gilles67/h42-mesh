"""System settings of the main process (pure functions).

- ``net.ipv4.ip_local_reserved_ports``: the port range of the router is never
  given to outgoing connections (it applies to IPv6 too). Entries set by
  others are kept; entries inside the band of the mesh
  (``42000 + 2000 x mesh``, 2000 ports) but not the router's are removed (a
  previous router number, for instance);
- ``rp_filter`` loose (2) on the tunnel interfaces (also set when the tunnel
  is created, checked again here).
"""

from pathlib import Path

from h42mesh.agent.tunnels.plan import MESH_PORT_STEP, PORT_BASE

PROC_SYS = Path("/proc/sys/net")
RESERVED_PORTS = PROC_SYS / "ipv4" / "ip_local_reserved_ports"
LOOSE_RP_FILTER = "2"

PortRanges = list[tuple[int, int]]


def parse_ports(text: str) -> PortRanges:
    """``8080,42000-42999`` -> [(8080, 8080), (42000, 42999)]."""
    ranges = []
    for item in text.replace("\n", "").split(","):
        item = item.strip()
        if not item:
            continue
        low, _, high = item.partition("-")
        start, end = int(low), int(high or low)
        if not 0 < start <= end <= 65535:
            raise ValueError(f"invalid port range {item!r}")
        ranges.append((start, end))
    return sorted(ranges)


def format_ports(ranges: PortRanges) -> str:
    return ",".join(f"{a}-{b}" if a != b else str(a) for a, b in sorted(ranges))


def mesh_band(mesh_number: int) -> tuple[int, int]:
    start = PORT_BASE + MESH_PORT_STEP * mesh_number
    return start, start + MESH_PORT_STEP - 1


def reserved_ports(current: str, mesh_number: int, router: range) -> str:
    """The new value of ip_local_reserved_ports."""
    low, high = mesh_band(mesh_number)
    kept = [(a, b) for a, b in parse_ports(current) if not (low <= a and b <= high)]
    return format_ports([*kept, (router.start, router.stop - 1)])


def same_ports(a: str, b: str) -> bool:
    """Same ports, however written (the kernel merges adjacent ranges)."""

    def ports(text: str) -> set[int]:
        return {port for start, end in parse_ports(text) for port in range(start, end + 1)}

    return ports(a) == ports(b)


def rp_filter_path(interface: str) -> Path:
    return PROC_SYS / "ipv4" / "conf" / interface / "rp_filter"
