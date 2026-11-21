"""connection list/show/set/remove, with a fake machine and a stored configuration."""

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from h42mesh.agent.commands.connection import (
    Machine,
    SetOptions,
    Target,
    list_connections,
    remove_connection,
    set_connection,
    show_connection,
)
from h42mesh.agent.config import PortRange, load_config
from h42mesh.agent.messages import RouterConfig
from h42mesh.agent.state import StateStore, StoredConfig
from test_messages import config_document

EXAMPLE = Path(__file__).parent / "data" / "agent.toml"
C0 = uuid.UUID("6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f")
C1 = uuid.UUID("0b9e8d7c-6a5f-4e3d-2c1b-0a9f8e7d6c5b")
C2 = uuid.UUID(int=2)


def connection(uid: uuid.UUID, number: int, name: str, role: str) -> dict[str, Any]:
    return {
        "id": str(uid),
        "number": number,
        "name": name,
        "role": role,
        "priority": None,
        "direct": "none",
        "public_ipv4": None,
        "public_ipv6": None,
    }


class FakeMachine(Machine):
    def __init__(self, store: StateStore) -> None:
        self.interfaces = {"eth1": "wan0", "wwan0": "wan1", "eth3": "wan2", "eth4": None}
        self.vrfs = {"wan0", "wan1", "wan2"}
        self.notified = 0
        super().__init__(
            interface_exists=lambda name: name in self.interfaces,
            vrf_exists=lambda name: name in self.vrfs,
            interface_vrf=lambda name: self.interfaces.get(name),
            notify=self._notify,
            store=lambda config: store,
        )

    def _notify(self) -> str:
        self.notified += 1
        return "notified"


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "agent.toml"
    shutil.copy(EXAMPLE, path)
    return path


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "state")
    document = config_document(
        connections=[
            connection(C0, 0, "fiber", "active"),
            connection(C1, 1, "lte", "backup"),
            connection(C2, 2, "starlink", "backup"),
        ],
        tunnels=[],
    )
    store.save_config(
        StoredConfig(
            fingerprint="f" * 64,
            received_at=datetime(2026, 1, 1, tzinfo=UTC),
            controller="https://vps1.example.org",
            config=RouterConfig.model_validate(document),
        )
    )
    return store


@pytest.fixture
def machine(store: StateStore) -> FakeMachine:
    return FakeMachine(store)


# --- list and show -----------------------------------------------------------


def test_list(config_file: Path, machine: FakeMachine, capsys: pytest.CaptureFixture[str]) -> None:
    assert list_connections(config_file, machine) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "c0  fiber  active  eth1  vrf wan0"
    assert lines[1] == "c1  lte  backup  wwan0  vrf wan1"
    assert lines[2].startswith("c2  starlink  backup  NOT DEFINED in agent.toml")


