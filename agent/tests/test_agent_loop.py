"""Main process logic, with real hub and instances and a fake controller."""

import json
import uuid
from pathlib import Path
from typing import Any

import jwt
import pytest

from agent_harness import FakeController, answer, wait_for, wired
from h42mesh.agent.agent_loop import (
    Agent,
    ConfigRejectedError,
    ControllerError,
    ControllerUnreachableError,
)
from h42mesh.agent.config import AgentConfig, ConnectionSettings
from h42mesh.agent.ipc.hub import WorkerHub
from h42mesh.agent.messages import RouterConfig
from h42mesh.agent.signing import TokenSigner, generate_key
from h42mesh.agent.state import StateStore, StoredConfig
from test_messages import config_document

ROUTER = uuid.UUID(int=99)
FIBER, LTE = uuid.UUID(int=1), uuid.UUID(int=2)
KEY = generate_key()


def agent_config(**fiber: Any) -> AgentConfig:
    return AgentConfig(
        controllers=["https://vps1.test"],
        connections=[
            ConnectionSettings(uid=FIBER, interface="eth1", vrf="wan0", **fiber),
            ConnectionSettings(uid=LTE, interface="wwan0", vrf="wan1"),
        ],
    )


def router_config(fingerprint: str = "f1", lte_first: bool = False) -> dict[str, Any]:
    def connection(uid: uuid.UUID, number: int, role: str) -> dict[str, Any]:
        return {
            "id": str(uid),
            "number": number,
            "name": f"c{number}",
            "role": role,
            "priority": None,
            "direct": "none",
            "public_ipv4": None,
            "public_ipv6": None,
        }

    roles = ("backup", "active") if lte_first else ("active", "backup")
    return config_document(
        fingerprint=fingerprint,
        connections=[connection(FIBER, 0, roles[0]), connection(LTE, 1, roles[1])],
    )


def make_agent(tmp_path: Path, config: AgentConfig | None = None) -> Agent:
    config = config or agent_config()
    hub = WorkerHub({c.uid for c in config.connections})
    return Agent(
        config=config,
        store=StateStore(tmp_path / "state"),
        signer=TokenSigner(KEY, ROUTER, config.jwt_audience),
        hub=hub,
    )


def config_answer(document: dict[str, Any], etag: str | None = None) -> Any:
    body = json.dumps(document).encode()
    return answer(200, body, etag=f'"{etag or document["fingerprint"]}"')


# --- requests and choice of the instance ------------------------------------


