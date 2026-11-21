"""Local storage of the agent in state_dir (/var/lib/h42-mesh by default).

| File                   | Content                                              |
| ---------------------- | ---------------------------------------------------- |
| config.json            | last valid configuration, fingerprint, date, source  |
| config.previous.json   | the one before, to roll back                         |
| tunnels/<uid>.json     | X25519 private key and port of each tunnel           |
| agent.key              | Ed25519 private key of the agent                     |

Every file holds secrets: written atomically (temporary file in the same
directory, fsync, rename, fsync of the directory) with mode 0600, in
directories with mode 0700. A power cut leaves the previous version intact.
"""

import contextlib
import os
import secrets
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from h42mesh.agent.messages import Key, Port, RouterConfig

FILE_MODE = 0o600
DIR_MODE = 0o700
CONFIG_FILE = "config.json"
PREVIOUS_CONFIG_FILE = "config.previous.json"
TUNNELS_DIR = "tunnels"
AGENT_KEY_FILE = "agent.key"


class StateError(Exception):
    """A state file exists but cannot be read or is invalid."""


class StoredConfig(BaseModel):
    """A configuration received from the controller, as stored locally."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    received_at: datetime
    controller: str  # URL of the controller that provided it
    config: RouterConfig


class TunnelState(BaseModel):
    """Local state of a tunnel: kept as long as the tunnel exists."""

    model_config = ConfigDict(extra="forbid")

    tunnel_id: UUID
    private_key: Key  # X25519, base64; never leaves the router
    port: Port | None = None
    # Whether the controller has recorded our public key and port.
    public_key_registered: bool = False
    port_registered: bool = False


def _fsync_directory(directory: Path) -> None:
    """Make the rename durable (POSIX only: Windows cannot open a directory)."""
    if os.name != "posix":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, mode: int = FILE_MODE) -> None:
    """Replace ``path`` by ``data`` atomically, with permissions ``mode``."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)  # the umask may have removed bits we want
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    _fsync_directory(path.parent)


class StateStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    # --- paths ---------------------------------------------------------------

    @property
    def config_path(self) -> Path:
        return self.state_dir / CONFIG_FILE

    @property
    def previous_config_path(self) -> Path:
        return self.state_dir / PREVIOUS_CONFIG_FILE

    @property
    def tunnels_dir(self) -> Path:
        return self.state_dir / TUNNELS_DIR

    @property
    def agent_key_path(self) -> Path:
        return self.state_dir / AGENT_KEY_FILE

    def tunnel_path(self, tunnel_id: UUID) -> Path:
        # A UUID cannot contain a path separator: no traversal possible.
        return self.tunnels_dir / f"{UUID(str(tunnel_id))}.json"

    def ensure_directories(self) -> None:
        for directory in (self.state_dir, self.tunnels_dir):
            directory.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
            os.chmod(directory, DIR_MODE)

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _read[M: BaseModel](path: Path, model: type[M]) -> M | None:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise StateError(f"{path}: cannot be read: {exc}") from exc
        try:
            return model.model_validate_json(text)
        except ValidationError as exc:
            raise StateError(f"{path}: invalid content: {exc}") from exc

    def _write(self, path: Path, document: BaseModel) -> None:
        self.ensure_directories()
        atomic_write(path, document.model_dump_json(indent=2).encode("utf-8"))

    # --- configuration -------------------------------------------------------

    def load_config(self) -> StoredConfig | None:
        """Last stored configuration; None if there is none yet."""
        return self._read(self.config_path, StoredConfig)

    def load_previous_config(self) -> StoredConfig | None:
        return self._read(self.previous_config_path, StoredConfig)

    def save_config(self, stored: StoredConfig) -> None:
        """Store a new configuration; the current one becomes the previous one.

        Two atomic writes: at any time both files are complete.
        """
        self.ensure_directories()
        try:
            current = self.config_path.read_bytes()
        except FileNotFoundError:
            current = None
        if current is not None:
            atomic_write(self.previous_config_path, current)
        self._write(self.config_path, stored)

    # --- tunnels -------------------------------------------------------------

    def load_tunnel(self, tunnel_id: UUID) -> TunnelState | None:
        state = self._read(self.tunnel_path(tunnel_id), TunnelState)
        if state is not None and state.tunnel_id != tunnel_id:
            raise StateError(f"{self.tunnel_path(tunnel_id)}: holds tunnel {state.tunnel_id}")
        return state

    def save_tunnel(self, state: TunnelState) -> None:
        self._write(self.tunnel_path(state.tunnel_id), state)

    def delete_tunnel(self, tunnel_id: UUID) -> None:
        """Only with the tunnel itself; the private key is gone for good."""
        with contextlib.suppress(FileNotFoundError):
            self.tunnel_path(tunnel_id).unlink()
        if self.tunnels_dir.exists():
            _fsync_directory(self.tunnels_dir)

    def tunnel_ids(self) -> list[UUID]:
        """Tunnels with a stored state (temporary and foreign files ignored)."""
        if not self.tunnels_dir.exists():
            return []
        ids = []
        for path in self.tunnels_dir.glob("*.json"):
            try:
                ids.append(UUID(path.stem))
            except ValueError:
                continue
        return sorted(ids)

    # --- agent signing key ---------------------------------------------------

    def load_agent_key(self) -> bytes | None:
        """Ed25519 private key of the agent (encoding chosen by the enrollment)."""
        try:
            return self.agent_key_path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StateError(f"{self.agent_key_path}: cannot be read: {exc}") from exc

    def save_agent_key(self, key: bytes) -> None:
        self.ensure_directories()
        atomic_write(self.agent_key_path, key)
