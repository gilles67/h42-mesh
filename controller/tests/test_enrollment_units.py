"""Enrollment tokens in the database: only the digest is stored."""

import hashlib

import pytest

from factories import make_mesh, make_router, make_site, make_user
from h42mesh.controller.auth import enrollment
from h42mesh.controller.models import EnrollmentToken
from h42mesh.controller.settings import Settings

pytestmark = pytest.mark.usefixtures("db")


async def test_only_the_digest_is_stored() -> None:
    router = await make_router(await make_site(await make_mesh()))
    user = await make_user()
    token, expires_at = await enrollment.create_token(router, user, Settings())

    (stored,) = await EnrollmentToken.all()
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(stored.__dict__)
    assert stored.expires_at == expires_at
    assert stored.created_by_id == user.id  # type: ignore[attr-defined]
    assert len(token) >= 40  # 32 random bytes


async def test_used_tokens_are_kept_new_ones_replace_unused() -> None:
    router = await make_router(await make_site(await make_mesh()))
    user = await make_user()
    first, _ = await enrollment.create_token(router, user, Settings())
    await enrollment.enroll(first, "A" * 43 + "=")
    await enrollment.create_token(router, user, Settings())
    await enrollment.create_token(router, user, Settings())

    tokens = await EnrollmentToken.filter(router_id=router.id)
    assert len(tokens) == 2  # the used one (history) and the latest
    assert sum(t.used_at is not None for t in tokens) == 1
