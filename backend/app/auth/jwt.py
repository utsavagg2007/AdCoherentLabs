"""Supabase JWT verification (D9, §13.1).

TWO signing schemes are accepted, selected by the token's own `alg` header:

  * **Asymmetric (ES256/RS256)** — Supabase Cloud signs USER SESSION tokens with
    a project keypair and publishes the public half at
    ``<project>/auth/v1/.well-known/jwks.json``. Verified against that JWKS,
    cached in-process with kid-based rotation.
  * **HS256** — self-hosted GoTrue, the legacy static anon/service_role keys,
    and internally minted dev tokens, verified against SUPABASE_JWT_SECRET.

Selecting the key SOURCE from the alg family is what makes this safe: an
attacker downgrading ES256 -> HS256 is verified against the shared secret they
do not have, never against the public key (the classic confusion attack).
Anything outside the two allowlists below is rejected outright.

Claim checks are identical on both paths: signature, exp, aud='authenticated',
and iss (exact match against SUPABASE_JWT_ISSUER — rejects tokens minted by
another Supabase environment). nbf is honoured when present. The
email-confirmed gate is enforced against auth.users in the org-context
resolution (deps.py) — the DB decides, the claim is only a hint.
"""

from __future__ import annotations

import jwt as pyjwt
import structlog

from ..errors import ApiError

logger = structlog.get_logger("app.auth.jwt")

_warned_no_issuer = False
_jwks_client: pyjwt.PyJWKClient | None = None
_jwks_client_url: str = ""

# Explicit allowlists — never echo an attacker-supplied alg straight into decode().
_ASYMMETRIC = {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512"}
_SYMMETRIC = {"HS256"}


class JwtClaims(dict):
    @property
    def user_id(self) -> str:
        return self["sub"]

    @property
    def email(self) -> str | None:
        return self.get("email")

    @property
    def aal(self) -> str:
        """GoTrue authenticator assurance level: aal1 (password/magic link)
        or aal2 (MFA-challenged session)."""
        return str(self.get("aal") or "aal1")


def _jwks(url: str) -> pyjwt.PyJWKClient:
    """One cached client per process. Keys are fetched on first use and on an
    unknown kid, so steady state costs no network hop; the short timeout keeps
    a JWKS outage from stalling the event loop."""
    global _jwks_client, _jwks_client_url
    if _jwks_client is None or _jwks_client_url != url:
        _jwks_client = pyjwt.PyJWKClient(
            url, cache_keys=True, max_cached_keys=8, lifespan=600, timeout=5)
        _jwks_client_url = url
    return _jwks_client


def verify_supabase_jwt(token: str, secret: str, issuer: str = "",
                        jwks_url: str = "") -> JwtClaims:
    global _warned_no_issuer
    if not issuer and not _warned_no_issuer:
        logger.warning("jwt.issuer_check_disabled - set SUPABASE_JWT_ISSUER "
                       "(dev only; required in prod)")
        _warned_no_issuer = True

    try:
        alg = str(pyjwt.get_unverified_header(token).get("alg") or "")
    except pyjwt.PyJWTError:
        raise ApiError(401, "unauthenticated", "Invalid token.")

    if alg in _ASYMMETRIC:
        if not jwks_url:
            raise ApiError(500, "internal",
                           "JWT verification is not configured for asymmetric "
                           "tokens (set SUPABASE_URL or SUPABASE_JWKS_URL).")
        try:
            key = _jwks(jwks_url).get_signing_key_from_jwt(token).key
        except pyjwt.PyJWTError:
            raise ApiError(401, "unauthenticated", "Invalid token.")
        except Exception as exc:                      # network / JWKS unreachable
            logger.error("jwt.jwks_unavailable", url=jwks_url, error=str(exc))
            raise ApiError(503, "unavailable",
                           "Unable to verify the session right now.")
        algorithms = [alg]
    elif alg in _SYMMETRIC:
        if not secret:
            raise ApiError(500, "internal", "JWT verification is not configured.")
        key = secret
        algorithms = ["HS256"]
    else:
        raise ApiError(401, "unauthenticated", "Invalid token.")

    try:
        claims = pyjwt.decode(
            token, key, algorithms=algorithms, audience="authenticated",
            issuer=issuer or None,
            options={"require": ["exp", "sub", "aud"],
                     "verify_iss": bool(issuer)},
        )
    except pyjwt.ExpiredSignatureError:
        raise ApiError(401, "unauthenticated", "Token has expired.")
    except pyjwt.InvalidAudienceError:
        raise ApiError(401, "unauthenticated", "Token audience is not 'authenticated'.")
    except pyjwt.InvalidIssuerError:
        raise ApiError(401, "unauthenticated", "Token issuer is not this environment.")
    except pyjwt.PyJWTError:
        raise ApiError(401, "unauthenticated", "Invalid token.")
    return JwtClaims(claims)
