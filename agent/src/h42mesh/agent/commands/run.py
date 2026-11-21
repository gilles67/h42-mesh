"""h42-mesh-agent run: main process, launched by h42-mesh-agent.service.

It launches one instance per connection (ip vrf exec), restarts them, polls
the configuration and has the public addresses discovered. Applying the
configuration (WireGuard, FRR, keepalived) comes later.
"""

import asyncio
import contextlib
import logging
import signal
from pathlib import Path

import typer

from h42mesh.agent import system
from h42mesh.agent.agent_loop import Agent
from h42mesh.agent.commands import load_or_exit
from h42mesh.agent.config import AgentConfig, config_path
from h42mesh.agent.ipc.hub import WorkerHub
from h42mesh.agent.signing import SigningKeyError, TokenSigner, key_from_pem
from h42mesh.agent.state import StateError, StateStore
from h42mesh.agent.supervisor import InstanceSupervisor, worker_command

EXIT_FAILED = 1
logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def load_signer(config: AgentConfig, store: StateStore) -> TokenSigner:
    identity = store.load_identity()
    pem = store.load_agent_key()
    if identity is None or pem is None:
        raise StateError(f"not enrolled (no identity or key in {store.state_dir})")
    return TokenSigner(key_from_pem(pem), identity.router_id, config.jwt_audience)


async def main_process(
    config: AgentConfig, config_file: Path, store: StateStore, signer: TokenSigner
) -> None:
    hub = WorkerHub({c.uid for c in config.connections})
    agent = Agent(config=config, store=store, signer=signer, hub=hub)
    hub.on_connect = agent.on_instance_connected
    socket = system.socket_path()
    server = await system.start_unix_server(socket, hub.handle_connection)
    supervisors = [
        InstanceSupervisor(c, worker_command(c, config_file, socket), system.vrf_exists)
        for c in config.connections
    ]
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(sig, main_task.cancel)  # type: ignore[union-attr]
    try:
        await asyncio.gather(
            *(s.run() for s in supervisors), agent.config_loop(), agent.discovery_loop()
        )
    finally:
        for supervisor in supervisors:
            supervisor.stop()
        server.close()


def run(path: Path | None) -> int:
    config = load_or_exit(path)
    configure_logging()
    store = StateStore(Path(str(config.state_dir)))
    try:
        signer = load_signer(config, store)
    except (StateError, SigningKeyError) as exc:
        typer.echo(f"run: {exc}; enroll first (h42-mesh-agent enroll)", err=True)
        return EXIT_FAILED
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(main_process(config, config_path(path), store, signer))
    return 0
