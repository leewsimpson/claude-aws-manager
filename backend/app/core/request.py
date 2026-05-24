"""Small request helpers shared across API routers."""

import ipaddress

from fastapi import Request


def client_ip(request: Request) -> str | None:
    """Return the client IP if it parses as a valid address (for the ``INET`` column).

    Returns ``None`` for missing or non-IP hosts (e.g. the TestClient's
    ``"testclient"``), so audit inserts never crash on the ``INET`` column.
    """
    if request.client is None:
        return None
    try:
        ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    return request.client.host
