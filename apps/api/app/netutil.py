from fastapi import Request


def client_ip(request: Request) -> str | None:
    """Return the direct peer address; do not trust caller-controlled forwarding headers."""
    return request.client.host if request.client else None
