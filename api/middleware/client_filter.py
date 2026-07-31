"""Restrict API access to LAN subnets only."""

import ipaddress
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import ALLOWED_SUBNETS

logger = logging.getLogger(__name__)

_networks = [ipaddress.ip_network(s) for s in ALLOWED_SUBNETS]


class ClientFilterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        if client_ip:
            try:
                addr = ipaddress.ip_address(client_ip)
                if not any(addr in net for net in _networks):
                    logger.warning("Blocked request from %s", client_ip)
                    return JSONResponse(
                        status_code=403,
                        content={"status": "error", "error": "Access denied"},
                    )
            except ValueError:
                pass
        return await call_next(request)
