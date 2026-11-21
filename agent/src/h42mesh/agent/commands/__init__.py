"""Commands of h42-mesh-agent. For now they only validate the configuration."""

from pathlib import Path

import typer

from h42mesh.agent.config import AgentConfig, ConfigError, config_path, load_config

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 1
EXIT_INVALID_CONFIG = 2


def load_or_exit(path: Path | None) -> AgentConfig:
    """The validated configuration; on error, the message and exit code 2."""
    try:
        return load_config(path)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INVALID_CONFIG) from exc


def load_if_present(path: Path | None) -> AgentConfig | None:
    """Like load_or_exit, but a missing file is not an error (enrollment)."""
    if not config_path(path).exists():
        return None
    return load_or_exit(path)


def not_implemented(what: str) -> int:
    typer.echo(f"{what}: not implemented yet", err=True)
    return EXIT_NOT_IMPLEMENTED
