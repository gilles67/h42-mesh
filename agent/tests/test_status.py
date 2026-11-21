"""status.json: built by the loop, read and judged by the status command."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from frr_cases import FIBER, LTE, backup_tunnel
from h42mesh.agent.commands.status import status
from h42mesh.agent.messages import AddressFamily
from h42mesh.agent.observe import ControllerContact, build_status, tunnel_reports
from h42mesh.agent.state import StoredConfig
from h42mesh.agent.status_file import AgentStatus, problems, read_status, write_status
from h42mesh.agent.tunnels.backend import TunnelStatus

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
ROUTER = uuid.UUID(int=99)
ACTIVE_ID, BACKUP_ID = uuid.UUID(int=100), uuid.UUID(int=101)
STATES = {"fe80::a9fe:a00": "Established", "fe80::a9fe:b00": "Established"}


def healthy(**overrides: Any) -> AgentStatus:
    config, agent, plan = backup_tunnel()
    stored = StoredConfig(
        fingerprint="ab" * 32, received_at=NOW, controller="https://vps1.test", config=config
    )
    contact = ControllerContact()
    contact.succeeded(NOW - timedelta(seconds=20), "https://vps1.test", FIBER)
    values: dict[str, Any] = {
        "now": NOW,
        "started_at": NOW - timedelta(hours=2),
        "pid": 4242,
        "router_id": ROUTER,
        "stored": stored,
        "agent": agent.model_copy(update={"controllers": ["https://vps1.test"]}),
        "plan": plan,
        "connected": {FIBER, LTE},
        "vrf_exists": lambda name: True,
        "statuses": {
            FIBER: [
                TunnelStatus(
                    name="wd0c0rootr0c0",
                    tunnel_id=ACTIVE_ID,
                    running=True,
                    family_in_use=AddressFamily.IPV6,
                    last_handshake_at=NOW - timedelta(seconds=30),
                )
            ],
            LTE: [TunnelStatus(name="wd0c1rootr0c0", tunnel_id=BACKUP_ID, running=True)],
        },
        "bgp_states": STATES,
        "contact": contact,
        "errors": [],
    }
    values.update(overrides)
    return build_status(**values)


# --- building ----------------------------------------------------------------


def test_build_status() -> None:
    state = healthy()
    assert state.identity is not None
    assert (state.identity.site_nickname, state.identity.site_asn) == ("pari", 4200000001)
    assert [c.number for c in state.connections] == [0, 1]
    assert [(t.name, t.bgp_state) for t in state.tunnels] == [
        ("wd0c0rootr0c0", "Established"),
        ("wd0c1rootr0c0", "Established"),
    ]
    assert state.tunnels[0].family_in_use is AddressFamily.IPV6
    assert state.controller.first_controller is True
    assert problems(state, NOW) == []


def test_tunnel_reports_are_a_full_snapshot() -> None:
    config, _, plan = backup_tunnel()
    statuses = {FIBER: [TunnelStatus(name="wd0c0rootr0c0", tunnel_id=ACTIVE_ID, running=True,
                                     family_in_use=AddressFamily.IPV4)]}  # fmt: skip
    reports = tunnel_reports(config, plan, statuses, {"fe80::a9fe:a00": "Established"})
    assert [(r.tunnel_id, r.family_in_use, r.bgp_established) for r in reports] == [
        (ACTIVE_ID, AddressFamily.IPV4, True),
        (BACKUP_ID, None, False),  # not observed: reported down
    ]


# --- problems ----------------------------------------------------------------


def test_no_status_file() -> None:
    assert problems(None, NOW) == [
        "service not running: no status file (systemctl status h42-mesh-agent)"
    ]


def test_stale_status() -> None:
    found = problems(healthy(), NOW + timedelta(minutes=5))
    assert found[0].startswith("service stopped or blocked")


def test_controller_lost() -> None:
    contact = ControllerContact()
    contact.succeeded(NOW - timedelta(minutes=11), "https://vps1.test", FIBER)
    assert "controller not reached for more than 10 minutes" in problems(
        healthy(contact=contact), NOW
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"vrf_exists": lambda name: name != "wan1"}, "connection c1: VRF wan1 does not exist"),
        ({"connected": {FIBER}}, "connection c1: instance not running"),
        ({"statuses": {}}, "tunnel wd0c0rootr0c0: not running"),
        ({"bgp_states": {"fe80::a9fe:a00": "Active"}}, "tunnel wd0c0rootr0c0: BGP session Active"),
        ({"stored": None}, "no configuration received from the controller yet"),
        ({"router_id": None}, "not enrolled"),
    ],
)
def test_problems(overrides: dict[str, Any], expected: str) -> None:
    assert expected in problems(healthy(**overrides), NOW)


def test_pending_tunnel_is_not_a_problem() -> None:
    _, _, plan = backup_tunnel()
    plan.pending[BACKUP_ID] = "public key of the other end not known yet"
    plan.specs[LTE] = []
    state = healthy(plan=plan)
    assert state.tunnels[1].pending is not None
    assert problems(state, NOW) == []


def test_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "run" / "status.json"
    assert read_status(path) is None
    write_status(healthy(), path)
    assert read_status(path) == healthy()


# --- the command -------------------------------------------------------------

EXAMPLE = Path(__file__).parent / "data" / "agent.toml"


def run_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], state: AgentStatus | None, *, as_json: bool
) -> tuple[int, str]:
    file = tmp_path / "status.json"
    if state is not None:
        write_status(state, file)
    code = status(EXAMPLE, as_json, status_file=file, now=NOW)
    return code, capsys.readouterr().out


def test_command_when_everything_works(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run_status(tmp_path, capsys, healthy(), as_json=False)
    assert code == 0
    assert "mesh home42, site pari (AS 4200000001), router r0" in out
    assert "service: running (pid 4242, started 2 h ago), status 0 s ago" in out
    assert "last exchange 20 s ago with https://vps1.test (first)" in out
    assert "c0  c0  active  eth1  vrf wan0  instance up" in out
    assert "wd0c0rootr0c0  root r0 c0  side b  active  up  ipv6  handshake 30 s ago" in out
    assert out.rstrip().endswith("Problems\n  none")


def test_command_with_a_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run_status(tmp_path, capsys, healthy(statuses={}), as_json=False)
    assert code == 1
    assert "  - tunnel wd0c0rootr0c0: not running" in out


def test_command_when_the_service_is_stopped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_status(tmp_path, capsys, None, as_json=False)
    assert code == 1
    assert "service: not running" in out
    assert "  - service not running" in out


def test_command_when_the_service_is_blocked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run_status(tmp_path, capsys, healthy(now=NOW - timedelta(minutes=3)), as_json=False)
    assert code == 1
    assert "STOPPED OR BLOCKED: status written 3 min ago" in out


def test_command_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run_status(tmp_path, capsys, healthy(), as_json=True)
    document = json.loads(out)
    assert code == 0
    assert (document["service"], document["problems"]) == ("running", [])
    assert document["state"]["tunnels"][0]["name"] == "wd0c0rootr0c0"
