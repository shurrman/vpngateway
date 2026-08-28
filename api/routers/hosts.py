"""LAN host discovery and runtime access-control endpoints."""

import asyncio

from fastapi import APIRouter

from models.common import error, ok
from models.hosts import HostAccessRequest
from services import hosts as host_service

router = APIRouter(prefix="/hosts", tags=["hosts"])


@router.get("")
async def list_hosts():
    try:
        hosts = await asyncio.to_thread(host_service.list_hosts)
    except host_service.HostAccessError as exc:
        return error(f"Host discovery failed: {exc}")
    return ok({"hosts": [host.model_dump() for host in hosts]})


@router.put("/{ip}/access")
async def update_host_access(ip: str, req: HostAccessRequest):
    try:
        host = await asyncio.to_thread(host_service.set_host_access, ip, req.enabled)
    except host_service.HostAccessError as exc:
        return error(f"Host access update failed: {exc}")
    return ok(host.model_dump())
