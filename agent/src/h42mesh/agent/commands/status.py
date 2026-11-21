"""h42-mesh-agent status: local state of the agent (for now: the configuration)."""

import json
from pathlib import Path

import typer

from h42mesh.agent.commands import EXIT_OK, load_or_exit
from h42mesh.agent.config import AgentConfig, config_path


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


def status(path: Path | None, as_json: bool) -> int:
    config = load_or_exit(path)
    if as_json:
        document = {
            "config_file": str(config_path(path)),
            "config_valid": True,
            "config": summary(config),
            "agent": "not_implemented",
        }
        typer.echo(json.dumps(document, indent=2))
        return EXIT_OK

    typer.echo(f"Configuration: {config_path(path)} (valid)")
    typer.echo(f"  Controllers: {', '.join(config.controllers)}")
    typer.echo(f"  Mesh number: {config.mesh_number}")
    if config.internal_link is not None:
        link = config.internal_link
        typer.echo(f"  Internal link: {link.interface} -> {link.peer_link_local}")
    if config.connections:
        typer.echo("  Connections:")
        for c in config.connections:
            typer.echo(f"    {c.uid}  interface {c.interface}  vrf {c.vrf}")
    else:
        typer.echo("  Connections: none defined")
    typer.echo("Agent state: not implemented yet")
    return EXIT_OK
