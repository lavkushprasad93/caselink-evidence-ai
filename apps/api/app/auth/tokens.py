from collections.abc import Callable
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import jwks_url, settings

bearer = HTTPBearer(auto_error=False)

KeyResolver = Callable[[str], Any]
_jwks_client: PyJWKClient | None = None


def _resolve_signing_key(token: str) -> Any:
    """Fetch the signing key for this token from Keycloak's JWKS (cached by PyJWKClient)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            jwks_url(),
            lifespan=settings.keycloak_jwks_cache_ttl_seconds,
        )
    return _jwks_client.get_signing_key_from_jwt(token).key


def get_key_resolver() -> KeyResolver:
    """A dependency so tests can supply their own key instead of calling Keycloak."""
    return _resolve_signing_key


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid or missing token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_jwt(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    resolve: Annotated[KeyResolver, Depends(get_key_resolver)],
) -> dict[str, Any]:
    """Validate signature, expiry, issuer and audience. Only RS256 is accepted."""
    if creds is None:
        raise _unauthorized()
    try:
        key = resolve(creds.credentials)
        claims: dict[str, Any] = jwt.decode(
            creds.credentials,
            key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc
    return claims


def try_decode(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    resolve: Annotated[KeyResolver, Depends(get_key_resolver)],
) -> dict[str, Any] | None:
    """Return claims for a valid bearer token, or None for anonymous/invalid requests."""
    try:
        return decode_jwt(creds, resolve)
    except HTTPException as exc:
        if exc.status_code == 401:
            return None
        raise
