"""Supabase JWT verification — local HS256, no network hop (D9, §13.1).

Checks: signature (SUPABASE_JWT_SECRET), exp, aud='authenticated', and iss
(exact match against SUPABASE_JWT_ISSUER — rejects tokens minted by another
GoTrue environment sharing the secret). nbf is honoured when present. The
email-confirmed gate is enforced against auth.users in the org-context
resolution (deps.py) — the DB decides, the claim is only a hint.

The deployed stack signs with legacy HS256 (verified against GoTrue
v2.189.0). If the stack ever moves to asymmetric keys, swap this module to
the stack's JWKS endpoint with kid-based rotation; nothing above this layer
changes.
"""

from __future__ import annotations

import jwt as pyjwt
import structlog

from ..errors import ApiError

logger = structlog.get_logger("app.auth.jwt")

_warned_no_issuer = False


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


def verify_supabase_jwt(token: str, secret: str, issuer: str = "") -> JwtClaims:
    global _warned_no_issuer
    if not secret:
        raise ApiError(500, "internal", "JWT verification is not configured.")
    if not issuer and not _warned_no_issuer:
        logger.warning("jwt.issuer_check_disabled - set SUPABASE_JWT_ISSUER "
                       "(dev only; required in prod)")
        _warned_no_issuer = True
    try:
        claims = pyjwt.decode(
            token, secret, algorithms=["HS256"], audience="authenticated",
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
