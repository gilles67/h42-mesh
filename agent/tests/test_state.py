"""Local storage: atomic writes, permissions, configuration rotation, tunnels."""

import base64
import os
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from h42mesh.agent.state import StateError, StateStore, StoredConfig, TunnelState, atomic_write
from test_messages import router_config

POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
KEY = base64.b64encode(bytes(range(32))).decode()


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def stored(fingerprint: str = "f1") -> StoredConfig:
    return StoredConfig(
        fingerprint=fingerprint,
        received_at=datetime(2026, 11, 21, 10, 0, tzinfo=UTC),
        controller="https://vps1.example.org",
        config=router_config(fingerprint=fingerprint),
    )


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state")


# --- atomic write ------------------------------------------------------------


def test_atomic_write_creates_and_replaces(tmp_path: Path) -> None:
    path = tmp_path / "file.json"
    atomic_write(path, b"one")
    atomic_write(path, b"two")
    assert path.read_bytes() == b"two"
    assert [p.name for p in tmp_path.iterdir()] == ["file.json"]  # no temporary left


def test_failed_write_keeps_the_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "file.json"
    atomic_write(path, b"old")

    def broken_fsync(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OSError, match="disk full"):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["file.json"]


def test_failed_rename_keeps_the_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "file.json"
    atomic_write(path, b"old")

    def broken_replace(source: Any, target: Any) -> None:
        raise OSError("crash")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="crash"):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["file.json"]


@POSIX
def test_files_are_0600_even_with_a_permissive_umask(tmp_path: Path) -> None:
    previous = os.umask(0o000)
    try:
        path = tmp_path / "secret"
        atomic_write(path, b"x")
        assert mode(path) == 0o600
    finally:
        os.umask(previous)


@POSIX
def test_directories_are_0700(store: StateStore) -> None:
    store.ensure_directories()
    assert mode(store.state_dir) == 0o700
    assert mode(store.tunnels_dir) == 0o700


@POSIX
def test_every_state_file_is_0600(store: StateStore) -> None:
    store.save_config(stored("f1"))
    store.save_config(stored("f2"))
    store.save_tunnel(TunnelState(tunnel_id=uuid.uuid4(), private_key=KEY))
    store.save_agent_key(b"-----BEGIN PRIVATE KEY-----\n")
    files = [p for p in store.state_dir.rglob("*") if p.is_file()]
    assert len(files) == 4
    assert all(mode(p) == 0o600 for p in files)


# --- configuration -----------------------------------------------------------


def test_no_configuration_yet(store: StateStore) -> None:
    assert store.load_config() is None
    assert store.load_previous_config() is None


def test_configuration_round_trip(store: StateStore) -> None:
    saved = stored("f1")
    store.save_config(saved)
    assert store.load_config() == saved
    assert store.load_previous_config() is None


def test_previous_configuration_is_kept(store: StateStore) -> None:
    store.save_config(stored("f1"))
    store.save_config(stored("f2"))
    store.save_config(stored("f3"))
    current, previous = store.load_config(), store.load_previous_config()
    assert current is not None and previous is not None
    assert (current.fingerprint, previous.fingerprint) == ("f3", "f2")


def test_corrupted_configuration(store: StateStore) -> None:
    store.ensure_directories()
    store.config_path.write_text("{not json")
    with pytest.raises(StateError, match="invalid content"):
        store.load_config()


def test_stored_configuration_refuses_unknown_fields(store: StateStore) -> None:
    store.save_config(stored())
    text = store.config_path.read_text().replace('"fingerprint"', '"extra": 1, "fingerprint"', 1)
    store.config_path.write_text(text)
    with pytest.raises(StateError):
        store.load_config()


# --- tunnels -----------------------------------------------------------------


def test_tunnel_state_round_trip(store: StateStore) -> None:
    tunnel_id = uuid.uuid4()
    assert store.load_tunnel(tunnel_id) is None
    tunnel = TunnelState(tunnel_id=tunnel_id, private_key=KEY, port=42001)
    store.save_tunnel(tunnel)
    assert store.load_tunnel(tunnel_id) == tunnel
    assert store.tunnel_path(tunnel_id).name == f"{tunnel_id}.json"

    tunnel.public_key_registered = tunnel.port_registered = True
    store.save_tunnel(tunnel)
    loaded = store.load_tunnel(tunnel_id)
    assert loaded is not None and loaded.port_registered


def test_tunnel_listing_and_deletion(store: StateStore) -> None:
    ids = sorted(uuid.uuid4() for _ in range(3))
    for tunnel_id in ids:
        store.save_tunnel(TunnelState(tunnel_id=tunnel_id, private_key=KEY))
    (store.tunnels_dir / "notes.json").write_text("{}")  # foreign file ignored
    (store.tunnels_dir / f".{ids[0]}.json.abc.tmp").write_text("{}")  # temporary ignored
    assert store.tunnel_ids() == ids

    store.delete_tunnel(ids[1])
    store.delete_tunnel(ids[1])  # already gone: no error
    assert store.tunnel_ids() == [ids[0], ids[2]]


def test_tunnel_file_holding_another_tunnel(store: StateStore) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    store.save_tunnel(TunnelState(tunnel_id=a, private_key=KEY))
    store.tunnel_path(a).rename(store.tunnel_path(b))
    with pytest.raises(StateError, match="holds tunnel"):
        store.load_tunnel(b)


@pytest.mark.parametrize(
    "overrides",
    [{"private_key": "short"}, {"port": 0}, {"port": 70000}, {"comment": "x"}],
)
def test_tunnel_state_validation(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TunnelState.model_validate({"tunnel_id": str(uuid.uuid4()), "private_key": KEY} | overrides)


def test_no_tunnels_directory_yet(store: StateStore) -> None:
    assert store.tunnel_ids() == []
    store.delete_tunnel(uuid.uuid4())


# --- agent key ---------------------------------------------------------------


def test_agent_key_round_trip(store: StateStore) -> None:
    assert store.load_agent_key() is None
    store.save_agent_key(b"secret key bytes")
    assert store.load_agent_key() == b"secret key bytes"
    assert store.agent_key_path.name == "agent.key"
