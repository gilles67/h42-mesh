import uuid
from typing import Any

from h42mesh.agent.config import ConnectionSettings
from h42mesh.agent.messages import RouterConfig
from h42mesh.agent.selection import connection_order
from test_messages import config_document

UIDS = [uuid.UUID(int=i + 1) for i in range(5)]


def settings(*uids: uuid.UUID) -> list[ConnectionSettings]:
    return [
        ConnectionSettings(uid=uid, interface=f"eth{i}", vrf=f"wan{i}")
        for i, uid in enumerate(uids)
    ]


def config(*connections: tuple[uuid.UUID, str, int | None, int]) -> RouterConfig:
    entries: list[dict[str, Any]] = [
        {
            "id": str(uid),
            "number": number,
            "name": f"c{number}",
            "role": role,
            "priority": priority,
            "direct": "none",
            "public_ipv4": None,
            "public_ipv6": None,
        }
        for uid, role, priority, number in connections
    ]
    return RouterConfig.model_validate(config_document(connections=entries, tunnels=[]))


def test_local_order_before_any_configuration() -> None:
    assert connection_order(settings(UIDS[2], UIDS[0]), None) == [UIDS[2], UIDS[0]]


def test_active_before_backup() -> None:
    cfg = config((UIDS[0], "backup", 1, 0), (UIDS[1], "active", 9, 1))
    assert connection_order(settings(UIDS[0], UIDS[1]), cfg) == [UIDS[1], UIDS[0]]


def test_priority_then_none_then_number() -> None:
    cfg = config(
        (UIDS[0], "active", None, 0),
        (UIDS[1], "active", 20, 1),
        (UIDS[2], "active", 10, 2),
        (UIDS[3], "active", None, 3),
        (UIDS[4], "backup", 1, 4),
    )
    order = connection_order(settings(*UIDS), cfg)
    assert order == [UIDS[2], UIDS[1], UIDS[0], UIDS[3], UIDS[4]]


def test_connections_unknown_to_the_controller_come_last() -> None:
    cfg = config((UIDS[1], "backup", None, 1))
    assert connection_order(settings(UIDS[0], UIDS[1]), cfg) == [UIDS[1], UIDS[0]]
