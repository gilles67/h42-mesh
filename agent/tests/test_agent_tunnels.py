"""Tunnels of the main process: real hub and instances, fake controller and backend."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from agent_harness import FakeController, answer, wait_for, wired
from fake_tunnel_backend import FakeTunnelBackend
from h42mesh.agent.agent_loop import Agent
from h42mesh.agent.state import TunnelState
from h42mesh.agent.tunnels.backend import TunnelBackend
from h42mesh.agent.worker import InstanceTunnels
from test_agent_loop import FIBER, LTE, _stored, make_agent
from test_messages import config_document, tunnel_document

T1 = uuid.UUID(int=11)
NAME = "wd0c0rootr0c0"


def connection(uid: uuid.UUID, number: int) -> dict[str, Any]:
    return {
        "id": str(uid),
        "number": number,
        "name": f"c{number}",
        "role": "active",
        "priority": None,
        "direct": "none",
        "public_ipv4": None,
        "public_ipv6": None,
    }


def document(*tunnels: dict[str, Any]) -> dict[str, Any]:
    return config_document(
        connections=[connection(FIBER, 0), connection(LTE, 1)], tunnels=list(tunnels)
    )


def fiber_tunnel(**overrides: Any) -> dict[str, Any]:
    return tunnel_document(id=str(T1), local_connection_id=str(FIBER), **overrides)


class Backends:
    """One fake backend per interface prefix, as the instances create them."""

    def __init__(self) -> None:
        self.by_prefix: dict[str, FakeTunnelBackend] = {}

    def factory(self, prefix: str) -> TunnelBackend:
        return self.by_prefix.setdefault(prefix, FakeTunnelBackend(prefix))

    def instances(self) -> dict[uuid.UUID, InstanceTunnels]:
        return {uid: InstanceTunnels(0, self.factory) for uid in (FIBER, LTE)}


def accepting(call: dict[str, Any]) -> Any:
    if call["path"] == "/api/v1/agent/tunnels":
        return answer(204)
    return answer(500)


@pytest.fixture
def agent(tmp_path: Path) -> Agent:
    agent = make_agent(tmp_path)
    agent.store.save_config(_stored(document(fiber_tunnel())))
    return agent


async def test_nothing_without_configuration(tmp_path: Path) -> None:
    assert await make_agent(tmp_path).apply_tunnels() is None


async def test_tunnels_are_applied_by_the_instance_of_their_connection(agent: Agent) -> None:
    backends = Backends()
    fiber, lte = FakeController(accepting), FakeController(accepting)
    async with wired(agent.hub, {FIBER: fiber, LTE: lte}, backends.instances()):
        plan = await agent.apply_tunnels()
    assert plan is not None
    assert list(backends.by_prefix["wd0c0"].tunnels) == [NAME]
    assert backends.by_prefix["wd0c1"].tunnels == {}

    # Key and port reported once, through the best connection.
    (call,) = fiber.calls
    reported = json.loads(call["body"])["tunnels"]
    state = agent.store.load_tunnel(T1)
    assert state is not None
    assert reported == [
        {"tunnel_id": str(T1), "public_key": reported[0]["public_key"], "port": state.port}
    ]
    assert state.public_key_registered and state.port_registered


async def test_twice_the_same_changes_nothing(agent: Agent) -> None:
    backends = Backends()
    async with wired(agent.hub, {FIBER: FakeController(accepting)}, backends.instances()):
        await agent.apply_tunnels()
        fake = backends.by_prefix["wd0c0"]
        calls = list(fake.calls)
        await agent.apply_tunnels()
    assert fake.calls == calls


async def test_applied_even_if_the_controller_cannot_be_reached(agent: Agent) -> None:
    backends = Backends()
    unreachable = FakeController(accepting, unreachable=True)
    async with wired(agent.hub, {FIBER: unreachable}, backends.instances()):
        await agent.apply_tunnels()
    assert list(backends.by_prefix["wd0c0"].tunnels) == [NAME]
    state = agent.store.load_tunnel(T1)
    assert state is not None and not state.public_key_registered


async def test_removed_tunnel(agent: Agent) -> None:
    backends = Backends()
    async with wired(agent.hub, {FIBER: FakeController(accepting)}, backends.instances()):
        await agent.apply_tunnels()
        agent.store.save_config(_stored(document() | {"fingerprint": "f2"}))
        await agent.apply_tunnels()
    assert backends.by_prefix["wd0c0"].tunnels == {}
    assert agent.store.tunnel_ids() == []  # key deleted with the tunnel


async def test_given_to_an_instance_when_it_connects(agent: Agent) -> None:
    backends = Backends()
    agent.hub.on_connect = agent.on_instance_connected
    async with wired(agent.hub, {FIBER: FakeController(accepting)}, backends.instances()):
        await wait_for(lambda: NAME in backends.by_prefix.get("wd0c0", FakeTunnelBackend()).tunnels)


async def test_tunnel_errors_do_not_stop_the_agent(agent: Agent) -> None:
    backends = Backends()
    backends.factory("wd0c0")
    backends.by_prefix["wd0c0"].failing.add(NAME)
    async with wired(agent.hub, {FIBER: FakeController(accepting)}, backends.instances()):
        assert await agent.apply_tunnels() is not None


async def test_instance_without_tunnel_management(agent: Agent) -> None:
    async with wired(agent.hub, {FIBER: FakeController(accepting)}):
        assert await agent.apply_tunnels() is not None  # logged, not raised


async def test_tunnel_statuses(agent: Agent) -> None:
    backends = Backends()
    async with wired(
        agent.hub, {FIBER: FakeController(accepting), LTE: FakeController(accepting)},
        backends.instances(),
    ):  # fmt: skip
        assert await agent.tunnel_statuses() == {FIBER: [], LTE: []}
        await agent.apply_tunnels()
        statuses = await agent.tunnel_statuses()
    assert [s.tunnel_id for s in statuses[FIBER]] == [T1]
    assert statuses[LTE] == []


async def test_stored_state_with_its_port(agent: Agent) -> None:
    agent.store.save_tunnel(
        TunnelState(tunnel_id=T1, private_key=fiber_tunnel()["preshared_key"], port=43210)
    )
    backends = Backends()
    async with wired(agent.hub, {FIBER: FakeController(accepting)}, backends.instances()):
        await agent.apply_tunnels()
    spec = backends.by_prefix["wd0c0"].tunnels[NAME]
    assert spec is not None and spec.listen_port == 43210


async def test_renumbered_connection_gets_a_new_backend() -> None:
    from fake_tunnel_backend import make_spec
    from h42mesh.agent.ipc.protocol import TunnelsApply

    backends = Backends()
    tunnels = InstanceTunnels(0, backends.factory)
    await tunnels.apply(TunnelsApply(id=1, connection_number=0, tunnels=[make_spec()]))
    applied = await tunnels.apply(
        TunnelsApply(id=2, connection_number=1, tunnels=[make_spec(name="wd0c1parir0c0")])
    )
    assert applied.created == ["wd0c1parir0c0"]
    assert backends.by_prefix["wd0c0"].closed
    await tunnels.close()
    assert backends.by_prefix["wd0c1"].closed
