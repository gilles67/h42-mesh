"""Reading and validating the local configuration file."""

import os
import tomllib
from pathlib import Path

from pydantic import ValidationError

from h42mesh.agent.config.models import AgentConfig

DEFAULT_CONFIG_PATH = Path("/etc/h42-mesh/agent.toml")
CONFIG_PATH_ENV = "H42_MESH_AGENT_CONFIG"


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


def config_path(path: Path | None = None) -> Path:
    """Given path, else H42_MESH_AGENT_CONFIG, else /etc/h42-mesh/agent.toml."""
    if path is not None:
        return path
    from_env = os.environ.get(CONFIG_PATH_ENV)
    return Path(from_env) if from_env else DEFAULT_CONFIG_PATH


def _location(loc: tuple[int | str, ...]) -> str:
    text = ""
    for part in loc:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or "(file)"


def format_validation_error(error: ValidationError) -> str:
    """One line per problem, naming the field: ``connections[1].vrf: …``."""
    lines = []
    for item in error.errors(include_url=False):
        # Drop the Annotated validator names Pydantic adds to the location.
        loc = tuple(p for p in item["loc"] if not str(p).startswith("function-"))
        message = str(item["msg"]).removeprefix("Value error, ")
        lines.append(f"{_location(loc)}: {message}")
    return "\n".join(lines)


def parse_config(text: str, source: str = "<text>") -> AgentConfig:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: invalid TOML: {exc}") from exc
    try:
        return AgentConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"{source}: invalid configuration\n{format_validation_error(exc)}"
        ) from exc


def load_config(path: Path | None = None) -> AgentConfig:
    resolved = config_path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"{resolved}: configuration file not found") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{resolved}: cannot read the configuration: {exc}") from exc
    return parse_config(text, str(resolved))