def test_show_by_number_and_by_uid(
    config_file: Path, machine: FakeMachine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert show_connection(config_file, Target(number=1), machine) == 0
    by_number = capsys.readouterr().out
    assert by_number.startswith("Connection c1 (lte)")
    assert "fallback-delay  30 s" in by_number
    assert show_connection(config_file, Target(uid=C1), machine) == 0
    assert capsys.readouterr().out == by_number


def test_show_undefined_connection(
    config_file: Path, machine: FakeMachine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert show_connection(config_file, Target(number=2), machine) == 1
    assert "not defined in agent.toml" in capsys.readouterr().err
    assert show_connection(config_file, Target(number=7), machine) == 1
    assert "no such connection" in capsys.readouterr().err


# --- set ---------------------------------------------------------------------


def test_set_keeps_comments_and_layout(config_file: Path, machine: FakeMachine) -> None:
    before = config_file.read_text(encoding="utf-8")
    options = SetOptions(ports=PortRange(min=42100, max=42199), fallback_delay=45)
    assert set_connection(config_file, Target(number=0), options, machine) == 0
    after = config_file.read_text(encoding="utf-8")
    assert "# /etc/h42-mesh/agent.toml (example of docs/specs/agent.md)" in after
    assert "# c0, fibre" in after and "# secondes" in after
    assert "ports = {min = 42100, max = 42199}" in after
    # Only the edited table changed.
    assert after.replace("fallback_delay = 45\nports = {min = 42100, max = 42199}\n", "") == before
    settings = load_config(config_file).connections[0]
    assert (settings.ports, settings.fallback_delay) == (PortRange(min=42100, max=42199), 45)
    assert machine.notified == 1


def test_set_creates_a_connection(config_file: Path, machine: FakeMachine) -> None:
    options = SetOptions(interface="eth3", vrf="wan2", force_ipv4="93.184.216.34")
    assert set_connection(config_file, Target(number=2), options, machine) == 0
    settings = load_config(config_file).connections[2]
    assert (settings.uid, settings.interface, settings.vrf) == (C2, "eth3", "wan2")
    assert str(settings.force_ipv4) == "93.184.216.34"


def test_set_clears_settings(config_file: Path, machine: FakeMachine) -> None:
    options = SetOptions(clear=frozenset({"fallback-delay", "ipv6-retry"}))
    assert set_connection(config_file, Target(number=1), options, machine) == 0
    text = config_file.read_text(encoding="utf-8")
    assert "fallback_delay" not in text and "ipv6_retry" not in text
    assert load_config(config_file).connections[1].fallback_delay == 30  # default


@pytest.mark.parametrize(
    ("target", "options", "message"),
    [
        (Target(number=2), SetOptions(interface="eth3"), "--interface and --vrf are required"),
        (Target(number=2), SetOptions(interface="eth9", vrf="wan2"),
         "interface eth9 does not exist"),
        (Target(number=2), SetOptions(interface="eth3", vrf="wan9"), "VRF wan9 does not exist"),
        (Target(number=2), SetOptions(interface="eth4", vrf="wan2"),
         "eth4 is not attached to VRF wan2 (attached to no VRF)"),
        (Target(number=0), SetOptions(ports=PortRange(min=50000, max=50100)),
         "outside the range of the router (r0)"),
        (Target(number=0), SetOptions(interface="wwan0", vrf="wan1"), "duplicate value wwan0"),
        (Target(number=0), SetOptions(force_ipv4="10.0.0.1"), "not a public IPv4"),
        (Target(number=0), SetOptions(fallback_delay=1), "greater than or equal to 5"),
    ],
)  # fmt: skip
def test_set_refused_leaves_the_file(
    config_file: Path,
    machine: FakeMachine,
    capsys: pytest.CaptureFixture[str],
    target: Target,
    options: SetOptions,
    message: str,
) -> None:
    before = config_file.read_text(encoding="utf-8")
    assert set_connection(config_file, target, options, machine) != 0
    err = capsys.readouterr().err
    assert message in err and "agent.toml not modified" in err
    assert config_file.read_text(encoding="utf-8") == before
    assert machine.notified == 0


def test_set_by_uid_without_controller_configuration(config_file: Path, tmp_path: Path) -> None:
    machine = FakeMachine(StateStore(tmp_path / "empty"))
    assert (
        set_connection(config_file, Target(number=0), SetOptions(fallback_delay=60), machine) == 1
    )
    assert set_connection(config_file, Target(uid=C0), SetOptions(fallback_delay=60), machine) == 0
    assert load_config(config_file).connections[0].fallback_delay == 60


# --- remove ------------------------------------------------------------------


def test_remove(config_file: Path, machine: FakeMachine) -> None:
    assert remove_connection(config_file, Target(number=1), machine) == 0
    config = load_config(config_file)
    assert [c.uid for c in config.connections] == [C0]
    assert "# c0, fibre" in config_file.read_text(encoding="utf-8")
    assert machine.notified == 1


def test_remove_undefined(
    config_file: Path, machine: FakeMachine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert remove_connection(config_file, Target(number=2), machine) == 1
    assert "not defined in agent.toml" in capsys.readouterr().err
