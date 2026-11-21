"""Command line of h42-mesh-agent (Typer).

Without a command, the agent behaves as ``status``. Exit codes: 0 success,
1 not implemented (or failure), 2 invalid configuration or usage error.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from h42mesh.agent import __version__
from h42mesh.agent.commands import connection as connection_cmd
from h42mesh.agent.commands.enroll import enroll as enroll_cmd
from h42mesh.agent.commands.run import run as run_cmd
from h42mesh.agent.commands.status import status as status_cmd
from h42mesh.agent.config.loader import CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH
from h42mesh.agent.config.models import controller_url

app = typer.Typer(
    name="h42-mesh-agent",
    help="h42-mesh agent: tunnels and routing of a router.",
    add_completion=False,
    no_args_is_help=False,
)
connection_app = typer.Typer(help="Local settings of the internet connections.")
app.add_typer(connection_app, name="connection")


@dataclass
class State:
    config: Path | None


def _state(ctx: typer.Context) -> State:
    """Set by the main callback, which always runs before a command."""
    state = ctx.find_object(State)
    return state if state is not None else State(config=None)


def _exit(code: int) -> None:
    raise typer.Exit(code)


def _parse[T](parser: Callable[[str], T], value: str, name: str) -> T:
    """Turn a ValueError of a parser into a usage error naming the option."""
    try:
        return parser(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint=name) from exc


ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        envvar=CONFIG_PATH_ENV,
        help=f"Configuration file (default: {DEFAULT_CONFIG_PATH.as_posix()}).",
        show_default=False,
    ),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    config: ConfigOption = None,
    version: Annotated[bool, typer.Option("--version", help="Show the version.")] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit(0)
    ctx.obj = State(config=config)
    if ctx.invoked_subcommand is None:
        _exit(status_cmd(config, as_json=False))


@app.command()
def status(ctx: typer.Context, as_json: JsonOption = False) -> None:
    """Local state of the agent (also shown without a command)."""
    _exit(status_cmd(_state(ctx).config, as_json))


@app.command()
def run(ctx: typer.Context) -> None:
    """Main loop (launched by h42-mesh-agent.service)."""
    _exit(run_cmd(_state(ctx).config))


@app.command()
def enroll(
    ctx: typer.Context,
    controller: Annotated[str, typer.Option(help="Controller URL (https://name).")],
    token: Annotated[str, typer.Option(help="Single-use enrollment token.")],
) -> None:
    """Generate the signing key and enroll the router with a token."""
    url = _parse(controller_url, controller, "--controller")
    _exit(enroll_cmd(_state(ctx).config, url, token))


TargetArgument = Annotated[str, typer.Argument(help="c0…c9, or the connection UID.")]


@connection_app.command("list")
def connection_list(ctx: typer.Context) -> None:
    """Connections of the router and their local settings."""
    _exit(connection_cmd.list_connections(_state(ctx).config))


@connection_app.command("show")
def connection_show(ctx: typer.Context, target: TargetArgument) -> None:
    """Local settings of one connection."""
    parsed = _parse(connection_cmd.parse_target, target, "TARGET")
    _exit(connection_cmd.show_connection(_state(ctx).config, parsed))


@connection_app.command("set")
def connection_set(
    ctx: typer.Context,
    target: TargetArgument,
    interface: Annotated[str | None, typer.Option(help="Physical interface.")] = None,
    vrf: Annotated[str | None, typer.Option(help="VRF of the connection.")] = None,
    ports: Annotated[str | None, typer.Option(help="Port range, e.g. 42000-42999.")] = None,
    force_ipv4: Annotated[str | None, typer.Option(help="Forced public IPv4.")] = None,
    force_ipv6: Annotated[str | None, typer.Option(help="Forced public IPv6.")] = None,
    fallback_delay: Annotated[
        str | None, typer.Option(help="IPv6 -> IPv4 fallback delay, e.g. 30s.")
    ] = None,
    ipv6_retry: Annotated[str | None, typer.Option(help="IPv6 retry interval, e.g. 10m.")] = None,
    clear: Annotated[
        list[str] | None,
        typer.Option(
            help="Remove a setting: ports, force-ipv4, force-ipv6, fallback-delay, ipv6-retry."
        ),
    ] = None,
) -> None:
    """Create or modify the local settings of a connection."""
    clearable = {"ports", "force-ipv4", "force-ipv6", "fallback-delay", "ipv6-retry"}
    cleared = frozenset(clear or [])
    unknown = cleared - clearable
    if unknown:
        raise typer.BadParameter(f"cannot clear {', '.join(sorted(unknown))}", param_hint="--clear")
    given = {
        "ports": ports,
        "force-ipv4": force_ipv4,
        "force-ipv6": force_ipv6,
        "fallback-delay": fallback_delay,
        "ipv6-retry": ipv6_retry,
    }
    both = sorted(name for name in cleared if given[name] is not None)
    if both:
        raise typer.BadParameter(f"--{both[0]} given and cleared", param_hint="--clear")
    options = connection_cmd.SetOptions(
        interface=interface,
        vrf=vrf,
        ports=_parse(connection_cmd.parse_ports, ports, "--ports") if ports else None,
        force_ipv4=force_ipv4,
        force_ipv6=force_ipv6,
        fallback_delay=(
            _parse(connection_cmd.parse_duration, fallback_delay, "--fallback-delay")
            if fallback_delay
            else None
        ),
        ipv6_retry=(
            _parse(connection_cmd.parse_duration, ipv6_retry, "--ipv6-retry")
            if ipv6_retry
            else None
        ),
        clear=cleared,
    )
    parsed = _parse(connection_cmd.parse_target, target, "TARGET")
    _exit(connection_cmd.set_connection(_state(ctx).config, parsed, options))


@connection_app.command("remove")
def connection_remove(ctx: typer.Context, target: TargetArgument) -> None:
    """Remove the local settings of a connection."""
    parsed = _parse(connection_cmd.parse_target, target, "TARGET")
    _exit(connection_cmd.remove_connection(_state(ctx).config, parsed))


def main() -> None:
    app()
