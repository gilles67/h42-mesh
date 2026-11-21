"""h42-mesh-agent enroll: Ed25519 key pair, enrollment with a single-use token."""

from pathlib import Path

from h42mesh.agent.commands import load_if_present, not_implemented


def enroll(path: Path | None, controller: str, token: str) -> int:
    # The configuration file may not exist yet when enrolling.
    load_if_present(path)
    return not_implemented("enroll")
