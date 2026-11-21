"""Which connection instance to use to reach the controller."""

from uuid import UUID

from h42mesh.agent.config import ConnectionSettings
from h42mesh.agent.messages import ConnectionRole, RouterConfig


def connection_order(settings: list[ConnectionSettings], config: RouterConfig | None) -> list[UUID]:
    """Active connections first, then backup ones; within a role, the lowest
    priority first, connections without priority after, then by number.

    Before any configuration is received, the order of agent.toml is kept.
    Connections unknown to the controller come last, in agent.toml order.
    """
    local = [s.uid for s in settings]
    if config is None:
        return local
    known = {c.id: c for c in config.connections}

    def key(uid: UUID) -> tuple[int, int, int, int]:
        connection = known[uid]
        role = 0 if connection.role is ConnectionRole.ACTIVE else 1
        no_priority = connection.priority is None
        priority = connection.priority if connection.priority is not None else 0
        return role, int(no_priority), priority, connection.number

    ordered = sorted((uid for uid in local if uid in known), key=key)
    return ordered + [uid for uid in local if uid not in known]
