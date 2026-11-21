"""Local socket: protocol, hub, instances."""

import asyncio
import base64
import os
import uuid
from pathlib import Path

import pytest

from agent_harness import FakeController, answer, wait_for, wired
from h42mesh.agent.ipc.channel import WorkerUnavailableError
from h42mesh.agent.ipc.hub import WorkerHub
from h42mesh.agent.ipc.protocol import (
    MAX_MESSAGE_BYTES,
    CallFailed,
    Hello,
    HttpCall,
    HttpResult,
    ProtocolError,
    decode,
    encode,
)

UID = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)


# --- protocol ----------------------------------------------------------------


def test_round_trip_of_every_message() -> None:
    messages: list[Hello | HttpCall | HttpResult | CallFailed] = [
        Hello(connection_uid=UID, pid=42),
        HttpCall(id=1, method="GET", path="/api/v1/agent/config", headers={"A": "b"}),
        HttpResult(id=1, status=200, headers={}, body_b64="", controller="https://x"),
        CallFailed(id=1, reason="down"),
    ]
    for message in messages:
        line = encode(message)
        assert line.endswith(b"\n") and line.count(b"\n") == 1
        assert decode(line) == message


@pytest.mark.parametrize(
    "line",
    [
        b"not json\n",
        b'{"type": "unknown"}\n',
        b'{"type": "hello", "connection_uid": "x", "pid": 1}\n',
        b'{"type": "http_call", "id": 1, "method": "PATCH", "path": "/"}\n',
        b'{"type": "http_call", "id": 1, "method": "GET", "path": "/a?b=c"}\n',
        b'{"type": "call_failed", "id": 1, "reason": "x", "extra": 1}\n',
    ],
)
def test_invalid_messages(line: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode(line)


def test_message_size_limit() -> None:
    big = HttpResult(
        id=1, status=200, headers={}, body_b64="A" * MAX_MESSAGE_BYTES, controller="https://x"
    )
    with pytest.raises(ProtocolError, match="too large"):
        encode(big)


def test_body_is_base64() -> None:
    call = HttpCall(id=1, method="POST", path="/x", body_b64=base64.b64encode(b"\x00{").decode())
    assert call.body == b"\x00{"


# --- hub and instances -------------------------------------------------------


async def test_call_through_an_instance() -> None:
    controller = FakeController(lambda call: answer(200, b'{"ok": true}', etag='"f"'))
    hub = WorkerHub({UID})
    async with wired(hub, {UID: controller}):
        link = hub.get(UID)
        assert link is not None
        result = await link.call(
            HttpCall(
                id=0,
                method="POST",
                path="/api/v1/x",
                headers={"H": "v"},
                body_b64="e30=",
                family="ipv6",
            )
        )
    assert (result.status, result.body, result.headers) == (200, b'{"ok": true}', {"etag": '"f"'})
    (call,) = controller.calls
    assert call == {
        "method": "POST",
        "path": "/api/v1/x",
        "body": b"{}",
        "headers": {"H": "v"},
        "family": "ipv6",
    }


async def test_concurrent_calls_are_correlated() -> None:
    def handler(call: dict[str, object]) -> object:
        return answer(200, str(call["path"]).encode())

    hub = WorkerHub({UID})
    async with wired(hub, {UID: FakeController(handler)}):  # type: ignore[arg-type]
        link = hub.get(UID)
        assert link is not None
        results = await asyncio.gather(
            *(link.call(HttpCall(id=0, method="GET", path=f"/p{i}")) for i in range(20))
        )
    assert [r.body for r in results] == [f"/p{i}".encode() for i in range(20)]


async def test_unreachable_controller_is_reported() -> None:
    hub = WorkerHub({UID})
    async with wired(hub, {UID: FakeController(lambda c: answer(200), unreachable=True)}):
        link = hub.get(UID)
        assert link is not None
        with pytest.raises(WorkerUnavailableError, match="no route"):
            await link.call(HttpCall(id=0, method="GET", path="/"))


async def test_disconnected_instance() -> None:
    hub = WorkerHub({UID})
    async with wired(hub, {UID: FakeController(lambda c: answer(200))}) as tasks:
        link = hub.get(UID)
        assert link is not None
        tasks[UID].cancel()
        await wait_for(lambda: hub.get(UID) is None)
        with pytest.raises(WorkerUnavailableError):
            await link.call(HttpCall(id=0, method="GET", path="/"))
    assert hub.connected() == set()


async def test_unexpected_instance_is_refused() -> None:
    hub = WorkerHub({UID})
    server = await asyncio.start_server(hub.handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(encode(Hello(connection_uid=OTHER, pid=1)))
    await writer.drain()
    assert await reader.read() == b""  # closed by the hub
    assert hub.connected() == set()
    writer.close()
    server.close()


async def test_garbage_instead_of_hello() -> None:
    hub = WorkerHub({UID})
    server = await asyncio.start_server(hub.handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"hello?\n")
    await writer.drain()
    assert await reader.read() == b""
    writer.close()
    server.close()


async def test_reconnection_replaces_the_previous_link() -> None:
    hub = WorkerHub({UID})
    first = FakeController(lambda c: answer(201))
    async with wired(hub, {UID: first}):
        old = hub.get(UID)
        second = FakeController(lambda c: answer(202))
        server = await asyncio.start_server(hub.handle_connection, "127.0.0.1", 0)
        from agent_harness import connect_instance

        task = asyncio.create_task(
            connect_instance(server.sockets[0].getsockname()[1], UID, second)
        )
        await wait_for(lambda: hub.get(UID) is not None and hub.get(UID) is not old)
        link = hub.get(UID)
        assert link is not None
        assert (await link.call(HttpCall(id=0, method="GET", path="/"))).status == 202
        task.cancel()
        server.close()


async def test_on_connect_callback() -> None:
    seen: list[uuid.UUID] = []

    async def on_connect(uid: uuid.UUID) -> None:
        seen.append(uid)

    hub = WorkerHub({UID, OTHER}, on_connect=on_connect)
    controllers = {
        UID: FakeController(lambda c: answer(200)),
        OTHER: FakeController(lambda c: answer(200)),
    }
    async with wired(hub, controllers):
        await wait_for(lambda: len(seen) == 2)
    assert set(seen) == {UID, OTHER}


@pytest.mark.skipif(os.name != "posix", reason="Unix sockets")
async def test_unix_socket(tmp_path: Path) -> None:
    from agent_harness import FakeController as Fake
    from h42mesh.agent import system
    from h42mesh.agent.ipc.channel import Channel
    from h42mesh.agent.worker import serve

    path = tmp_path / "run" / "agent.sock"
    hub = WorkerHub({UID})
    server = await system.start_unix_server(path, hub.handle_connection)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    reader, writer = await system.open_unix_connection(path)
    task = asyncio.create_task(serve(Channel(reader, writer), UID, Fake(lambda c: answer(204))))
    await wait_for(lambda: hub.get(UID) is not None)
    link = hub.get(UID)
    assert link is not None
    assert (await link.call(HttpCall(id=0, method="GET", path="/"))).status == 204
    task.cancel()
    server.close()


# --- tunnel messages ---------------------------------------------------------


def test_round_trip_of_the_tunnel_messages() -> None:
    from fake_tunnel_backend import make_spec
    from h42mesh.agent.ipc.protocol import (
        AnyMessage,
        TunnelsApplied,
        TunnelsApply,
        TunnelStatuses,
        TunnelStatusQuery,
    )
    from h42mesh.agent.tunnels.backend import TunnelStatus

    messages: list[AnyMessage] = [
        TunnelsApply(id=3, connection_number=1, tunnels=[make_spec()]),
        TunnelsApplied(id=3, created=["wd0c0parir0c0"], errors={"wd0c0rootr0c0": "x"}),
        TunnelStatusQuery(id=4),
        TunnelStatuses(
            id=4, tunnels=[TunnelStatus(name="wd0c0parir0c0", tunnel_id=UID, running=True)]
        ),
    ]
    for message in messages:
        assert decode(encode(message)) == message


async def test_answer_of_another_type_is_refused() -> None:
    from h42mesh.agent.ipc.protocol import TunnelsApplied, TunnelStatusQuery

    hub = WorkerHub({UID})
    async with wired(hub, {UID: FakeController(lambda c: answer(200))}):
        link = hub.get(UID)
        assert link is not None
        # This instance has no tunnel management: call_failed.
        with pytest.raises(WorkerUnavailableError, match="no tunnel management"):
            await link.request(TunnelStatusQuery(id=0), TunnelsApplied)
