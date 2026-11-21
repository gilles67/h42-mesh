"""h42-mesh-agent connection-worker: instance of one connection (hidden command)."""

import asyncio
from pathlib import Path
from uuid import UUID

from h42mesh.agent import system
from h42mesh.agent.commands import load_or_exit
from h42mesh.agent.commands.run import configure_logging
from h42mesh.agent.worker import run_worker


def connection_worker(path: Path | None, uid: UUID, socket: Path | None) -> int:
    config = load_or_exit(path)
    configure_logging()
    return asyncio.run(run_worker(config, uid, socket or system.socket_path()))
