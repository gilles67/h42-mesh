"""Linux network device names (interfaces and VRFs)."""

IFNAMSIZ = 16  # including the final NUL: 15 usable characters
MAX_NAME_LENGTH = IFNAMSIZ - 1
# Names of the main routing table: never a dedicated VRF.
RESERVED_VRF_NAMES = frozenset({"default", "main"})


def check_device_name(value: str) -> str:
    """Rules of the kernel (dev_valid_name): 1 to 15 characters, no '/', ':' or
    whitespace, neither '.' nor '..'."""
    if not value:
        raise ValueError("an interface name cannot be empty")
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{value!r} is longer than {MAX_NAME_LENGTH} characters")
    if value in {".", ".."}:
        raise ValueError(f"{value!r} is not a valid interface name")
    if any(c in "/:" or c.isspace() for c in value):
        raise ValueError(f"{value!r} contains '/', ':' or whitespace")
    return value


def check_vrf_name(value: str) -> str:
    check_device_name(value)
    if value in RESERVED_VRF_NAMES:
        raise ValueError(f"{value!r} is the default VRF: use a dedicated VRF")
    return value


TUNNEL_PREFIX = "wd"


def tunnel_interface_prefix(mesh_number: int, local_connection: int) -> str:
    """Start of the names of the tunnels of one local connection: ``wd<mesh>c<n>``."""
    if not (0 <= mesh_number <= 9 and 0 <= local_connection <= 9):
        raise ValueError("mesh and connection numbers are 0 to 9")
    return f"{TUNNEL_PREFIX}{mesh_number}c{local_connection}"


def tunnel_interface_name(
    mesh_number: int,
    local_connection: int,
    site_nickname: str,
    router_number: int,
    remote_connection: int,
) -> str:
    """``wd<mesh>c<local connection><remote site>r<remote router>c<remote connection>``.

    13 characters, unique on a router: a tunnel joins one pair of connections.
    """
    if len(site_nickname) != 4 or not all(c in _NICKNAME_CHARS for c in site_nickname):
        raise ValueError(f"{site_nickname!r} is not a site nickname ([a-z0-9]{{4}})")
    if not (0 <= router_number <= 9 and 0 <= remote_connection <= 9):
        raise ValueError("router and connection numbers are 0 to 9")
    name = (
        tunnel_interface_prefix(mesh_number, local_connection)
        + f"{site_nickname}r{router_number}c{remote_connection}"
    )
    return check_device_name(name)


_NICKNAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
TUNNEL_NAME_PATTERN = r"^wd[0-9]c[0-9][a-z0-9]{4}r[0-9]c[0-9]$"
