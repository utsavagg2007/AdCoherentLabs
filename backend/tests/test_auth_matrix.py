"""Auth/authz matrix (§16): route × principal → expected status.
Cross-org ids return 404 (existence never revealed)."""

from __future__ import annotations

import hashlib
import secrets as pysecrets

import pytest

from .conftest import auth, mint_jwt, q_one, set_tier

pytestmark = pytest.mark.needs_db

TEXT_SUBMISSION = {"kind": "text", "content": "Get 5.99% APR, guaranteed!",
                   "target_jurisdictions": ["US-CA"]}


async def test_anonymous_gets_401(client):
    for path in ("/v1/credits", "/v1/runs", "/v1/submissions", "/v1/orgs/me"):
        r = await client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"
        assert r.json()["error"]["request_id"].startswith("req_")


async def test_bad_tokens_401(client, tenant):
    owner = tenant["users"]["owner"]
    for token in (
            mint_jwt(owner, "x@x", secret="wrong-secret"),
            mint_jwt(owner, "x@x", expired=True),
            mint_jwt(owner, "x@x", aud="not-authenticated")):
        r = await client.get("/v1/credits", headers=auth(token))
        assert r.status_code == 401


async def test_role_ladder_on_reads_and_submit(client, tenant):
    org = tenant["org"]
    for role in ("owner", "admin", "reviewer", "viewer"):
        tok = mint_jwt(tenant["users"][role], f"{role}@bt.local")
        r = await client.get("/v1/credits", headers=auth(tok, org))
        assert r.status_code == 200, (role, r.text)
    # viewer cannot submit; reviewer+ passes the gate (402/202 both mean "past authz")
    viewer = mint_jwt(tenant["users"]["viewer"], "v@bt.local")
    r = await client.post("/v1/submissions", json=TEXT_SUBMISSION,
                          headers=auth(viewer, org))
    assert r.status_code == 403
    unconfirmed = mint_jwt(tenant["users"]["unconfirmed"], "u@bt.local")
    r = await client.post("/v1/submissions", json=TEXT_SUBMISSION,
                          headers=auth(unconfirmed, org))
    assert r.status_code == 403
    assert "email" in r.json()["error"]["message"].lower()


async def test_cross_org_is_404_never_403(client, tenant):
    outsider = mint_jwt(tenant["users"]["outsider"], "o@bt.local")
    # selecting the victim org as an outsider
    r = await client.get("/v1/credits", headers=auth(outsider, tenant["org"]))
    assert r.status_code == 404
    # reading a victim run by id from the outsider's own org context
    sub = q_one("insert into public.submissions (org_id, created_by, title) "
                "values (%s, %s, 'x') returning id::text",
                (tenant["org"], tenant["users"]["owner"]))["id"]
    run = q_one("insert into public.analysis_runs (submission_id, org_id, status) "
                "values (%s, %s, 'complete') returning id::text",
                (sub, tenant["org"]))["id"]
    r = await client.get(f"/v1/runs/{run}",
                         headers=auth(outsider, tenant["other_org"]))
    assert r.status_code == 404


async def test_api_key_auth_scopes_and_revocation(client, tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "pro")   # api_access entitlement
    plaintext = "ack_" + pysecrets.token_hex(24)
    q_one("insert into public.api_keys (org_id, name, key_hash, scopes, created_by) "
          "values (%s, 'matrix', %s, %s, %s) returning id::text",
          (org, hashlib.sha256(plaintext.encode()).hexdigest(),
           ["read"], owner))
    r = await client.get("/v1/credits", headers={"X-API-Key": plaintext})
    assert r.status_code == 200
    r = await client.post("/v1/submissions", json=TEXT_SUBMISSION,
                          headers={"X-API-Key": plaintext})
    assert r.status_code == 403               # read-only key lacks submit scope
    r = await client.get("/v1/credits", headers={"X-API-Key": "ack_" + "0" * 48})
    assert r.status_code == 401               # unknown key
    q_one("update public.api_keys set revoked_at = now() "
          "where org_id = %s returning id", (org,))
    r = await client.get("/v1/credits", headers={"X-API-Key": plaintext})
    assert r.status_code == 401               # revoked


async def test_free_tier_has_no_api_access(client, tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    plaintext = "ack_" + pysecrets.token_hex(24)
    q_one("insert into public.api_keys (org_id, name, key_hash, scopes, created_by) "
          "values (%s, 'free-key', %s, %s, %s) returning id::text",
          (org, hashlib.sha256(plaintext.encode()).hexdigest(),
           ["read", "submit"], owner))
    r = await client.get("/v1/credits", headers={"X-API-Key": plaintext})
    assert r.status_code == 403


async def test_admin_routes_hidden_from_non_staff(client, tenant):
    owner = mint_jwt(tenant["users"]["owner"], f"owner-{tenant['tag']}@bt.local")
    r = await client.get("/v1/admin/queue", headers=auth(owner, tenant["org"]))
    assert r.status_code == 404               # not 403: the route does not exist for them
