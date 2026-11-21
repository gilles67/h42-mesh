"""Security of agent enrollment and JWT authentication."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_helpers import (
    AUDIENCE,
    Agent,
    call,
    create_token,
    enroll,
    enrolled_agent,
    unsigned_token,
)
from api_helpers import API, World, use_token


@pytest.fixture
def agent(world: World) -> Agent:
    return enrolled_agent(world)


def assert_invalid(response: object) -> None:
    assert response.status_code == 401, response.text  # type: ignore[attr-defined]
    assert response.json()["code"] == "invalid_agent_token"  # type: ignore[attr-defined]


# --- enrollment --------------------------------------------------------------


def test_enrollment(world: World) -> None:
    agent = enrolled_agent(world)
    assert agent.router_id == world.ids["router"]
    router = world.as_("manager").get(f"{API}/routers/{agent.router_id}").json()
    assert router["enrolled"] is True
    assert router["enrolled_at"] is not None
    assert "signing_public_key" not in router

    response = call(world.client, agent.token())
    assert response.status_code == 200
    assert response.json() == {
        "router_id": world.ids["router"],
        "mesh_id": world.ids["mesh"],
        "site_nickname": "root",
        "router_number": 0,
    }
    assert world.as_("manager").get(f"{API}/routers/{agent.router_id}").json()["last_seen_at"]


def test_token_is_single_use(world: World) -> None:
    token = create_token(world)
    assert enroll(world.client, token, Agent("").public_key).status_code == 200
    response = enroll(world.client, token, Agent("").public_key)
    assert (response.status_code, response.json()["code"]) == (401, "invalid_enrollment_token")


def test_expired_token(world: World) -> None:
    token = create_token(world)
    world.env.clock.advance(hours=4, seconds=1)
    response = enroll(world.client, token, Agent("").public_key)
    assert (response.status_code, response.json()["code"]) == (401, "invalid_enrollment_token")


def test_token_still_valid_before_expiry(world: World) -> None:
    token = create_token(world)
    world.env.clock.advance(hours=3, minutes=59)
    assert enroll(world.client, token, Agent("").public_key).status_code == 200


def test_unknown_token(world: World) -> None:
    response = enroll(world.client, "made-up-token", Agent("").public_key)
    assert (response.status_code, response.json()["code"]) == (401, "invalid_enrollment_token")


def test_new_token_replaces_unused_one(world: World) -> None:
    first = create_token(world)
    second = create_token(world)
    assert first != second
    assert enroll(world.client, first, Agent("").public_key).status_code == 401
    assert enroll(world.client, second, Agent("").public_key).status_code == 200


def test_token_is_bound_to_its_router(world: World) -> None:
    other = (
        world.as_("manager")
        .post(f"{API}/sites/{world.ids['site']}/routers", json={"number": 1, "name": "vps2"})
        .json()
    )
    agent = Agent("")
    response = enroll(world.client, create_token(world, other["id"]), agent.public_key)
    assert response.json()["router_id"] == other["id"]


@pytest.mark.parametrize(
    "key", ["short", "A" * 44, "not base64 at all, 44 chars long!!!!!!!!!!", ""]
)
def test_enrollment_rejects_malformed_key(world: World, key: str) -> None:
    response = enroll(world.client, create_token(world), key)
    assert response.status_code == 422


def test_signing_key_cannot_be_shared(world: World, agent: Agent) -> None:
    other = (
        world.as_("manager")
        .post(f"{API}/sites/{world.ids['site']}/routers", json={"number": 1, "name": "vps2"})
        .json()
    )
    response = enroll(world.client, create_token(world, other["id"]), agent.public_key)
    assert (response.status_code, response.json()["code"]) == (409, "signing_key_in_use")


def test_enrollment_token_shown_once_and_not_listed(world: World) -> None:
    response = world.as_("manager").post(f"{API}/routers/{world.ids['router']}/enrollment-tokens")
    body = response.json()
    assert set(body) == {"token", "expires_at"}
    assert len(body["token"]) >= 40
    router = world.as_("manager").get(f"{API}/routers/{world.ids['router']}").json()
    assert body["token"] not in str(router)


# --- algorithm ---------------------------------------------------------------


def test_alg_none_refused(world: World, agent: Agent) -> None:
    assert_invalid(call(world.client, unsigned_token(agent.claims())))


def test_hs256_with_public_key_as_secret_refused(world: World, agent: Agent) -> None:
    """Key confusion: HMAC keyed with the (public) Ed25519 key."""
    token = jwt.encode(agent.claims(), agent.public_key, algorithm="HS256")
    assert_invalid(call(world.client, token))


def test_es256_refused(world: World, agent: Agent) -> None:
    token = jwt.encode(agent.claims(), ec.generate_private_key(ec.SECP256R1()), algorithm="ES256")
    assert_invalid(call(world.client, token))


def test_rs256_refused(world: World, agent: Agent) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert_invalid(call(world.client, jwt.encode(agent.claims(), key, algorithm="RS256")))


def test_signed_by_another_key(world: World, agent: Agent) -> None:
    assert_invalid(call(world.client, agent.token(key=Ed25519PrivateKey.generate())))


def test_tampered_payload(world: World, agent: Agent) -> None:
    header, _, signature = agent.token().split(".")
    other = Agent(agent.router_id).token(aud="someone-else").split(".")[1]
    assert_invalid(call(world.client, f"{header}.{other}.{signature}"))


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c", "Bearer"])
def test_malformed(world: World, token: str) -> None:
    assert_invalid(call(world.client, token))


def test_missing_or_wrong_scheme(world: World, agent: Agent) -> None:
    assert_invalid(call(world.client, None))
    use_token(world.client, None)
    response = world.client.get(
        f"{API}/agent/me", headers={"Authorization": f"Basic {agent.token()}"}
    )
    assert_invalid(response)


def test_gui_session_is_not_an_agent_credential(world: World) -> None:
    client = world.as_("admin")
    response = client.get(f"{API}/agent/me")
    assert_invalid(response)


# --- claims ------------------------------------------------------------------


def test_expired(world: World, agent: Agent) -> None:
    assert_invalid(call(world.client, agent.token(exp=int(time.time()) - 60)))


def test_clock_skew_tolerated(world: World, agent: Agent) -> None:
    response = call(world.client, agent.token(exp=int(time.time()) - 10))
    assert response.status_code == 200


def test_exp_too_far(world: World, agent: Agent) -> None:
    assert_invalid(call(world.client, agent.token(exp=int(time.time()) + 3600)))
    assert call(world.client, agent.token(exp=int(time.time()) + 290)).status_code == 200


@pytest.mark.parametrize("audience", ["someone-else", ["other"], ""])
def test_wrong_audience(world: World, agent: Agent, audience: object) -> None:
    assert_invalid(call(world.client, agent.token(aud=audience)))


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "exp", "jti"])
def test_required_claims(world: World, agent: Agent, claim: str) -> None:
    assert_invalid(call(world.client, agent.token(**{claim: None})))


def test_sub_must_match_iss(world: World, agent: Agent) -> None:
    assert_invalid(call(world.client, agent.token(sub=str(uuid.uuid4()))))


def test_unknown_or_invalid_issuer(world: World, agent: Agent) -> None:
    stranger = str(uuid.uuid4())
    assert_invalid(call(world.client, agent.token(iss=stranger, sub=stranger)))
    assert_invalid(call(world.client, agent.token(iss="vps1", sub="vps1")))


def test_issuer_of_another_router(world: World, agent: Agent) -> None:
    """A valid key cannot speak for another (enrolled) router."""
    other = (
        world.as_("manager")
        .post(f"{API}/sites/{world.ids['site']}/routers", json={"number": 1, "name": "vps2"})
        .json()
    )
    enroll(world.client, create_token(world, other["id"]), Agent("").public_key)
    assert_invalid(call(world.client, agent.token(iss=other["id"], sub=other["id"])))


def test_not_enrolled_router(world: World) -> None:
    other = (
        world.as_("manager")
        .post(f"{API}/sites/{world.ids['site']}/routers", json={"number": 1, "name": "vps2"})
        .json()
    )
    agent = Agent(other["id"])
    assert_invalid(call(world.client, agent.token()))


@pytest.mark.parametrize("jti", ["", "x" * 129, 42])
def test_invalid_jti(world: World, agent: Agent, jti: object) -> None:
    assert_invalid(call(world.client, agent.token(jti=jti)))


# --- replay ------------------------------------------------------------------


def test_replay_refused(world: World, agent: Agent) -> None:
    token = agent.token()
    assert call(world.client, token).status_code == 200
    assert_invalid(call(world.client, token))
    assert_invalid(
        call(
            world.client,
            agent.token(jti=jwt.decode(token, options={"verify_signature": False})["jti"]),
        )
    )


def test_same_jti_for_another_router(world: World, agent: Agent) -> None:
    other_router = (
        world.as_("manager")
        .post(f"{API}/sites/{world.ids['site']}/routers", json={"number": 1, "name": "vps2"})
        .json()
    )
    other = Agent(other_router["id"])
    enroll(world.client, create_token(world, other.router_id), other.public_key)
    assert call(world.client, agent.token(jti="shared")).status_code == 200
    assert call(world.client, other.token(jti="shared")).status_code == 200


def test_used_jti_purged_after_expiry(world: World, agent: Agent) -> None:
    from h42mesh.controller.auth import agent_jwt

    assert call(world.client, agent.token(jti="old")).status_code == 200
    world.env.clock.advance(minutes=5)
    agent_jwt._last_purge = 0.0  # force the next request to purge
    assert call(world.client, agent.token()).status_code == 200
    # "old" expired long ago (exp = +60 s): it was purged, so it may be used again.
    assert call(world.client, agent.token(jti="old")).status_code == 200


# --- revocation and renewal --------------------------------------------------


def test_revoked_router_refused_at_next_request(world: World, agent: Agent) -> None:
    assert call(world.client, agent.token()).status_code == 200
    response = world.as_("manager").post(f"{API}/routers/{agent.router_id}/revoke")
    assert response.json()["signing_key_revoked"] is True

    response = call(world.client, agent.token())
    assert (response.status_code, response.json()["code"]) == (403, "router_revoked")


def test_revocation_not_revealed_without_the_key(world: World, agent: Agent) -> None:
    world.as_("manager").post(f"{API}/routers/{agent.router_id}/revoke")
    assert_invalid(call(world.client, agent.token(key=Ed25519PrivateKey.generate())))


def test_reenrollment_lifts_revocation(world: World, agent: Agent) -> None:
    world.as_("manager").post(f"{API}/routers/{agent.router_id}/revoke")
    new = Agent(agent.router_id)
    assert enroll(world.client, create_token(world), new.public_key).status_code == 200
    assert call(world.client, new.token()).status_code == 200
    assert_invalid(call(world.client, agent.token()))  # the old key is gone
    router = world.as_("manager").get(f"{API}/routers/{agent.router_id}").json()
    assert router["signing_key_revoked"] is False


def renew(world: World, agent: Agent, new_public_key: str) -> object:
    use_token(world.client, None)
    return world.client.put(
        f"{API}/agent/signing-key",
        json={"signing_public_key": new_public_key},
        headers={"Authorization": f"Bearer {agent.token()}"},
    )


def test_key_renewal(world: World, agent: Agent) -> None:
    new = Agent(agent.router_id)
    response = renew(world, agent, new.public_key)
    assert response.status_code == 204  # type: ignore[attr-defined]
    assert call(world.client, new.token()).status_code == 200
    assert_invalid(call(world.client, agent.token()))  # previous key refused at once


def test_renewal_refused_when_revoked(world: World, agent: Agent) -> None:
    world.as_("manager").post(f"{API}/routers/{agent.router_id}/revoke")
    response = renew(world, agent, Agent(agent.router_id).public_key)
    assert response.status_code == 403  # type: ignore[attr-defined]


def test_renewal_needs_a_valid_jwt(world: World, agent: Agent) -> None:
    use_token(world.client, None)
    response = world.client.put(
        f"{API}/agent/signing-key",
        json={"signing_public_key": Agent("").public_key},
        headers={"Authorization": f"Bearer {agent.token(key=Ed25519PrivateKey.generate())}"},
    )
    assert_invalid(response)


def test_renewal_rejects_a_key_in_use(world: World, agent: Agent) -> None:
    other_router = (
        world.as_("manager")
        .post(f"{API}/sites/{world.ids['site']}/routers", json={"number": 1, "name": "vps2"})
        .json()
    )
    other = Agent(other_router["id"])
    enroll(world.client, create_token(world, other.router_id), other.public_key)
    response = renew(world, agent, other.public_key)
    assert response.status_code == 409  # type: ignore[attr-defined]
    assert response.json()["code"] == "signing_key_in_use"  # type: ignore[attr-defined]


def test_audience_is_a_setting(world: World, agent: Agent) -> None:
    assert world.env.settings.agent_jwt_audience == AUDIENCE
