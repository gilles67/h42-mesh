from pathlib import Path

import pytest

from h42mesh.agent.config import ConfigError, config_path, load_config, parse_config
from h42mesh.agent.config.loader import CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH

DATA = Path(__file__).parent / "data"


def test_load_example() -> None:
    config = load_config(DATA / "agent.toml")
    assert len(config.connections) == 2


def test_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)
    assert config_path() == DEFAULT_CONFIG_PATH
    assert DEFAULT_CONFIG_PATH.as_posix() == "/etc/h42-mesh/agent.toml"


def test_path_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "x.toml"))
    assert config_path() == tmp_path / "x.toml"
    assert config_path(Path("/given.toml")) == Path("/given.toml")  # explicit path wins


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configuration file not found"):
        load_config(tmp_path / "absent.toml")


def test_invalid_toml() -> None:
    with pytest.raises(ConfigError, match=r"invalid TOML.*line 2"):
        parse_config('controllers = ["https://vps1.example.org"]\nmesh_number = \n')


def test_messages_name_the_fields() -> None:
    text = """
controllers = ["http://vps1.example.org"]
mesh_numbr = 0

[[connections]]
uid = "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f"
interface = "eth1"
vrf = "wan0"

[[connections]]
uid = "0b9e8d7c-6a5f-4e3d-2c1b-0a9f8e7d6c5b"
interface = "wwan0"
vrf = "default"
ports = { min = 43000, max = 42000 }
"""
    with pytest.raises(ConfigError) as info:
        parse_config(text, "agent.toml")
    message = str(info.value)
    assert message.startswith("agent.toml: invalid configuration")
    assert "controllers[0]: 'http://vps1.example.org': only https:// is accepted" in message
    assert "mesh_numbr: Extra inputs are not permitted" in message
    assert "connections[1].vrf: 'default' is the default VRF" in message
    assert "connections[1].ports: min (43000) is greater than max (42000)" in message


def test_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "agent.toml"
    path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(path)
