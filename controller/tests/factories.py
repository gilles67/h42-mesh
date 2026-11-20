"""Helpers that create valid entities for tests, with overridable fields."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from h42mesh.controller.models import (
    Connection,
    ConnectionRole,
    DirectMode,
    EnrollmentToken,
    Mesh,
    Router,
    Site,
    Tunnel,
    User,
)
from h42mesh.controller.models.validators import ipv6_network_for

# Shape of an encrypted secret; real encryption comes in a later task.
FAKE_SECRET: dict[str, Any] = {
    "v": 1,
    "kdf": "scrypt",
    "salt": "c2FsdA==",
    "nonce": "bm9uY2U=",
    "ciphertext": "Y2lwaGVy",
}


def key(n: int) -> str:
    """A valid base64 32-byte public key, distinct for each n."""
    return base64.b64encode(bytes([n]) * 32).decode()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def in_hours(hours: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


async def make_user(username: str = "alice", **kwargs: Any) -> User:
    return await User.create(username=username, password_hash="$argon2id$fake", **kwargs)


async def make_mesh(name: str = "home42", **kwargs: Any) -> Mesh:
    return await Mesh.create(name=name, **kwargs)


async def make_site(
    mesh: Mesh, nickname: str = "pari", asn: int = 4_200_000_001, **kwargs: Any
) -> Site:
    kwargs.setdefault("name", f"Site {nickname}")
    return await Site.create(mesh=mesh, nickname=nickname, asn=asn, **kwargs)


async def make_router(site: Site, number: int = 0, **kwargs: Any) -> Router:
    kwargs.setdefault("name", f"r{number}")
    return await Router.create(site=site, number=number, **kwargs)


async def make_connection(router: Router, number: int = 0, **kwargs: Any) -> Connection:
    kwargs.setdefault("name", f"c{number}")
    kwargs.setdefault("role", ConnectionRole.ACTIVE)
    return await Connection.create(router=router, number=number, **kwargs)


async def make_tunnel(
    mesh: Mesh,
    connection_a: Connection,
    connection_b: Connection,
    ipv4_network: str = "169.254.12.34/31",
    **kwargs: Any,
) -> Tunnel:
    kwargs.setdefault("ipv6_network", ipv6_network_for(ipv4_network))
    kwargs.setdefault("preshared_key", FAKE_SECRET)
    return await Tunnel.create(
        mesh=mesh,
        connection_a=connection_a,
        connection_b=connection_b,
        ipv4_network=ipv4_network,
        **kwargs,
    )


async def make_token(router: Router, created_by: User, name: str = "token") -> EnrollmentToken:
    return await EnrollmentToken.create(
        router=router, token_hash=digest(name), expires_at=in_hours(4), created_by=created_by
    )


class Topology:
    """One mesh with two sites, one router each, one direct connection each."""

    mesh: Mesh
    site_a: Site
    site_b: Site
    router_a: Router
    router_b: Router
    conn_a: Connection
    conn_b: Connection

    @classmethod
    async def create(cls, mesh_name: str = "home42") -> "Topology":
        topo = cls()
        topo.mesh = await make_mesh(mesh_name)
        topo.site_a = await make_site(topo.mesh, "root", 4_200_000_000)
        topo.site_b = await make_site(topo.mesh, "pari", 4_200_000_001)
        topo.router_a = await make_router(topo.site_a)
        topo.router_b = await make_router(topo.site_b)
        topo.conn_a = await make_connection(topo.router_a, direct=DirectMode.BOTH)
        topo.conn_b = await make_connection(topo.router_b)
        return topo
