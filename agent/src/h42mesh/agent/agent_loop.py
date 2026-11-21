"""Main process logic: talking to the controller through the connection instances.

- each request gets a fresh JWT and goes through the best connected instance
  (active connections by priority, then backup ones), the next one on failure;
- the configuration is polled with If-None-Match; a valid new one is stored;
- each instance discovers the public addresses of its own connection;
- the tunnels: keys and ports kept in state_dir and reported to the
  controller, wanted tunnels sent to the instance of each connection (which
  applies them with the tunnel backend);
- observation: states of the tunnels and of the BGP sessions, the BGP table;
  written to status.json for ``status`` and reported to the controller.
"""

import asyncio
import json
import logging
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from h42mesh.agent import system
from h42mesh.agent.config import AgentConfig, ConnectionSettings
from h42mesh.agent.ipc.channel import WorkerUnavailableError
from h42mesh.agent.ipc.hub import WorkerHub
from h42mesh.agent.ipc.protocol import (
    HttpCall,
    HttpResult,
    TunnelsApplied,
    TunnelsApply,
    TunnelStatuses,
    TunnelStatusQuery,
    b64,
)
from h42mesh.agent.messages import (
    API_PREFIX,
    AddressFamily,
    BgpRoutesReport,
    ErrorResponse,
    PublicAddressReport,
    PublicAddressResult,
    Request,
    RouterConfig,
    TunnelKeysReport,
    TunnelStatusesReport,
)
from h42mesh.agent.observe import ControllerContact, build_status, route_context, tunnel_reports
from h42mesh.agent.routing.apply import RoutingApplier
from h42mesh.agent.routing.bgp import FrrReader, VtyshError
from h42mesh.agent.selection import connection_order
from h42mesh.agent.signing import TokenSigner
from h42mesh.agent.state import StateError, StateStore, StoredConfig, TunnelState
from h42mesh.agent.status_file import AgentStatus, write_status
from h42mesh.agent.tunnels.backend import TunnelStatus
from h42mesh.agent.tunnels.plan import TunnelPlan, plan_tunnels

logger = logging.getLogger(__name__)

CONFIG_INTERVAL = 30.0
CONFIG_JITTER = 5.0
DISCOVERY_INTERVAL = 600.0
OBSERVE_INTERVAL = 30.0
REPORT_REFRESH = 600.0  # a report unchanged is sent again after this delay


class ControllerUnreachableError(Exception):
    """No connected instance could reach a controller."""


class ControllerError(Exception):
    """The controller answered with an error."""

    def __init__(self, status: int, code: str | None, message: str) -> None:
        super().__init__(f"HTTP {status} {code or ''}: {message}".strip())
        self.status = status
        self.code = code


class ConfigRejectedError(Exception):
    """A configuration was received but is not valid: the stored one stays."""


def controller_error(result: HttpResult) -> ControllerError:
    try:
        error = ErrorResponse.model_validate_json(result.body)
    except ValidationError:
        return ControllerError(result.status, None, result.body[:200].decode(errors="replace"))
    return ControllerError(result.status, error.code, error.message)


