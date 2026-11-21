"""agent.toml taken into account without restart: instances follow, watcher reloads."""

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from h42mesh.agent.config import AgentConfig, ConnectionSettings, load_config
from h42mesh.agent.reload import ConfigWatcher, Instances

A, B = uuid.UUID(int=1), uuid.UUID(int=2)
EXAMPLE = Path(__file__).parent / "data" / "agent.toml"


class FakeSupervisor:
    def __init__(self, settings: ConnectionSettings, log: list[tuple[str, uuid.UUID]]) -> None:
        self.settings = settings
        self.log = log
        self.stopped = asyncio.Event()

    async def run(self) -> None:
        self.log.append(("start", self.settings.uid))
        await self.stopped.wait()

    def stop(self) -> None:
        self.log.append(("stop", self.settings.uid))
        self.stopped.set()


def config(*connections: ConnectionSettings, **overrides: object) -> AgentConfig:
    values: dict[str, object] = {
        "controllers": ["https://vps1.test"],
        "connections": list(connections),
    }
    values.update(overrides)
    return AgentConfig.model_validate(values)


def conn(uid: uuid.UUID, vrf: str, **overrides: object) -> ConnectionSettings:
    return ConnectionSettings.model_validate(
        {"uid": uid, "interface": f"if{vrf}", "vrf": vrf, **overrides}
    )


@pytest.fixture
def log() -> list[tuple[str, uuid.UUID]]:
    return []


@pytest.fixture
def instances(log: list[tuple[str, uuid.UUID]]) -> Instances:
    return Instances(lambda settings: FakeSupervisor(settings, log))


async def settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_connections_added_and_removed(
    instances: Instances, log: list[tuple[str, uuid.UUID]]
) -> None:
    first = config(conn(A, "wan0"))
    await instances.follow(None, first)
    await settle()
    second = config(conn(B, "wan1"))
    await instances.follow(first, second)
    await settle()
    assert log == [("start", A), ("stop", A), ("start", B)]
    await instances.stop_all()


async def test_vrf_change_restarts_the_instance(
    instances: Instances, log: list[tuple[str, uuid.UUID]]
) -> None:
    first = config(conn(A, "wan0"), conn(B, "wan1"))
    await instances.follow(None, first)
    await settle()
    log.clear()
    await instances.follow(first, config(conn(A, "wan2"), conn(B, "wan1")))
    await settle()
    assert log == [("stop", A), ("start", A)]
    await instances.stop_all()


async def test_other_settings_do_not_restart(
    instances: Instances, log: list[tuple[str, uuid.UUID]]
) -> None:
    first = config(conn(A, "wan0"))
    await instances.follow(None, first)
    await settle()
    log.clear()
    await instances.follow(first, config(conn(A, "wan0", fallback_delay=60)))
    assert log == []
    assert instances.running[A][0].settings.fallback_delay == 60
    await instances.stop_all()


async def test_controllers_change_restarts_every_instance(
    instances: Instances, log: list[tuple[str, uuid.UUID]]
) -> None:
    first = config(conn(A, "wan0"), conn(B, "wan1"))
    await instances.follow(None, first)
    await settle()
    log.clear()
    await instances.follow(
        first, config(conn(A, "wan0"), conn(B, "wan1"), controllers=["https://vps2.test"])
    )
    await settle()
    assert sorted(log) == [("start", A), ("start", B), ("stop", A), ("stop", B)]
    await instances.stop_all()


# --- watcher -----------------------------------------------------------------


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "agent.toml"
    shutil.copy(EXAMPLE, path)
    return path


async def test_watcher_applies_a_valid_change(config_file: Path) -> None:
    applied: list[AgentConfig] = []

    async def on_change(new: AgentConfig) -> None:
        applied.append(new)

    watcher = ConfigWatcher(config_file, load_config(config_file), on_change)
    assert await watcher.check() is False  # unchanged
    config_file.write_text(config_file.read_text().replace("mesh_number = 0", "mesh_number = 1"))
    assert await watcher.check(forced=True) is True
    assert applied[0].mesh_number == 1
    assert watcher.current.mesh_number == 1


async def test_watcher_refuses_an_invalid_file(
    config_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def on_change(new: AgentConfig) -> None:
        raise AssertionError("not applied")

    watcher = ConfigWatcher(config_file, load_config(config_file), on_change)
    config_file.write_text(config_file.read_text() + "typo = 1\n")
    assert await watcher.check(forced=True) is False
    assert "current settings stay" in caplog.text


async def test_watcher_refuses_a_new_state_dir(config_file: Path) -> None:
    async def on_change(new: AgentConfig) -> None:
        raise AssertionError("not applied")

    watcher = ConfigWatcher(config_file, load_config(config_file), on_change)
    config_file.write_text('state_dir = "/srv/h42"\n' + config_file.read_text())
    assert await watcher.check(forced=True) is False


async def test_watcher_wakes_up_on_request(config_file: Path) -> None:
    applied: list[AgentConfig] = []

    async def on_change(new: AgentConfig) -> None:
        applied.append(new)

    watcher = ConfigWatcher(config_file, load_config(config_file), on_change, check_interval=3600)
    task = asyncio.create_task(watcher.run())
    config_file.write_text(config_file.read_text().replace("mesh_number = 0", "mesh_number = 2"))
    watcher.wake.set()  # what SIGHUP does
    async with asyncio.timeout(5):
        while not applied:  # noqa: ASYNC110 (polling a test condition)
            await asyncio.sleep(0.01)
    task.cancel()
    assert applied[0].mesh_number == 2
