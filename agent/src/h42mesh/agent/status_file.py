"""State of the running agent, written by the main loop and read by ``status``.

/run/h42-mesh/status.json, rewritten atomically at each pass of the
observation loop (every 30 s). ``status`` reports a missing or stale file
(service stopped or blocked) and computes the problems from its content.
"""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from h42mesh.agent import system
from h42mesh.agent.messages import AddressFamily, ConnectionRole, TunnelSide
from h42mesh.agent.state import atomic_write

STATUS_NAME = "status.json"
STATUS_MODE = 0o644  # no secret in it
STALE_AFTER = timedelta(seconds=90)  # three passes missed
CONTROLLER_LOST_AFTER = timedelta(minutes=10)


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")  # read by a possibly newer status command


class IdentityStatus(_Model):
    router_id: UUID
    mesh_name: str | None = None
    site_nickname: str | None = None
    site_asn: int | None = None
    router_number: int | None = None


class ConfigStatus(_Model):
    fingerprint: str
    received_at: datetime
    controller: str


class ControllerStatus(_Model):
    last_success_at: datetime | None = None
    controller: str | None = None  # origin that answered last
    first_controller: bool | None = None  # the first of agent.toml, or the second
    via_connection: UUID | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None


class ConnectionStatus(_Model):
    uid: UUID
    number: int | None = None  # None: unknown to the controller
    name: str | None = None
    role: ConnectionRole | None = None
    interface: str
    vrf: str
    vrf_present: bool
    instance_connected: bool
    public_ipv4: str | None = None
    public_ipv6: str | None = None


class TunnelStatusEntry(_Model):
    tunnel_id: UUID
    name: str | None = None  # interface; None while pending
    local_connection: UUID
    remote: str  # "<site> r<router> c<connection>"
    side: TunnelSide
    role: ConnectionRole
    pending: str | None = None  # why it is not created yet
    running: bool = False
    family_in_use: AddressFamily | None = None
    endpoint: str | None = None
    last_handshake_at: datetime | None = None
    bgp_state: str | None = None


class InternalLinkStatus(_Model):
    interface: str
    peer_link_local: str
    bgp_state: str | None = None


class AgentStatus(_Model):
    written_at: datetime
    started_at: datetime
    pid: int
    last_pass_errors: list[str] = []
    identity: IdentityStatus | None = None
    config: ConfigStatus | None = None
    controller: ControllerStatus = ControllerStatus()
    connections: list[ConnectionStatus] = []
    tunnels: list[TunnelStatusEntry] = []
    internal_link: InternalLinkStatus | None = None


def status_path() -> Path:
    return system.runtime_dir() / STATUS_NAME


def write_status(status: AgentStatus, path: Path | None = None) -> None:
    path = path or status_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write(path, status.model_dump_json(indent=2).encode(), STATUS_MODE)


class StatusUnreadable(Exception):  # noqa: N818 (a state, not only an error)
    pass


def read_status(path: Path | None = None) -> AgentStatus | None:
    """None if there is no file (service never started since boot, or stopped)."""
    path = path or status_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StatusUnreadable(f"{path}: {exc}") from exc
    try:
        return AgentStatus.model_validate_json(text)
    except ValidationError as exc:
        raise StatusUnreadable(f"{path}: invalid content") from exc


def is_stale(status: AgentStatus, now: datetime) -> bool:
    return now - status.written_at > STALE_AFTER


def problems(status: AgentStatus | None, now: datetime) -> list[str]:
    """What is wrong, one line each; empty when everything works."""
    if status is None:
        return ["service not running: no status file (systemctl status h42-mesh-agent)"]
    found = []
    if is_stale(status, now):
        age = int((now - status.written_at).total_seconds())
        found.append(f"service stopped or blocked: status written {age} s ago")
    if status.identity is None:
        found.append("not enrolled")
    if status.config is None:
        found.append("no configuration received from the controller yet")
    contact = status.controller.last_success_at
    if (contact is None and now - status.started_at > CONTROLLER_LOST_AFTER) or (
        contact is not None and now - contact > CONTROLLER_LOST_AFTER
    ):
        found.append("controller not reached for more than 10 minutes")
    for c in status.connections:
        label = f"connection {f'c{c.number}' if c.number is not None else c.uid}"
        if not c.vrf_present:
            found.append(f"{label}: VRF {c.vrf} does not exist")
        elif not c.instance_connected:
            found.append(f"{label}: instance not running")
        if c.number is None:
            found.append(f"{label}: unknown to the controller")
    for t in status.tunnels:
        if t.pending is not None:
            continue  # waiting for the other end: not a failure of this router
        label = f"tunnel {t.name or t.tunnel_id}"
        if not t.running:
            found.append(f"{label}: not running")
        elif t.bgp_state != "Established":
            found.append(f"{label}: BGP session {t.bgp_state or 'unknown'}")
    link = status.internal_link
    if link is not None and link.bgp_state != "Established":
        found.append(f"internal link: iBGP session {link.bgp_state or 'unknown'}")
    return found
