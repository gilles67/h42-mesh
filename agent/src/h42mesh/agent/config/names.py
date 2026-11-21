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
