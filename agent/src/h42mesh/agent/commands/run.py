"""h42-mesh-agent run: main loop, launched by h42-mesh-agent.service."""

from pathlib import Path

from h42mesh.agent.commands import load_or_exit, not_implemented


def run(path: Path | None) -> int:
    load_or_exit(path)
    # Non-zero on purpose: systemd must not believe the service is working.
    return not_implemented("run")
