"""Access to the operating system (Linux): VRFs, sockets, processes.

Kept apart from the logic so that the rest is tested anywhere; this module is
covered by the integration tests (Linux, root).
"""

import asyncio
import os
import signal
import socket
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

RUNTIME_DIR_ENV = "H42_MESH_AGENT_RUNTIME_DIR"
DEFAULT_RUNTIME_DIR = Path("/run/h42-mesh")
SOCKET_NAME = "agent.sock"
STREAM_LIMIT = 32 * 1024 * 1024  # largest IPC line (a BGP table report)
IN_VRF_ENV = "H42_MESH_AGENT_IN_VRF"  # set when the agent re-executed itself in a VRF

# Destinations used to test that a family is routed (UDP connect sends nothing).
_PROBES = {4: ("192.0.2.1", 4), 6: ("2001:db8::1", 6)}


def runtime_dir() -> Path:
    return Path(os.environ.get(RUNTIME_DIR_ENV) or DEFAULT_RUNTIME_DIR)


def socket_path() -> Path:
    return runtime_dir() / SOCKET_NAME


def vrf_exists(name: str) -> bool:
    """A VRF device with this name exists (created by the system configuration)."""
    if not (Path("/sys/class/net") / name).exists():
        return False
    result = subprocess.run(  # noqa: S603 (fixed command, name from validated config)
        ["ip", "-d", "link", "show", "dev", name],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and " vrf table " in result.stdout


def family_available(version: int) -> bool:
    """The current VRF has a route for this family (checked by UDP connect)."""
    address, family = _PROBES[version]
    sock = socket.socket(socket.AF_INET if family == 4 else socket.AF_INET6, socket.SOCK_DGRAM)
    try:
        sock.connect((address, 53))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def run_in_vrf(vrf: str, argv: Sequence[str]) -> int:
    """Run the same agent command inside a VRF (``ip vrf exec``) and wait for it."""
    env = {**os.environ, IN_VRF_ENV: vrf}
    return subprocess.run(["ip", "vrf", "exec", vrf, *argv], env=env, check=False).returncode  # noqa: S603, S607


def in_vrf() -> str | None:
    return os.environ.get(IN_VRF_ENV) or None


Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


def _prepare_socket_path(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        path.unlink()  # left by a previous run


async def start_unix_server(path: Path, handler: Handler) -> asyncio.AbstractServer:
    """Listening socket of the main process, readable by root only."""
    _prepare_socket_path(path)
    previous = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(handler, path=str(path), limit=STREAM_LIMIT)
    finally:
        os.umask(previous)
    os.chmod(path, 0o600)
    return server


async def open_unix_connection(
    path: Path,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_unix_connection(str(path), limit=STREAM_LIMIT)


SYS_CLASS_NET = Path("/sys/class/net")


def interface_exists(name: str) -> bool:
    return (SYS_CLASS_NET / name).exists()


def interface_master(name: str) -> str | None:
    """The device the interface is attached to (its VRF), or None."""
    master = SYS_CLASS_NET / name / "master"
    try:
        return os.path.basename(os.readlink(master))
    except OSError:
        return None


def notify_service(pid: int) -> bool:
    """Ask the running service to reload agent.toml now (SIGHUP)."""
    hangup = getattr(signal, "SIGHUP", None)
    if hangup is None:
        return False
    try:
        os.kill(pid, hangup)
    except OSError:
        return False
    return True
