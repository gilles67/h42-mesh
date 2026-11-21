"""The rest of the agent depends on the TunnelBackend interface only."""

import ast
from pathlib import Path

import h42mesh.agent

SOURCES = Path(h42mesh.agent.__file__).parent
IMPLEMENTATION = "h42mesh.agent.tunnels.wireguard_go"
# The factory of the connection instance chooses the implementation.
ALLOWED = {SOURCES / "worker.py", SOURCES / "tunnels" / "wireguard_go.py"}


def imported_modules(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def test_only_the_factory_imports_wireguard_go() -> None:
    offenders = [
        str(path.relative_to(SOURCES))
        for path in SOURCES.rglob("*.py")
        if path not in ALLOWED and IMPLEMENTATION in imported_modules(path)
    ]
    assert offenders == []


def test_the_factory_does_import_it() -> None:
    assert IMPLEMENTATION in imported_modules(SOURCES / "worker.py")
