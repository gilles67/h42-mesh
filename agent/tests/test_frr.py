"""FRR configuration: generated files compared with tests/data/frr/*.conf.

After a deliberate change of the template, regenerate the files, then review
the differences with git:

    H42_MESH_UPDATE_EXPECTED=1 uv run pytest tests/test_frr.py
"""

import os
from pathlib import Path

import pytest

from frr_cases import CASES, LINKS, backup_tunnel, two_routers
from h42mesh.agent.routing import frr

EXPECTED = Path(__file__).parent / "data" / "frr"


def generated(name: str) -> str:
    config, agent, plan = CASES[name]()
    return frr.render(frr.build_model(config, agent, plan, LINKS))


@pytest.mark.parametrize("name", sorted(CASES))
def test_generated_file(name: str) -> None:
    path = EXPECTED / f"{name}.conf"
    text = generated(name)
    if os.environ.get("H42_MESH_UPDATE_EXPECTED") == "1":
        path.write_text(text, encoding="utf-8", newline="\n")
    assert text == path.read_text(encoding="utf-8")


def test_generation_is_stable() -> None:
    assert generated("backup_tunnel") == generated("backup_tunnel")


def test_backup_community_of_the_site() -> None:
    text = generated("backup_tunnel")
    assert " set large-community 4200000001:1:2 additive\n" in text
    assert "bgp large-community-list expanded H42-BACKUP-ROUTES permit _[0-9]+:1:2_\n" in text


def test_backup_only_where_needed() -> None:
    active = generated("active_tunnel")
    assert "H42-BACKUP " not in active and "H42-IN-BACKUP" not in active
    assert "H42-INTERNAL" not in active


def test_sessions() -> None:
    config, agent, plan = backup_tunnel()
    model = frr.build_model(config, agent, plan, LINKS)
    assert [(n.interface, n.group, n.remote_as) for n in model.neighbors] == [
        ("wd0c0rootr0c0", frr.ACTIVE, 4200000000),
        ("wd0c1rootr0c0", frr.BACKUP, 4200000000),
    ]
    # Link-local address of the other end of the tunnel.
    assert str(model.neighbors[0].address) == "fe80::a9fe:a00"


def test_internal_link() -> None:
    config, agent, plan = two_routers()
    model = frr.build_model(config, agent, plan, LINKS)
    internal = model.neighbors[-1]
    assert (internal.interface, internal.group, internal.remote_as) == (
        "br-lan",
        frr.INTERNAL,
        None,
    )
    text = frr.render(model)
    assert "  neighbor H42-INTERNAL next-hop-self\n" in text
    assert " neighbor fe80::1a2b:3cff:fe4d:5e6f interface br-lan\n" in text


def test_pending_tunnels_have_no_session() -> None:
    config, agent, plan = backup_tunnel()
    plan.specs = {uid: [] for uid in plan.specs}
    model = frr.build_model(config, agent, plan, LINKS)
    assert model.neighbors == []
    assert "neighbor fe80" not in frr.render(model)


def test_excluded_interfaces() -> None:
    links = ["lo", "eth0", "br-lan", "br-0123456789ab", "docker0", "podman0", "cni-podman0",
             "virbr0", "veth9f", "wd0c0oldsr0c0", "wdx"]  # fmt: skip
    assert frr.excluded_interfaces(links, ["wd0c0rootr0c0"]) == [
        "br-0123456789ab", "cni-podman0", "docker0", "lo", "podman0", "veth9f", "virbr0",
        "wd0c0oldsr0c0", "wd0c0rootr0c0",
    ]  # fmt: skip


def test_no_router_id() -> None:
    assert "router-id" not in generated("two_routers")
