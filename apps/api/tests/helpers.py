import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    roles: list[str],
    *,
    sub: str = "user-1",
    key: Any = PRIVATE,
) -> str:
    claims = {
        "sub": sub,
        "preferred_username": "tester",
        "iss": settings.keycloak_issuer,
        "aud": settings.keycloak_audience,
        "exp": int(time.time()) + 300,
        "realm_access": {"roles": roles},
    }
    return jwt.encode(claims, key, algorithm="RS256")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
