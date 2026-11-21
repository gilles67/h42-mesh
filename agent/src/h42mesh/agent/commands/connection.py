"""h42-mesh-agent connection list/show/set/remove: local connection settings.

- a connection is designated by its number (c0…c9), found in the
  configuration received from the controller (state_dir), or by its UID;
  the UID is what agent.toml holds;
- before writing: the new file is validated as a whole (Pydantic), then
  checked against the machine (interface, VRF, interface attached to the VRF)
  and the controller (port range of the connection within the router's);
- agent.toml is modified with tomlkit: comments and layout are kept; it is
  written atomically, with its previous permissions;
- the running service is asked to reload it (SIGHUP); it also notices the
  change by itself within a few seconds.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import tomlkit
import typer
from tomlkit.items import AoT, Table

from h42mesh.agent import system
from h42mesh.agent.commands import EXIT_INVALID_CONFIG, EXIT_OK, load_or_exit
from h42mesh.agent.config import (
    AgentConfig,
    ConfigError,
    ConnectionSettings,
    PortRange,
    config_path,
    parse_config,
)
from h42mesh.agent.messages import RouterConfig
from h42mesh.agent.state import StateError, StateStore, atomic_write
from h42mesh.agent.status_file import StatusUnreadable, is_stale, read_status
from h42mesh.agent.tunnels.plan import connection_ports

EXIT_FAILED = 1

_DURATION = re.compile(r"(\d+)([smh]?)")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}
_NUMBER = re.compile(r"c([0-9])")
CLEARABLE = {
    "ports": "ports",
    "force-ipv4": "force_ipv4",
    "force-ipv6": "force_ipv6",
    "fallback-delay": "fallback_delay",
    "ipv6-retry": "ipv6_retry",
}


def parse_duration(text: str) -> int:
    """Seconds from ``30``, ``30s``, ``10m`` or ``1h``."""
    match = _DURATION.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"{text!r} is not a duration (examples: 30s, 10m, 1h)")
    return int(match.group(1)) * _UNITS[match.group(2)]


def parse_ports(text: str) -> PortRange:
    """``42000-42999`` (or a single port ``42000``)."""
    low, sep, high = text.strip().partition("-")
    try:
        return PortRange(min=int(low), max=int(high) if sep else int(low))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a port range (example: 42000-42999)") from exc


@dataclass(frozen=True)
class Target:
    """A connection designated by its number (c0…c9) or directly by its UID."""

    number: int | None = None
    uid: UUID | None = None


def parse_target(text: str) -> Target:
    match = _NUMBER.fullmatch(text.strip())
    if match is not None:
        return Target(number=int(match.group(1)))
    try:
        return Target(uid=UUID(text.strip()))
    except ValueError as exc:
        raise ValueError(f"{text!r} is neither c0…c9 nor a connection UID") from exc


@dataclass(frozen=True)
class SetOptions:
    interface: str | None = None
    vrf: str | None = None
    ports: PortRange | None = None
    force_ipv4: str | None = None
    force_ipv6: str | None = None
    fallback_delay: int | None = None
    ipv6_retry: int | None = None
    clear: frozenset[str] = frozenset()


@dataclass
class Machine:
    """What is checked on the machine, and how the service is told (replaced in tests)."""

    interface_exists: Callable[[str], bool] = system.interface_exists
    vrf_exists: Callable[[str], bool] = system.vrf_exists
    interface_vrf: Callable[[str], str | None] = system.interface_master
    notify: Callable[[], str] = field(default=lambda: notify_running_service())
    store: Callable[[AgentConfig], StateStore] = field(
        default=lambda config: StateStore(Path(str(config.state_dir)))
    )


def notify_running_service() -> str:
    try:
        state = read_status()
    except StatusUnreadable:
        state = None
    running = state is not None and not is_stale(state, datetime.now(UTC))
    if running and state is not None and system.notify_service(state.pid):
        return "the running service applies it now"
    return "the service uses it when it (re)starts, or within a few seconds if it is running"


class CommandError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.code = code


# --- helpers -----------------------------------------------------------------


def router_config(config: AgentConfig, machine: Machine) -> RouterConfig | None:
    try:
        stored = machine.store(config).load_config()
    except (StateError, OSError) as exc:
        typer.echo(f"warning: {exc}", err=True)
        return None
    return stored.config if stored is not None else None


def resolve(target: Target, known: RouterConfig | None) -> UUID:
    if target.uid is not None:
        return target.uid
    if known is None:
        raise CommandError(
            f"c{target.number}: the configuration of the controller is not known yet "
            "(not enrolled, or never reached): give the UID of the connection"
        )
    for connection in known.connections:
        if connection.number == target.number:
            return connection.id
    raise CommandError(f"c{target.number}: no such connection on this router")


def _label(uid: UUID, known: RouterConfig | None) -> str:
    for connection in known.connections if known else []:
        if connection.id == uid:
            return f"c{connection.number} ({connection.name})"
    return str(uid)


def _settings_lines(settings: ConnectionSettings) -> list[str]:
    ports = f"{settings.ports.min}-{settings.ports.max}" if settings.ports else "router range"
    return [
        f"  uid             {settings.uid}",
        f"  interface       {settings.interface}",
        f"  vrf             {settings.vrf}",
        f"  ports           {ports}",
        f"  force-ipv4      {settings.force_ipv4 or '-'}",
        f"  force-ipv6      {settings.force_ipv6 or '-'}",
        f"  fallback-delay  {settings.fallback_delay} s",
        f"  ipv6-retry      {settings.ipv6_retry} s",
    ]


def check_machine(
    settings: ConnectionSettings, config: AgentConfig, known: RouterConfig | None, machine: Machine
) -> list[str]:
    """Problems that Pydantic cannot see: they depend on the machine and the controller."""
    found = []
    if not machine.interface_exists(settings.interface):
        found.append(f"interface {settings.interface} does not exist")
    if not machine.vrf_exists(settings.vrf):
        found.append(f"VRF {settings.vrf} does not exist (created by the system configuration)")
    elif machine.interface_exists(settings.interface):
        attached = machine.interface_vrf(settings.interface)
        if attached != settings.vrf:
            found.append(
                f"interface {settings.interface} is not attached to VRF {settings.vrf} "
                f"(attached to {attached or 'no VRF'})"
            )
    if settings.ports is not None and known is not None:
        usable = connection_ports(config.mesh_number, known.router.number, settings)
        if len(usable) == 0:
            found.append(
                f"ports {settings.ports.min}-{settings.ports.max} are outside the range of the "
                f"router (r{known.router.number})"
            )
    return found


# --- the file ----------------------------------------------------------------


def _connections(document: tomlkit.TOMLDocument, create: bool) -> AoT | None:
    found = document.get("connections")
    if found is None and create:
        found = tomlkit.aot()
        document.append("connections", found)
    if found is not None and not isinstance(found, AoT):
        raise CommandError("agent.toml: connections is not an array of tables", EXIT_INVALID_CONFIG)
    return found


def _find(tables: AoT | None, uid: UUID) -> tuple[int, Table] | None:
    for index, table in enumerate(tables or []):
        try:
            if UUID(str(table.get("uid"))) == uid:
                return index, table
        except ValueError:
            continue
    return None


def _edit(table: Table, options: SetOptions) -> None:
    values: dict[str, Any] = {
        "interface": options.interface,
        "vrf": options.vrf,
        "force_ipv4": options.force_ipv4,
        "force_ipv6": options.force_ipv6,
        "fallback_delay": options.fallback_delay,
        "ipv6_retry": options.ipv6_retry,
    }
    for key, value in values.items():
        if value is not None:
            table[key] = value
    if options.ports is not None:
        ports = tomlkit.inline_table()
        ports.update({"min": options.ports.min, "max": options.ports.max})
        table["ports"] = ports
    for name in options.clear:
        key = CLEARABLE[name]
        if key in table:
            del table[key]


def _write(path: Path, text: str) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    atomic_write(path, text.encode("utf-8"), mode)


def _validated(text: str, source: Path) -> AgentConfig:
    try:
        return parse_config(text, str(source))
    except ConfigError as exc:
        raise CommandError(f"{exc}\nagent.toml not modified", EXIT_INVALID_CONFIG) from exc


# --- commands ----------------------------------------------------------------


def _run(action: Callable[[], int]) -> int:
    try:
        return action()
    except CommandError as exc:
        typer.echo(str(exc), err=True)
        return exc.code


def list_connections(path: Path | None, machine: Machine | None = None) -> int:
    machine = machine or Machine()
    config = load_or_exit(path)
    known = router_config(config, machine)
    local = {c.uid: c for c in config.connections}
    if known is None:
        typer.echo("Configuration of the controller not known yet: local settings only.")
    for connection in sorted(known.connections if known else [], key=lambda c: c.number):
        settings = local.pop(connection.id, None)
        where = (
            f"{settings.interface}  vrf {settings.vrf}"
            if settings
            else "NOT DEFINED in agent.toml (h42-mesh-agent connection set "
            f"c{connection.number} --interface … --vrf …)"
        )
        typer.echo(f"c{connection.number}  {connection.name}  {connection.role}  {where}")
    for settings in local.values():
        suffix = "  (unknown to the controller)" if known is not None else ""
        typer.echo(f"{settings.uid}  {settings.interface}  vrf {settings.vrf}{suffix}")
    if known is None and not config.connections:
        typer.echo("No connection defined.")
    return EXIT_OK


def show_connection(path: Path | None, target: Target, machine: Machine | None = None) -> int:
    machine = machine or Machine()

    def action() -> int:
        config = load_or_exit(path)
        known = router_config(config, machine)
        uid = resolve(target, known)
        settings = next((c for c in config.connections if c.uid == uid), None)
        if settings is None:
            raise CommandError(f"{_label(uid, known)}: not defined in agent.toml")
        typer.echo(f"Connection {_label(uid, known)}")
        for line in _settings_lines(settings):
            typer.echo(line)
        for problem in check_machine(settings, config, known, machine):
            typer.echo(f"  warning: {problem}")
        return EXIT_OK

    return _run(action)


def set_connection(
    path: Path | None, target: Target, options: SetOptions, machine: Machine | None = None
) -> int:
    machine = machine or Machine()

    def action() -> int:
        config = load_or_exit(path)
        known = router_config(config, machine)
        uid = resolve(target, known)
        file = config_path(path)
        document = tomlkit.parse(file.read_text(encoding="utf-8"))
        tables = _connections(document, create=True)
        assert tables is not None  # noqa: S101 (created above)
        found = _find(tables, uid)
        if found is None:
            if options.interface is None or options.vrf is None:
                raise CommandError(
                    f"{_label(uid, known)}: new connection: --interface and --vrf are required"
                    "\nagent.toml not modified",
                    EXIT_INVALID_CONFIG,
                )
            table = tomlkit.table()
            table["uid"] = str(uid)
            tables.append(table)
            table = tables[-1]
        else:
            table = found[1]
        _edit(table, options)
        text = tomlkit.dumps(document)
        new = _validated(text, file)
        settings = next(c for c in new.connections if c.uid == uid)
        problems = check_machine(settings, new, known, machine)
        if problems:
            raise CommandError(
                "\n".join(f"{_label(uid, known)}: {p}" for p in problems)
                + "\nagent.toml not modified"
            )
        _write(file, text)
        typer.echo(f"{_label(uid, known)}: saved in {file}; {machine.notify()}")
        return EXIT_OK

    return _run(action)


def remove_connection(path: Path | None, target: Target, machine: Machine | None = None) -> int:
    machine = machine or Machine()

    def action() -> int:
        config = load_or_exit(path)
        known = router_config(config, machine)
        uid = resolve(target, known)
        file = config_path(path)
        document = tomlkit.parse(file.read_text(encoding="utf-8"))
        tables = _connections(document, create=False)
        found = _find(tables, uid)
        if tables is None or found is None:
            raise CommandError(f"{_label(uid, known)}: not defined in agent.toml")
        del tables[found[0]]
        text = tomlkit.dumps(document)
        _validated(text, file)
        _write(file, text)
        typer.echo(f"{_label(uid, known)}: removed from {file}; {machine.notify()}")
        return EXIT_OK

    return _run(action)
