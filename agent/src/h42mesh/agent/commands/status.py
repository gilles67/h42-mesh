"""h42-mesh-agent status (and without command): "does it work, and if not, where?".

Reads agent.toml and /run/h42-mesh/status.json (written by the service at
each pass). Exit code 0 when everything works, 1 when there is a problem
(service stopped, controller not reached for long, tunnel down…), 2 when
agent.toml is invalid.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from h42mesh.agent.commands import EXIT_OK, load_or_exit
from h42mesh.agent.config import AgentConfig, config_path
from h42mesh.agent.status_file import (
    AgentStatus,
    StatusUnreadable,
    is_stale,
    problems,
    read_status,
    status_path,
)

EXIT_PROBLEM = 1
NONE = "-"


def summary(config: AgentConfig) -> dict[str, object]:
    return {
        "controllers": config.controllers,
        "mesh_number": config.mesh_number,
        "state_dir": str(config.state_dir),
        "internal_link": config.internal_link.interface if config.internal_link else None,
        "connections": [
            {"uid": str(c.uid), "interface": c.interface, "vrf": c.vrf} for c in config.connections
        ],
    }


def ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "never"
    seconds = int((now - moment).total_seconds())
    if seconds < 120:
        return f"{seconds} s ago"
    if seconds < 7200:
        return f"{seconds // 60} min ago"
    if seconds < 172800:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def service_state(state: AgentStatus | None, now: datetime) -> str:
    if state is None:
        return "stopped"
    return "stale" if is_stale(state, now) else "running"


def _service_line(state: AgentStatus | None, file: Path, now: datetime) -> str:
    if state is None:
        return f"not running (no {file}): systemctl status h42-mesh-agent"
    written = ago(state.written_at, now)
    if is_stale(state, now):
        return f"STOPPED OR BLOCKED: status written {written} (pid {state.pid})"
    return f"running (pid {state.pid}, started {ago(state.started_at, now)}), status {written}"


def render_text(
    config: AgentConfig, file_config: Path, state: AgentStatus | None, file: Path, now: datetime
) -> list[str]:
    lines = []
    identity = state.identity if state else None
    lines.append("Identity")
    if identity is None:
        lines.append("  not known (not enrolled, or service not running)")
    else:
        site = f"{identity.site_nickname or '?'} (AS {identity.site_asn or '?'})"
        router = f"r{identity.router_number}" if identity.router_number is not None else "?"
        lines.append(f"  mesh {identity.mesh_name or '?'}, site {site}, router {router}")
        lines.append(f"  router id {identity.router_id}")

    lines.append("Agent")
    lines.append(f"  service: {_service_line(state, file, now)}")
    lines.append(f"  configuration file: {file_config} (valid)")
    if state is not None:
        if state.config is None:
            lines.append("  controller configuration: none received yet")
        else:
            c = state.config
            lines.append(
                f"  controller configuration: {c.fingerprint[:12]}, received "
                f"{ago(c.received_at, now)} from {c.controller}"
            )
        errors = state.last_pass_errors
        lines.append(f"  last pass: {'no error' if not errors else f'{len(errors)} error(s)'}")
        lines += [f"    {error}" for error in errors]

    lines.append("Controller")
    if state is None:
        lines.append(f"  {', '.join(config.controllers)}")
    else:
        contact = state.controller
        if contact.last_success_at is None:
            lines.append("  never reached since the service started")
        else:
            which = "first" if contact.first_controller else "second"
            lines.append(
                f"  last exchange {ago(contact.last_success_at, now)} with {contact.controller}"
                f" ({which}), through connection {contact.via_connection}"
            )
        if contact.last_error is not None:
            lines.append(f"  last failure {ago(contact.last_error_at, now)}: {contact.last_error}")

    lines.append("Connections")
    if state is None:
        if not config.connections:
            lines.append("  none defined in agent.toml")
        for s in config.connections:
            lines.append(f"  {s.uid}  {s.interface}  vrf {s.vrf}")
    else:
        if not state.connections:
            lines.append("  none defined in agent.toml")
        for conn in state.connections:
            number = f"c{conn.number}" if conn.number is not None else "c?"
            vrf = f"vrf {conn.vrf}" + ("" if conn.vrf_present else " (MISSING)")
            instance = "instance up" if conn.instance_connected else "INSTANCE DOWN"
            lines.append(
                f"  {number}  {conn.name or NONE}  {conn.role or NONE}  {conn.interface}  {vrf}  "
                f"{instance}  ipv4 {conn.public_ipv4 or NONE}  ipv6 {conn.public_ipv6 or NONE}"
            )

    lines.append("Tunnels")
    if state is None or not state.tunnels:
        lines.append("  none" if state is not None else "  unknown (service not running)")
    else:
        for t in state.tunnels:
            if t.pending is not None:
                lines.append(f"  (pending)  {t.remote}  {t.role}: {t.pending}")
                continue
            running = "up" if t.running else "DOWN"
            lines.append(
                f"  {t.name}  {t.remote}  side {t.side}  {t.role}  {running}  "
                f"{t.family_in_use or 'no family'}  handshake {ago(t.last_handshake_at, now)}  "
                f"BGP {t.bgp_state or 'unknown'}"
            )

    if config.internal_link is not None:
        link = config.internal_link
        lines.append("Internal link")
        bgp = state.internal_link.bgp_state if state and state.internal_link else None
        lines.append(f"  {link.interface} -> {link.peer_link_local}  iBGP {bgp or 'unknown'}")
    return lines


def status(
    path: Path | None,
    as_json: bool,
    status_file: Path | None = None,
    now: datetime | None = None,
) -> int:
    config = load_or_exit(path)
    file = status_file or status_path()
    now = now or datetime.now(UTC)
    try:
        state = read_status(file)
    except StatusUnreadable as exc:
        typer.echo(f"status: {exc}", err=True)
        state = None
    found = problems(state, now)

    if as_json:
        document = {
            "config_file": str(config_path(path)),
            "config_valid": True,
            "config": summary(config),
            "status_file": str(file),
            "service": service_state(state, now),
            "problems": found,
            "state": state.model_dump(mode="json") if state else None,
        }
        typer.echo(json.dumps(document, indent=2))
    else:
        for line in render_text(config, config_path(path), state, file, now):
            typer.echo(line)
        typer.echo("Problems")
        typer.echo("  none" if not found else "\n".join(f"  - {p}" for p in found))
    return EXIT_PROBLEM if found else EXIT_OK
