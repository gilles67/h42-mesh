"""Reconciliation of the tunnels of one connection, in its instance.

Compares the wanted tunnels with the existing ones (``backend.list()``) and
only applies the differences: tunnels in excess are deleted, missing ones
created, changed ones updated. A failure on one tunnel does not stop the
others. Depends on the TunnelBackend interface only.
"""

import logging
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any

from h42mesh.agent.tunnels.backend import TunnelBackend, TunnelError, TunnelSpec, TunnelStatus

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class TunnelManager:
    """Keeps the backend in line with the wanted tunnels."""

    def __init__(self, backend: TunnelBackend) -> None:
        self.backend = backend
        self.applied: dict[str, TunnelSpec] = {}  # last spec applied, by name

    async def reconcile(self, wanted: Sequence[TunnelSpec]) -> ReconcileReport:
        report = ReconcileReport()
        by_name: dict[str, TunnelSpec] = {}
        for spec in wanted:
            if spec.name in by_name:
                report.errors[spec.name] = "two wanted tunnels with this name"
            by_name[spec.name] = spec
        for name in report.errors:
            by_name.pop(name, None)

        existing = set(await self.backend.list())
        for name in sorted(existing - set(by_name)):
            await self._do(report, name, self._delete(name), report.deleted)
        for name, spec in sorted(by_name.items()):
            if name in existing and name in self.applied:
                if self.applied[name] != spec:
                    await self._do(report, name, self._update(spec), report.updated)
            else:
                # Missing, or left over by a previous instance (spec unknown).
                await self._do(report, name, self._create(spec, name in existing), report.created)
        return report

    async def statuses(self) -> list[TunnelStatus]:
        found = []
        for name in await self.backend.list():
            status = await self.backend.status(name)
            if status is not None:
                found.append(status)
        return found

    async def close(self) -> None:
        await self.backend.close()
        self.applied.clear()

    # --- steps ---------------------------------------------------------------

    @staticmethod
    async def _do(
        report: ReconcileReport, name: str, step: Coroutine[Any, Any, None], done: list[str]
    ) -> None:
        try:
            await step
        except TunnelError as exc:
            logger.error("%s", exc)
            report.errors[name] = str(exc)
        else:
            done.append(name)

    async def _delete(self, name: str) -> None:
        self.applied.pop(name, None)
        await self.backend.delete(name)

    async def _create(self, spec: TunnelSpec, left_over: bool) -> None:
        self.applied.pop(spec.name, None)
        if left_over:
            await self.backend.delete(spec.name)
        await self.backend.create(spec)
        self.applied[spec.name] = spec

    async def _update(self, spec: TunnelSpec) -> None:
        await self.backend.update(spec)
        self.applied[spec.name] = spec
