import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from h42mesh.agent.cli import app
from h42mesh.agent.commands.connection import Target, parse_duration, parse_ports, parse_target
from h42mesh.agent.config import PortRange
from h42mesh.agent.config.loader import CONFIG_PATH_ENV

DATA = Path(__file__).parent / "data"
EXAMPLE = str(DATA / "agent.toml")
runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)


@pytest.fixture
def bad_config(tmp_path: Path) -> str:
    path = tmp_path / "agent.toml"
    path.write_text('controllers = ["https://vps1.example.org"]\ntypo = 1\n')
    return str(path)


def invoke(*args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


# --- status (and no command) -------------------------------------------------


def test_status() -> None:
    code, out, _ = invoke("--config", EXAMPLE, "status")
    assert code == 0
    assert "(valid)" in out
    assert "https://vps1.example.org" in out
    assert "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f  interface eth1  vrf wan0" in out
    assert "Internal link: eth2 -> fe80::1a2b:3cff:fe4d:5e6f" in out


def test_no_command_is_status() -> None:
    assert invoke("--config", EXAMPLE) == invoke("--config", EXAMPLE, "status")


def test_status_json() -> None:
    code, out, _ = invoke("--config", EXAMPLE, "status", "--json")
    assert code == 0
    document = json.loads(out)
    assert document["config_valid"] is True
    assert document["config"]["mesh_number"] == 0
    assert [c["vrf"] for c in document["config"]["connections"]] == ["wan0", "wan1"]


def test_config_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, EXAMPLE)
    code, out, _ = invoke("status")
    assert code == 0
    assert EXAMPLE in out


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["status"],
        ["run"],
        ["connection", "list"],
        ["connection", "show", "c0"],
        ["connection", "set", "c0", "--interface", "eth1"],
        ["connection", "remove", "c0"],
    ],
)
def test_invalid_config_exits_2(bad_config: str, command: list[str]) -> None:
    code, _, err = invoke("--config", bad_config, *command)
    assert code == 2
    assert "invalid configuration" in err
    assert "typo: Extra inputs are not permitted" in err


def test_missing_config_exits_2(tmp_path: Path) -> None:
    code, _, err = invoke("--config", str(tmp_path / "absent.toml"), "status")
    assert code == 2
    assert "configuration file not found" in err


# --- not implemented commands ------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        ["connection", "list"],
        ["connection", "show", "c0"],
        ["connection", "show", "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f"],
        [
            "connection",
            "set",
            "c1",
            "--interface",
            "wwan0",
            "--vrf",
            "wan1",
            "--ports",
            "42000-42999",
            "--fallback-delay",
            "30s",
            "--ipv6-retry",
            "10m",
        ],
        ["connection", "set", "c1", "--clear", "ports", "--clear", "force-ipv4"],
        ["connection", "remove", "c1"],
    ],
)
def test_not_implemented_exits_1(command: list[str]) -> None:
    code, _, err = invoke("--config", EXAMPLE, *command)
    assert code == 1
    assert "not implemented yet" in err


def test_run_requires_an_enrollment() -> None:
    code, _, err = invoke("--config", EXAMPLE, "run")
    assert code == 1
    assert "not enrolled" in err


def test_enroll_without_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The configuration file may not exist yet when enrolling."""
    import json

    from agent_harness import FakeController, answer
    from h42mesh.agent.commands import enroll as enroll_module
    from h42mesh.agent.state import StateStore

    router_id = "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f"
    controller = FakeController(
        lambda c: answer(200, json.dumps({"router_id": router_id}).encode())
    )
    monkeypatch.setattr(enroll_module, "default_client", lambda url, config: controller)
    monkeypatch.setattr(enroll_module, "StateStore", lambda _: StateStore(tmp_path / "state"))
    code, out, _ = invoke(
        "--config",
        str(tmp_path / "absent.toml"),
        "enroll",
        "--controller",
        "https://vps1.example.org",
        "--token",
        "abc",
    )
    assert code == 0
    assert f"Enrolled: router {router_id}" in out


def test_enroll_validates_an_existing_config(bad_config: str) -> None:
    code, _, _ = invoke(
        "--config",
        bad_config,
        "enroll",
        "--controller",
        "https://vps1.example.org",
        "--token",
        "abc",
    )
    assert code == 2


@pytest.mark.parametrize("url", ["http://vps1.example.org", "https://vps1.example.org/api"])
def test_enroll_checks_the_controller_url(url: str) -> None:
    code, _, err = invoke("--config", EXAMPLE, "enroll", "--controller", url, "--token", "abc")
    assert code == 2
    assert "--controller" in err


def test_enroll_requires_its_options() -> None:
    assert invoke("--config", EXAMPLE, "enroll", "--token", "abc")[0] == 2


# --- option parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "hint"),
    [
        (["connection", "show", "c10"], "TARGET"),
        (["connection", "show", "eth1"], "TARGET"),
        (["connection", "set", "c0", "--ports", "42000-"], "--ports"),
        (["connection", "set", "c0", "--ports", "2-1"], "--ports"),
        (["connection", "set", "c0", "--fallback-delay", "soon"], "--fallback-delay"),
        (["connection", "set", "c0", "--clear", "interface"], "--clear"),
        (["connection", "set", "c0", "--ports", "1-2", "--clear", "ports"], "--clear"),
    ],
)
def test_usage_errors(args: list[str], hint: str) -> None:
    code, _, err = invoke("--config", EXAMPLE, *args)
    assert code == 2
    assert hint in err


@pytest.mark.parametrize(
    ("text", "seconds"), [("30", 30), ("30s", 30), ("10m", 600), ("1h", 3600), (" 5s ", 5)]
)
def test_parse_duration(text: str, seconds: int) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "10x", "-5", "1.5m", "m"])
def test_parse_duration_errors(text: str) -> None:
    with pytest.raises(ValueError, match="not a duration"):
        parse_duration(text)


def test_parse_ports() -> None:
    assert parse_ports("42000-42999") == PortRange(min=42000, max=42999)
    assert parse_ports("42000") == PortRange(min=42000, max=42000)


def test_parse_target() -> None:
    assert parse_target("c3") == Target(number=3)
    uid = "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f"
    assert str(parse_target(uid).uid) == uid


def test_version() -> None:
    code, out, _ = invoke("--version")
    assert code == 0
    assert out.strip()
