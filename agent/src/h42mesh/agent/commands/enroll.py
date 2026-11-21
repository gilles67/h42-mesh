"""h42-mesh-agent enroll: Ed25519 key pair, enrollment with a single-use token.

With ``--vrf``, the command runs itself again inside that VRF (the default VRF
has no route to the Internet). A new key pair is generated each time; it is
written only after the controller accepted it, so a failure keeps the old one.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import typer
from pydantic import ValidationError

from h42mesh.agent import system
from h42mesh.agent.commands import EXIT_INVALID_CONFIG, EXIT_OK, load_if_present
from h42mesh.agent.config import AgentConfig
from h42mesh.agent.config.models import DEFAULT_DNS_SERVERS, DEFAULT_STATE_DIR
from h42mesh.agent.messages import (
    API_PREFIX,
    EnrollRequest,
    EnrollResponse,
    ErrorResponse,
)
from h42mesh.agent.net.dns import Resolver
from h42mesh.agent.net.https import ControllerClient, ControllerUnreachableError
from h42mesh.agent.signing import generate_key, key_to_pem, public_key_b64
from h42mesh.agent.state import Identity, StateError, StateStore
from h42mesh.agent.worker import Requester

EXIT_FAILED = 1

ClientFactory = Callable[[str, AgentConfig | None], Requester]


def default_client(controller: str, config: AgentConfig | None) -> Requester:
    import ipaddress

    servers = (
        list(config.dns_servers)
        if config is not None
        else [ipaddress.ip_address(a) for a in DEFAULT_DNS_SERVERS]
    )
    resolver = Resolver(servers, family_available=system.family_available)
    return ControllerClient([controller], resolver)


def enroll(
    path: Path | None,
    controller: str,
    token: str,
    vrf: str | None = None,
    *,
    reexec_argv: Sequence[str] = (),
    client_factory: ClientFactory | None = None,
) -> int:
    # The configuration file may not exist yet when enrolling.
    config = load_if_present(path)

    if vrf is not None and system.in_vrf() != vrf:
        if not system.vrf_exists(vrf):
            typer.echo(f"enroll: VRF {vrf} does not exist", err=True)
            return EXIT_INVALID_CONFIG
        return system.run_in_vrf(vrf, list(reexec_argv))

    if config is not None and controller not in config.controllers:
        typer.echo(
            f"enroll: {controller} is not one of the controllers of the configuration "
            f"({', '.join(config.controllers)})",
            err=True,
        )
        return EXIT_INVALID_CONFIG

    store = StateStore(Path(str(config.state_dir if config else DEFAULT_STATE_DIR)))
    key = generate_key()
    body = EnrollRequest(token=token, signing_public_key=public_key_b64(key))
    try:
        response = (client_factory or default_client)(controller, config).request(
            "POST",
            f"{API_PREFIX}/agent/enroll",
            body=body.model_dump_json().encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    except ControllerUnreachableError as exc:
        typer.echo(f"enroll: controller unreachable: {exc}", err=True)
        return EXIT_FAILED

    if response.status != 200:
        try:
            error = ErrorResponse.model_validate_json(response.body)
            detail = f"{error.code}: {error.message}"
        except ValidationError:
            detail = response.body[:200].decode(errors="replace")
        typer.echo(f"enroll: refused by the controller (HTTP {response.status}) {detail}", err=True)
        return EXIT_FAILED

    try:
        result = EnrollResponse.model_validate_json(response.body)
    except ValidationError as exc:
        typer.echo(f"enroll: unexpected answer: {exc}", err=True)
        return EXIT_FAILED
    try:
        store.save_agent_key(key_to_pem(key))
        store.save_identity(
            Identity(
                router_id=result.router_id, controller=controller, enrolled_at=datetime.now(UTC)
            )
        )
    except (OSError, StateError) as exc:
        typer.echo(f"enroll: cannot store the key in {store.state_dir}: {exc}", err=True)
        return EXIT_FAILED
    typer.echo(f"Enrolled: router {result.router_id} on {controller}")
    return EXIT_OK
