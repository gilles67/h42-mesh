"""Enrollment: key generated, sent, stored only on success."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from agent_harness import FakeController, answer
from h42mesh.agent import system
from h42mesh.agent.commands import enroll as enroll_module
from h42mesh.agent.commands.enroll import enroll
from h42mesh.agent.signing import key_from_pem, public_key_b64
from h42mesh.agent.state import StateStore

ROUTER = uuid.UUID(int=42)
CONTROLLER = "https://vps1.example.org"


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "agent.toml"
    path.write_text(f'controllers = ["{CONTROLLER}"]\n')
    # state_dir is a POSIX path in the configuration: store in tmp_path instead.
    monkeypatch.setattr(enroll_module, "StateStore", lambda _: StateStore(tmp_path / "state"))
    return path


def accepting(call: dict[str, Any]) -> Any:
    return answer(200, json.dumps({"router_id": str(ROUTER)}).encode())


def run(config_file: Path | None, controller: FakeController, **kwargs: Any) -> int:
    return enroll(
        config_file,
        CONTROLLER,
        "the-token",
        client_factory=lambda url, config: controller,
        **kwargs,
    )


def store_of(config_file: Path) -> StateStore:
    return StateStore(config_file.parent / "state")


def test_successful_enrollment(config_file: Path) -> None:
    controller = FakeController(accepting)
    assert run(config_file, controller) == 0

    (call,) = controller.calls
    assert (call["method"], call["path"]) == ("POST", "/api/v1/agent/enroll")
    body = json.loads(call["body"])
    assert body["token"] == "the-token"

    store = store_of(config_file)
    identity = store.load_identity()
    pem = store.load_agent_key()
    assert identity is not None and pem is not None
    assert (identity.router_id, identity.controller) == (ROUTER, CONTROLLER)
    assert public_key_b64(key_from_pem(pem)) == body["signing_public_key"]


def test_refused_enrollment_writes_nothing(config_file: Path) -> None:
    controller = FakeController(
        lambda c: answer(401, b'{"code": "invalid_enrollment_token", "message": "used"}')
    )
    assert run(config_file, controller) == 1
    assert not (config_file.parent / "state").exists()


def test_failure_keeps_the_previous_key(config_file: Path) -> None:
    store = store_of(config_file)
    store.save_agent_key(b"previous key")
    controller = FakeController(accepting, unreachable=True)
    assert run(config_file, controller) == 1
    assert store.load_agent_key() == b"previous key"


def test_new_key_at_each_enrollment(config_file: Path) -> None:
    run(config_file, FakeController(accepting))
    first = store_of(config_file).load_agent_key()
    run(config_file, FakeController(accepting))
    assert store_of(config_file).load_agent_key() != first


def test_controller_must_be_in_the_configuration(config_file: Path) -> None:
    controller = FakeController(accepting)
    code = enroll(
        config_file,
        "https://other.example.org",
        "t",
        client_factory=lambda url, config: controller,
    )
    assert code == 2
    assert controller.calls == []


def test_without_configuration_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[Path] = []

    def store(path: Path) -> StateStore:
        used.append(path)
        return StateStore(tmp_path / "default-state")

    monkeypatch.setattr(enroll_module, "StateStore", store)
    assert run(tmp_path / "absent.toml", FakeController(accepting)) == 0
    assert used == [Path("/var/lib/h42-mesh")]  # the default state_dir
    assert StateStore(tmp_path / "default-state").load_identity() is not None


def test_unexpected_answer(config_file: Path) -> None:
    assert run(config_file, FakeController(lambda c: answer(200, b"[]"))) == 1


# --- --vrf: the command runs itself again inside the VRF --------------------


def test_reexecution_inside_the_vrf(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(system, "vrf_exists", lambda name: True)
    monkeypatch.setattr(system, "in_vrf", lambda: None)

    def run_in_vrf(vrf: str, argv: list[str]) -> int:
        runs.append((vrf, argv))
        return 0

    monkeypatch.setattr(system, "run_in_vrf", run_in_vrf)
    controller = FakeController(accepting)
    assert run(config_file, controller, vrf="wan0", reexec_argv=["agent", "enroll"]) == 0
    assert runs == [("wan0", ["agent", "enroll"])]
    assert controller.calls == []  # done by the re-executed command


def test_inside_the_vrf_already(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "in_vrf", lambda: "wan0")
    controller = FakeController(accepting)
    assert run(config_file, controller, vrf="wan0") == 0
    assert len(controller.calls) == 1


def test_missing_vrf(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "vrf_exists", lambda name: False)
    monkeypatch.setattr(system, "in_vrf", lambda: None)
    assert run(config_file, FakeController(accepting), vrf="wan9") == 2
