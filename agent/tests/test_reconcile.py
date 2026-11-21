"""Reconciliation in the connection instance, with the fake backend."""

import uuid

from fake_tunnel_backend import FakeTunnelBackend, make_spec
from h42mesh.agent.tunnels.reconcile import TunnelManager

A = make_spec(name="wd0c0parir0c0", tunnel_id=uuid.UUID(int=1), listen_port=42001)
B = make_spec(name="wd0c0rootr0c0", tunnel_id=uuid.UUID(int=2), listen_port=42002)


async def test_creates_the_missing_tunnels() -> None:
    backend = FakeTunnelBackend()
    report = await TunnelManager(backend).reconcile([A, B])
    assert report.created == [A.name, B.name]
    assert backend.tunnels == {A.name: A, B.name: B}


async def test_twice_the_same_changes_nothing() -> None:
    backend = FakeTunnelBackend()
    manager = TunnelManager(backend)
    await manager.reconcile([A, B])
    backend.calls.clear()
    report = await manager.reconcile([A, B])
    assert backend.calls == []
    assert (report.created, report.updated, report.deleted) == ([], [], [])


async def test_updates_a_changed_tunnel() -> None:
    backend = FakeTunnelBackend()
    manager = TunnelManager(backend)
    await manager.reconcile([A])
    changed = A.model_copy(update={"fallback_delay": 60})
    report = await manager.reconcile([changed])
    assert report.updated == [A.name]
    assert backend.tunnels[A.name] == changed


async def test_deletes_the_tunnels_no_longer_wanted() -> None:
    backend = FakeTunnelBackend()
    manager = TunnelManager(backend)
    await manager.reconcile([A, B])
    report = await manager.reconcile([A])
    assert report.deleted == [B.name]
    assert list(backend.tunnels) == [A.name]
    assert B.name not in manager.applied


async def test_left_over_interfaces() -> None:
    """Left by a previous instance: an unwanted one is deleted, a wanted one recreated."""
    backend = FakeTunnelBackend(left_over=(A.name, "wd0c0oldsr0c0"))
    report = await TunnelManager(backend).reconcile([A])
    assert report.deleted == ["wd0c0oldsr0c0"]
    assert report.created == [A.name]
    assert ("delete", A.name) in backend.calls
    assert backend.tunnels == {A.name: A}


async def test_a_failure_does_not_stop_the_others() -> None:
    backend = FakeTunnelBackend()
    backend.failing.add(A.name)
    manager = TunnelManager(backend)
    report = await manager.reconcile([A, B])
    assert report.created == [B.name]
    assert "create failed" in report.errors[A.name]
    # Tried again at the next reconciliation.
    backend.failing.clear()
    assert (await manager.reconcile([A, B])).created == [A.name]


async def test_duplicate_names_are_refused() -> None:
    backend = FakeTunnelBackend()
    other = A.model_copy(update={"tunnel_id": uuid.UUID(int=9)})
    report = await TunnelManager(backend).reconcile([A, other, B])
    assert list(report.errors) == [A.name]
    assert list(backend.tunnels) == [B.name]


async def test_statuses_and_close() -> None:
    backend = FakeTunnelBackend(left_over=("wd0c0oldsr0c0",))
    manager = TunnelManager(backend)
    await manager.reconcile([A, B, make_spec(name="wd0c0oldsr0c0")])
    statuses = await manager.statuses()
    # By name: wd0c0olds…, wd0c0pari…, wd0c0root…
    assert [s.tunnel_id for s in statuses] == [make_spec().tunnel_id, A.tunnel_id, B.tunnel_id]
    await manager.close()
    assert backend.closed and manager.applied == {}
