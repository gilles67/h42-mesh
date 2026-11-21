"""Integration: real VRF, real ``ip vrf exec``, real Unix socket.

Linux only, as root, and only with H42_MESH_AGENT_INTEGRATION=1:

    sudo H42_MESH_AGENT_INTEGRATION=1 uv run pytest -m integration

A test VRF (h42test0, table 4242, without any route) is created and removed.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_harness import wait_for

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (
            sys.platform == "linux"
            and hasattr(os, "geteuid")
            and os.geteuid() == 0
            and os.environ.get("H42_MESH_AGENT_INTEGRATION") == "1"
        ),
        reason="needs Linux, root and H42_MESH_AGENT_INTEGRATION=1",
    ),
]

VRF = "h42test0"
UID = uuid.UUID("6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f")


def ip(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ip", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607


@pytest.fixture
def vrf() -> Iterator[str]:
    ip("link", "del", VRF)
    assert ip("link", "add", VRF, "type", "vrf", "table", "4242").returncode == 0
    assert ip("link", "set", VRF, "up").returncode == 0
    try:
        yield VRF
    finally:
        ip("link", "del", VRF)


@pytest.fixture
def config_file(tmp_path: Path, vrf: str) -> Path:
    path = tmp_path / "agent.toml"
    path.write_text(
        'controllers = ["https://vps1.example.org"]\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        "[[connections]]\n"
        f'uid = "{UID}"\ninterface = "lo"\nvrf = "{vrf}"\n'
    )
    return path


def test_vrf_exists(vrf: str) -> None:
    from h42mesh.agent import system

    assert system.vrf_exists(vrf)
    assert not system.vrf_exists("lo")  # a device, not a VRF
    assert not system.vrf_exists("h42nothing")


def test_no_route_in_an_empty_vrf(vrf: str) -> None:
    code = (
        "from h42mesh.agent import system; "
        "raise SystemExit(0 if not system.family_available(4) else 1)"
    )
    result = subprocess.run(  # noqa: S603
        ["ip", "vrf", "exec", vrf, sys.executable, "-c", code],  # noqa: S607
        check=False,
    )
    assert result.returncode == 0


async def test_instance_runs_in_its_vrf_and_is_restarted(
    tmp_path: Path, config_file: Path, vrf: str
) -> None:
    from h42mesh.agent import system
    from h42mesh.agent.config import load_config
    from h42mesh.agent.ipc.hub import WorkerHub
    from h42mesh.agent.supervisor import InstanceSupervisor, worker_command

    config = load_config(config_file)
    socket = tmp_path / "run" / "agent.sock"
    hub = WorkerHub({UID})
    server = await system.start_unix_server(socket, hub.handle_connection)
    settings = config.connections[0]
    supervisor = InstanceSupervisor(
        settings, worker_command(settings, config_file, socket), system.vrf_exists
    )
    task = asyncio.create_task(supervisor.run())
    try:
        await wait_for(lambda: hub.get(UID) is not None, 30)
        process = supervisor.process
        assert process is not None
        # The instance and its children are attached to the VRF.
        pid = getattr(process, "pid")  # noqa: B009
        identified = await asyncio.to_thread(ip, "vrf", "identify", str(pid))
        assert identified.stdout.strip() == vrf

        # Killed: restarted by the supervisor, and connected again.
        first = hub.get(UID)
        process.terminate()
        await wait_for(lambda: hub.get(UID) not in (None, first), 30)
        assert supervisor.starts == 2
    finally:
        supervisor.stop()
        task.cancel()
        server.close()
