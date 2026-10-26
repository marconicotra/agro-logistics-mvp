"""Verify Supabase Auth access tokens through the project's public JWKS."""

from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings


class SupabaseAuthConfigurationError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


def verify_supabase_access_token(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.supabase_url:
        raise SupabaseAuthConfigurationError("Supabase Auth is not configured")
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    jwks_url = f"{issuer}/.well-known/jwks.json"
    signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        audience=settings.supabase_jwt_audience,
        issuer=issuer,
        options={"require": ["exp", "iat", "sub", "aud", "iss"]},
    )
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise jwt.InvalidTokenError("Subject claim is required")
    return claims
