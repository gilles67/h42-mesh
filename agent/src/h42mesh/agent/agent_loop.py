"""Main process logic: talking to the controller through the connection instances.

- each request gets a fresh JWT and goes through the best connected instance
  (active connections by priority, then backup ones), the next one on failure;
- the configuration is polled with If-None-Match; a valid new one is stored;
- each instance discovers the public addresses of its own connection.
"""

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError

from h42mesh.agent.config import AgentConfig, ConnectionSettings
from h42mesh.agent.ipc.channel import WorkerUnavailableError
from h42mesh.agent.ipc.hub import WorkerHub
from h42mesh.agent.ipc.protocol import HttpCall, HttpResult, b64
from h42mesh.agent.messages import (
    API_PREFIX,
    AddressFamily,
    ErrorResponse,
    PublicAddressReport,
    PublicAddressResult,
    Request,
    RouterConfig,
)
from h42mesh.agent.selection import connection_order
from h42mesh.agent.signing import TokenSigner
from h42mesh.agent.state import StateError, StateStore, StoredConfig

logger = logging.getLogger(__name__)

CONFIG_INTERVAL = 30.0
CONFIG_JITTER = 5.0
DISCOVERY_INTERVAL = 600.0


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
                return await link.call(call)
            except WorkerUnavailableError as exc:
                errors.append(str(exc))
        raise ControllerUnreachableError("; ".join(errors) or "no connection instance connected")

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
        settings = next((c for c in self.config.connections if c.uid == uid), None)
        if settings is not None:
            await self.discover_addresses(settings)

    # --- loops ---------------------------------------------------------------

    async def config_loop(self) -> None:
        while True:
            try:
                await self.refresh_config()
            except (ControllerUnreachableError, ControllerError, ConfigRejectedError) as exc:
                logger.warning("configuration not refreshed: %s", exc)
            await asyncio.sleep(CONFIG_INTERVAL + random.uniform(-CONFIG_JITTER, CONFIG_JITTER))  # noqa: S311

    async def discovery_loop(self) -> None:
        while True:
            await asyncio.sleep(DISCOVERY_INTERVAL)
            for settings in self.config.connections:
                if self.hub.get(settings.uid) is not None:
                    await self.discover_addresses(settings)