async def test_request_is_signed_and_prefixed(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber = FakeController(lambda c: answer(200, b"{}"))
    async with wired(agent.hub, {FIBER: fiber}):
        await agent.call("GET", "/agent/me")
    (call,) = fiber.calls
    assert call["path"] == "/api/v1/agent/me"
    token = call["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token, KEY.public_key(), algorithms=["EdDSA"], audience="h42-mesh-controller"
    )
    assert claims["iss"] == claims["sub"] == str(ROUTER)


async def test_each_attempt_has_a_fresh_jti(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber = FakeController(lambda c: answer(200), unreachable=True)
    lte = FakeController(lambda c: answer(200))
    async with wired(agent.hub, {FIBER: fiber, LTE: lte}):
        await agent.call("GET", "/agent/me")
    tokens = [c["headers"]["Authorization"] for c in fiber.calls + lte.calls]
    assert len(set(tokens)) == 2


async def test_active_connection_first(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    agent.store.save_config(_stored(router_config(lte_first=True)))
    fiber, lte = FakeController(lambda c: answer(200)), FakeController(lambda c: answer(200))
    async with wired(agent.hub, {FIBER: fiber, LTE: lte}):
        await agent.call("GET", "/agent/me")
    assert (len(lte.calls), len(fiber.calls)) == (1, 0)


async def test_next_connection_when_one_fails(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber = FakeController(lambda c: answer(200), unreachable=True)
    lte = FakeController(lambda c: answer(201))
    async with wired(agent.hub, {FIBER: fiber, LTE: lte}):
        assert (await agent.call("GET", "/agent/me")).status == 201
    assert (len(fiber.calls), len(lte.calls)) == (1, 1)


async def test_controller_errors_do_not_switch_connection(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber, lte = FakeController(lambda c: answer(401)), FakeController(lambda c: answer(200))
    async with wired(agent.hub, {FIBER: fiber, LTE: lte}):
        assert (await agent.call("GET", "/agent/me")).status == 401
    assert lte.calls == []


async def test_disconnected_instances_are_skipped(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    lte = FakeController(lambda c: answer(200))
    async with wired(agent.hub, {LTE: lte}):  # fiber instance not running
        await agent.call("GET", "/agent/me")
    assert len(lte.calls) == 1


async def test_nobody_reachable(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber = FakeController(lambda c: answer(200), unreachable=True)
    async with wired(agent.hub, {FIBER: fiber}):
        with pytest.raises(ControllerUnreachableError, match="no route"):
            await agent.call("GET", "/agent/me")
    with pytest.raises(ControllerUnreachableError, match="no connection instance"):
        await agent.call("GET", "/agent/me")


# --- configuration -----------------------------------------------------------


def _stored(document: dict[str, Any]) -> StoredConfig:
    from datetime import UTC, datetime

    config = RouterConfig.model_validate(document)
    return StoredConfig(
        fingerprint=config.fingerprint,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        controller="https://vps1.test",
        config=config,
    )


async def test_new_configuration_is_stored(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber = FakeController(lambda c: config_answer(router_config("f1")))
    async with wired(agent.hub, {FIBER: fiber}):
        assert await agent.refresh_config() is True
    stored = agent.store.load_config()
    assert stored is not None
    assert (stored.fingerprint, stored.controller) == ("f1", "https://vps1.test")
    assert "If-None-Match" not in fiber.calls[0]["headers"]


async def test_if_none_match_and_304(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    agent.store.save_config(_stored(router_config("f1")))

    def controller(call: dict[str, Any]) -> Any:
        return answer(304) if call["headers"].get("If-None-Match") == '"f1"' else answer(500)

    fiber = FakeController(controller)
    async with wired(agent.hub, {FIBER: fiber}):
        assert await agent.refresh_config() is False
    assert agent.store.load_previous_config() is None  # nothing rotated


async def test_changed_configuration_rotates(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    agent.store.save_config(_stored(router_config("f1")))
    fiber = FakeController(lambda c: config_answer(router_config("f2")))
    async with wired(agent.hub, {FIBER: fiber}):
        assert await agent.refresh_config() is True
    current, previous = agent.store.load_config(), agent.store.load_previous_config()
    assert current is not None and previous is not None
    assert (current.fingerprint, previous.fingerprint) == ("f2", "f1")


@pytest.mark.parametrize(
    ("make_answer", "error"),
    [
        (lambda: answer(200, b"not json", etag='"f2"'), ConfigRejectedError),
        (lambda: config_answer({**router_config("f2"), "tunnels": "?"}), ConfigRejectedError),
        (lambda: config_answer(router_config("f2"), etag="other"), ConfigRejectedError),
        (lambda: answer(401, b'{"code": "invalid_agent_token", "message": "x"}'), ControllerError),
        (lambda: answer(403, b'{"code": "router_revoked", "message": "x"}'), ControllerError),
    ],
)
async def test_rejected_configuration_keeps_the_stored_one(
    tmp_path: Path, make_answer: Any, error: type[Exception]
) -> None:
    agent = make_agent(tmp_path)
    agent.store.save_config(_stored(router_config("f1")))
    async with wired(agent.hub, {FIBER: FakeController(lambda c: make_answer())}):
        with pytest.raises(error):
            await agent.refresh_config()
    stored = agent.store.load_config()
    assert stored is not None and stored.fingerprint == "f1"


async def test_controller_error_code(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    body = b'{"code": "router_revoked", "message": "revoked"}'
    async with wired(agent.hub, {FIBER: FakeController(lambda c: answer(403, body))}):
        with pytest.raises(ControllerError) as info:
            await agent.refresh_config()
    assert (info.value.status, info.value.code) == (403, "router_revoked")


# --- public addresses --------------------------------------------------------


def address_answer(call: dict[str, Any]) -> Any:
    body = json.loads(call["body"])
    address = body["forced_address"] or (
        "93.184.216.34" if body["family"] == "ipv4" else "2a00:1450::1"
    )
    result = {"family": body["family"], "address": address, "isp": "Example"}
    return answer(200, json.dumps(result).encode())


async def test_discovery_uses_the_connection_itself(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    fiber, lte = FakeController(address_answer), FakeController(address_answer)
    async with wired(agent.hub, {FIBER: fiber, LTE: lte}):
        found = await agent.discover_addresses(agent.config.connections[1])  # LTE
    assert fiber.calls == []
    assert [c["family"] for c in lte.calls] == ["ipv4", "ipv6"]
    bodies = [json.loads(c["body"]) for c in lte.calls]
    assert {b["connection_id"] for b in bodies} == {str(LTE)}
    assert [str(r.address) for r in found] == ["93.184.216.34", "2a00:1450::1"]


async def test_forced_address_in_the_request(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, agent_config(force_ipv4="93.184.216.99"))
    fiber = FakeController(address_answer)
    async with wired(agent.hub, {FIBER: fiber}):
        found = await agent.discover_addresses(agent.config.connections[0])
    bodies = [json.loads(c["body"]) for c in fiber.calls]
    assert [b["forced_address"] for b in bodies] == ["93.184.216.99", None]
    assert str(found[0].address) == "93.184.216.99"


async def test_discovery_continues_after_a_refusal(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)

    def controller(call: dict[str, Any]) -> Any:
        if call["family"] == "ipv4":
            return answer(422, b'{"code": "address_not_public", "message": "10.0.0.2"}')
        return address_answer(call)

    async with wired(agent.hub, {FIBER: FakeController(controller)}):
        found = await agent.discover_addresses(agent.config.connections[0])
    assert [r.family for r in found] == ["ipv6"]


async def test_discovery_when_the_instance_connects(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    agent.hub.on_connect = agent.on_instance_connected
    fiber = FakeController(address_answer)
    async with wired(agent.hub, {FIBER: fiber}):
        await wait_for(lambda: len(fiber.calls) == 2)
    assert all(c["path"] == "/api/v1/agent/public-address" for c in fiber.calls)
