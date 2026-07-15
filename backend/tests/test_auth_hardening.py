"""Auth hardening tests (AUTH_AUDIT_AND_PLAN.md §8A/§15): issuer validation,
email-only confirmation (phone-autoconfirm bypass closed), and aal2 step-up
for privileged actions."""

from __future__ import annotations

import uuid

import pytest

from app.config import settings

from .conftest import auth, mint_jwt, q_one, set_tier

pytestmark = pytest.mark.needs_db


async def test_wrong_issuer_is_401(client, tenant):
    owner = tenant["users"]["owner"]
    if not settings.supabase_jwt_issuer:
        pytest.skip("SUPABASE_JWT_ISSUER not configured")
    bad = mint_jwt(owner, "x@bt.local", iss="http://evil.example/auth/v1")
    r = await client.get("/v1/credits", headers=auth(bad, tenant["org"]))
    assert r.status_code == 401
    assert "issuer" in r.json()["error"]["message"].lower()
    good = mint_jwt(owner, "x@bt.local")           # conftest stamps the real iss
    r = await client.get("/v1/credits", headers=auth(good, tenant["org"]))
    assert r.status_code == 200


async def test_phone_only_confirmation_is_not_enough(client, tenant):
    """W2: a phone-autoconfirmed account (email unconfirmed) must NOT pass
    the analysis gate — email confirmation is the only accepted proof."""
    uid = tenant["users"]["unconfirmed"]
    q_one("update auth.users set phone_confirmed_at = now() "
          "where id = %s returning id", (uid,))
    tok = mint_jwt(uid, f"unconfirmed-{tenant['tag']}@bt.local")
    r = await client.post("/v1/submissions",
                          json={"kind": "text", "content": "hi"},
                          headers=auth(tok, tenant["org"]))
    assert r.status_code == 403
    assert "email" in r.json()["error"]["message"].lower()


def _enroll_totp(user_id: str) -> None:
    q_one("insert into auth.mfa_factors "
          "  (id, user_id, friendly_name, factor_type, status, created_at, updated_at) "
          "values (gen_random_uuid(), %s, 'test-authenticator', 'totp', "
          "        'verified', now(), now()) returning id", (user_id,))


async def test_step_up_required_for_enrolled_users(client, tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "pro")                                  # api_access for key mint
    email = f"owner-{tenant['tag']}@bt.local"

    # Without MFA enrolled: aal1 session may perform privileged actions
    # (optional-MFA policy), e.g. mint an API key.
    r = await client.post("/v1/api-keys",
                          json={"name": "pre-mfa"},
                          headers=auth(mint_jwt(owner, email), org))
    assert r.status_code == 201

    _enroll_totp(owner)
    # authn cache holds the pre-enrollment snapshot for 60 s — flush it.
    from app import redis_client
    try:
        await redis_client.client().delete(f"authn:{owner}")
    except Exception:
        pass

    # Enrolled + aal1 → privileged actions demand a step-up...
    aal1 = mint_jwt(owner, email, aal="aal1")
    r = await client.post("/v1/api-keys", json={"name": "post-mfa"},
                          headers=auth(aal1, org))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "step_up_required"
    r = await client.patch("/v1/orgs/members",
                           json={"user_id": tenant["users"]["viewer"],
                                 "role": "reviewer"},
                           headers=auth(aal1, org))
    assert r.status_code == 403

    # ...but an MFA-challenged session (aal2) passes.
    aal2 = mint_jwt(owner, email, aal="aal2")
    r = await client.post("/v1/api-keys", json={"name": "post-mfa"},
                          headers=auth(aal2, org))
    assert r.status_code == 201
    # and non-privileged routes never demand step-up
    r = await client.get("/v1/credits", headers=auth(aal1, org))
    assert r.status_code == 200
