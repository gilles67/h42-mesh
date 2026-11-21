"""Applying the routing of the main process: FRR configuration and sysctls.

FRR is reloaded only when its configuration changed (or when the previous
reload failed); a sysctl is written only when its value differs. Every access
to the system goes through ``SystemAccess``, replaced in the tests.
"""

import asyncio
import contextlib
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from h42mesh.agent.config import AgentConfig
from h42mesh.agent.messages import RouterConfig
from h42mesh.agent.routing import frr, sysctl
from h42mesh.agent.state import atomic_write
from h42mesh.agent.tunnels import netlink
from h42mesh.agent.tunnels.plan import TunnelPlan, router_ports

logger = logging.getLogger(__name__)

FRR_CONF = Path("/etc/frr/frr.conf")
FRR_RELOAD = Path("/usr/lib/frr/frr-reload.py")
FRR_CONF_MODE = 0o640  # owner and group frr


class RoutingError(Exception):
    pass


class SystemAccess(Protocol):
    def read(self, path: Path) -> str | None: ...

    def write(self, path: Path, text: str) -> None: ...

    def write_frr_config(self, path: Path, text: str) -> None: ...

    def reload_frr(self, path: Path) -> None: ...

    def links(self) -> list[str]: ...


class LinuxSystem:
    """/proc/sys, /etc/frr and frr-reload.py (FRR's own tool)."""

    def read(self, path: Path) -> str | None:
        try:
            return path.read_text()
        except FileNotFoundError:
            return None

    def write(self, path: Path, text: str) -> None:
        path.write_text(text)

    def write_frr_config(self, path: Path, text: str) -> None:
        atomic_write(path, text.encode(), FRR_CONF_MODE)
        with contextlib.suppress(LookupError, OSError):  # no frr user: keep root
            shutil.chown(path, "frr", "frr")

    def reload_frr(self, path: Path) -> None:
        result = subprocess.run(  # noqa: S603 (fixed program and path)
            [str(FRR_RELOAD), "--reload", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RoutingError(f"frr-reload failed: {result.stderr.strip()[-500:]}")

    def links(self) -> list[str]:
        return netlink.link_names()


class RoutingApplier:
    def __init__(self, system: SystemAccess | None = None, frr_conf: Path = FRR_CONF) -> None:
        self.system: SystemAccess = system or LinuxSystem()
        self.frr_conf = frr_conf
        self.reload_failed = False

    async def apply(self, config: RouterConfig, agent: AgentConfig, plan: TunnelPlan) -> None:
        await asyncio.to_thread(self.apply_now, config, agent, plan)

    def apply_now(self, config: RouterConfig, agent: AgentConfig, plan: TunnelPlan) -> None:
        links = self.system.links()
        self._sysctls(config, agent, links)
        self._frr(frr.render(frr.build_model(config, agent, plan, links)))

    def _frr(self, text: str) -> bool:
        """True if FRR was reloaded."""
        if self.system.read(self.frr_conf) == text and not self.reload_failed:
            return False
        self.system.write_frr_config(self.frr_conf, text)
        try:
            self.system.reload_frr(self.frr_conf)
        except (RoutingError, OSError) as exc:
            self.reload_failed = True  # tried again at the next pass
            logger.error("FRR not reloaded: %s", exc)
            return False
        self.reload_failed = False
        logger.info("FRR configuration changed and reloaded")
        return True

    def _sysctls(self, config: RouterConfig, agent: AgentConfig, links: list[str]) -> None:
        current = self.system.read(sysctl.RESERVED_PORTS) or ""
        wanted = sysctl.reserved_ports(
            current, agent.mesh_number, router_ports(agent.mesh_number, config.router.number)
        )
        if not sysctl.same_ports(current, wanted):
            self._write(sysctl.RESERVED_PORTS, wanted)
        tunnels = [n for n in links if frr.TUNNEL_NAME.match(n)]
        for name in tunnels:
            path = sysctl.rp_filter_path(name)
            value = self.system.read(path)
            if value is not None and value.strip() != sysctl.LOOSE_RP_FILTER:
                self._write(path, sysctl.LOOSE_RP_FILTER)

    def _write(self, path: Path, value: str) -> None:
        try:
            self.system.write(path, value)
        except OSError as exc:
            logger.error("%s: %s", path, exc)
        else:
            logger.info("%s = %s", path, value)