def strip_etag(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().removeprefix("W/").strip('"')


@dataclass
class Agent:
    config: AgentConfig
    store: StateStore
    signer: TokenSigner
    hub: WorkerHub
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    routing: RoutingApplier | None = None  # FRR and sysctls; None in most tests
    frr: FrrReader | None = None  # reading FRR (vtysh); None in most tests
    status_file: Path | None = None  # where status.json is written; None: not written
    vrf_exists: Callable[[str], bool] = system.vrf_exists
    monotonic: Callable[[], float] = time.monotonic
    contact: ControllerContact = field(default_factory=ControllerContact)
    last_plan: TunnelPlan | None = field(default=None, init=False)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _sent: dict[str, tuple[str, float]] = field(default_factory=dict, init=False, repr=False)
    _tunnels_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    # --- requests ------------------------------------------------------------

    def _stored_router_config(self) -> RouterConfig | None:
        try:
            stored = self.store.load_config()
        except StateError as exc:
            logger.warning("%s", exc)
            return None
        return stored.config if stored is not None else None

    def candidates(self) -> list[UUID]:
        order = connection_order(list(self.config.connections), self._stored_router_config())
        return [uid for uid in order if self.hub.get(uid) is not None]

    async def call(
        self,
        method: str,
        path: str,
        body: Request | None = None,
        *,
        headers: dict[str, str] | None = None,
        via: UUID | None = None,
        family: AddressFamily | None = None,
    ) -> HttpResult:
        """Send a request to the controller; ``via`` forces one connection."""
        order = [via] if via is not None else self.candidates()
        errors: list[str] = []
        for uid in order:
            link = self.hub.get(uid)
            if link is None:
                errors.append(f"{uid}: instance not connected")
                continue
            call = HttpCall(
                id=0,
                method=method,
                path=API_PREFIX + path,
                headers={
                    "Authorization": self.signer.authorization(),  # fresh jti per attempt
                    "Accept": "application/json",
                    **({"Content-Type": "application/json"} if body is not None else {}),
                    **(headers or {}),
                },
                body_b64=b64(body.model_dump_json().encode()) if body is not None else None,
                family=family,
            )
            try:
                result = await link.call(call)
            except WorkerUnavailableError as exc:
                errors.append(str(exc))
                continue
            self.contact.succeeded(self.now(), result.controller, uid)
            return result
        message = "; ".join(errors) or "no connection instance connected"
        self.contact.failed(self.now(), message)
        raise ControllerUnreachableError(message)

    # --- configuration -------------------------------------------------------

    async def refresh_config(self) -> bool:
        """Poll the configuration; True if a new one was stored."""
        try:
            current = self.store.load_config()
        except StateError as exc:
            logger.warning("%s: fetching the configuration again", exc)
            current = None
        headers = {"If-None-Match": f'"{current.fingerprint}"'} if current else {}
        result = await self.call("GET", "/agent/config", headers=headers)
        if result.status == 304:
            return False
        if result.status != 200:
            raise controller_error(result)
        try:
            config = RouterConfig.model_validate_json(result.body)
        except ValidationError as exc:
            raise ConfigRejectedError(f"invalid configuration received: {exc}") from exc
        etag = strip_etag(result.headers.get("etag"))
        if etag != config.fingerprint:
            raise ConfigRejectedError(f"ETag {etag!r} differs from the fingerprint")
        if current is not None and current.fingerprint == config.fingerprint:
            return False
        self.store.save_config(
            StoredConfig(
                fingerprint=config.fingerprint,
                received_at=self.now(),
                controller=result.controller,
                config=config,
            )
        )
        logger.info("new configuration %s from %s", config.fingerprint[:12], result.controller)
        return True

    # --- public addresses ----------------------------------------------------

    async def discover_addresses(self, settings: ConnectionSettings) -> list[PublicAddressResult]:
        """One request per family, through the connection itself."""
        found: list[PublicAddressResult] = []
        for family, forced in (
            (AddressFamily.IPV4, settings.force_ipv4),
            (AddressFamily.IPV6, settings.force_ipv6),
        ):
            body = PublicAddressReport(
                connection_id=settings.uid,
                family=family,
                forced_address=str(forced) if forced is not None else None,
            )
            try:
                result = await self.call(
                    "POST", "/agent/public-address", body, via=settings.uid, family=family
                )
            except ControllerUnreachableError as exc:
                logger.info("connection %s, %s: %s", settings.uid, family, exc)
                continue
            if result.status != 200:
                logger.warning(
                    "connection %s, %s: %s", settings.uid, family, controller_error(result)
                )
                continue
            address = PublicAddressResult.model_validate_json(result.body)
            logger.info("connection %s: public %s %s", settings.uid, family, address.address)
            found.append(address)
        return found

    async def on_instance_connected(self, uid: UUID) -> None:
        """A (re)started instance has no tunnel: give it its tunnels first."""
        settings = next((c for c in self.config.connections if c.uid == uid), None)
        if settings is not None:
            await self.apply_tunnels(only=uid)
            await self.discover_addresses(settings)

    # --- tunnels -------------------------------------------------------------

    def _tunnel_states(self) -> dict[UUID, TunnelState]:
        states = {}
        for tunnel_id in self.store.tunnel_ids():
            try:
                state = self.store.load_tunnel(tunnel_id)
            except StateError as exc:
                logger.error("%s: a new key will be generated", exc)
                continue
            if state is not None:
                states[tunnel_id] = state
        return states

    async def apply_tunnels(self, only: UUID | None = None) -> TunnelPlan | None:
        """Keys and ports, report to the controller, then the tunnels of each
        connected instance (or of ``only``). Runs with the stored configuration:
        the tunnels are applied even if the controller cannot be reached."""
        async with self._tunnels_lock:
            stored = self.store.load_config()
            if stored is None:
                return None
            plan = plan_tunnels(stored.config, self.config, self._tunnel_states())
            self.last_plan = plan
            for tunnel_id in plan.changed:
                self.store.save_tunnel(plan.states[tunnel_id])
            for tunnel_id, reason in plan.pending.items():
                logger.info("tunnel %s waits: %s", tunnel_id, reason)
            await self._report_tunnel_keys(plan)
            for settings in self.config.connections:
                if only is None or settings.uid == only:
                    await self._send_tunnels(settings.uid, plan)
            # The interfaces of a removed tunnel need no key to be deleted.
            for tunnel_id in plan.obsolete:
                self.store.delete_tunnel(tunnel_id)
            return plan

    async def _report_tunnel_keys(self, plan: TunnelPlan) -> None:
        if not plan.to_report:
            return
        try:
            result = await self.call(
                "POST", "/agent/tunnels", TunnelKeysReport(tunnels=plan.to_report)
            )
        except ControllerUnreachableError as exc:
            logger.info("tunnel keys not reported: %s", exc)
            return
        if result.status // 100 != 2:
            logger.warning("tunnel keys not reported: %s", controller_error(result))
            return
        for report in plan.to_report:
            state = plan.states[report.tunnel_id].model_copy(
                update={"public_key_registered": True, "port_registered": True}
            )
            plan.states[report.tunnel_id] = state
            self.store.save_tunnel(state)
        logger.info("%d tunnel keys reported", len(plan.to_report))

    async def _send_tunnels(self, uid: UUID, plan: TunnelPlan) -> None:
        link = self.hub.get(uid)
        number = plan.numbers.get(uid)
        if link is None:
            return
        if number is None:
            logger.warning("connection %s is not a connection of the router", uid)
            return
        message = TunnelsApply(id=0, connection_number=number, tunnels=plan.specs.get(uid, []))
        try:
            applied = await link.request(message, TunnelsApplied)
        except WorkerUnavailableError as exc:
            logger.warning("tunnels of %s not applied: %s", uid, exc)
            return
        for name, error in applied.errors.items():
            logger.error("tunnel %s: %s", name, error)

    async def apply_routing(self, plan: TunnelPlan) -> None:
        """FRR configuration (reloaded only if it changed) and sysctls."""
        stored = self.store.load_config()
        if self.routing is None or stored is None:
            return
        try:
            await self.routing.apply(stored.config, self.config, plan)
        except (OSError, ValueError) as exc:
            logger.error("routing not applied: %s", exc)

    # --- observation and reports ---------------------------------------------

    async def observe(self) -> AgentStatus:
        """Gather the state, report it to the controller, write status.json."""
        errors: list[str] = []
        try:
            stored = self.store.load_config()
        except StateError as exc:
            errors.append(str(exc))
            stored = None
        statuses = await self.tunnel_statuses()
        bgp_states: dict[str, str] = {}
        if self.frr is not None:
            try:
                bgp_states = await asyncio.to_thread(self.frr.neighbor_states)
            except VtyshError as exc:
                errors.append(f"FRR: {exc}")
        if stored is not None:
            config = stored.config
            reports = tunnel_reports(config, self.last_plan, statuses, bgp_states)
            await self._report(
                "PUT", "/agent/tunnel-status", TunnelStatusesReport(tunnels=reports), errors
            )
            if self.frr is not None:
                context = route_context(config, self.last_plan, self.config)
                try:
                    routes = await asyncio.to_thread(self.frr.routes, context)
                except VtyshError as exc:
                    errors.append(f"FRR: {exc}")
                else:
                    await self._report(
                        "PUT", "/agent/bgp-routes", BgpRoutesReport(routes=routes), errors
                    )
        status = build_status(
            now=self.now(),
            started_at=self.started_at,
            pid=os.getpid(),
            router_id=self.signer.router_id,
            stored=stored,
            agent=self.config,
            plan=self.last_plan,
            connected=self.hub.connected(),
            vrf_exists=self.vrf_exists,
            statuses=statuses,
            bgp_states=bgp_states,
            contact=self.contact,
            errors=errors,
        )
        if self.status_file is not None:
            write_status(status, self.status_file)
        return status

    async def _report(self, method: str, path: str, body: Request, errors: list[str]) -> None:
        """Send ``body`` if it changed since the last report (or after REPORT_REFRESH)."""
        payload = json.dumps(body.model_dump(mode="json"), sort_keys=True)
        previous = self._sent.get(path)
        fresh = previous is not None and self.monotonic() - previous[1] < REPORT_REFRESH
        if previous is not None and previous[0] == payload and fresh:
            return
        try:
            result = await self.call(method, path, body)
        except ControllerUnreachableError as exc:
            errors.append(f"{path}: {exc}")
            return
        if result.status // 100 != 2:
            errors.append(f"{path}: {controller_error(result)}")
            return
        self._sent[path] = (payload, self.monotonic())

    async def tunnel_statuses(self) -> dict[UUID, list[TunnelStatus]]:
        """States of the tunnels, from each connected instance."""
        found: dict[UUID, list[TunnelStatus]] = {}
        for settings in self.config.connections:
            link = self.hub.get(settings.uid)
            if link is None:
                continue
            try:
                answer = await link.request(TunnelStatusQuery(id=0), TunnelStatuses)
            except WorkerUnavailableError as exc:
                logger.warning("tunnel states of %s: %s", settings.uid, exc)
                continue
            found[settings.uid] = answer.tunnels
        return found

    # --- loops ---------------------------------------------------------------

    async def config_loop(self) -> None:
        while True:
            try:
                await self.refresh_config()
            except (ControllerUnreachableError, ControllerError, ConfigRejectedError) as exc:
                logger.warning("configuration not refreshed: %s", exc)
            try:
                plan = await self.apply_tunnels()  # idempotent: nothing done if nothing changed
                if plan is not None:
                    await self.apply_routing(plan)
            except StateError as exc:
                logger.error("tunnels not applied: %s", exc)
            await asyncio.sleep(CONFIG_INTERVAL + random.uniform(-CONFIG_JITTER, CONFIG_JITTER))  # noqa: S311

    async def observe_loop(self) -> None:
        while True:
            try:
                await self.observe()
            except (OSError, StateError) as exc:
                logger.error("observation failed: %s", exc)
            await asyncio.sleep(OBSERVE_INTERVAL)

    async def discovery_loop(self) -> None:
        while True:
            await asyncio.sleep(DISCOVERY_INTERVAL)
            for settings in self.config.connections:
                if self.hub.get(settings.uid) is not None:
                    await self.discover_addresses(settings)
