"""Systemd service management endpoints."""

from fastapi import APIRouter, Query

from config import ALLOWED_SERVICES
from models.common import ok, error
from services import system_commands as sys_cmd

router = APIRouter(prefix="/services", tags=["services"])


@router.get("")
async def list_services():
    services = await sys_cmd.get_all_services()
    return ok({"services": [s.model_dump() for s in services]})


@router.get("/{name}")
async def get_service(name: str):
    if name not in ALLOWED_SERVICES:
        return error(f"Service {name} not in whitelist")
    svc = await sys_cmd.get_service_status(name)
    return ok(svc.model_dump())


@router.post("/{name}/start")
async def start_service(name: str):
    if name not in ALLOWED_SERVICES:
        return error(f"Service {name} not in whitelist")
    log = await sys_cmd.service_action(name, "start")
    svc = await sys_cmd.get_service_status(name)
    return ok(svc.model_dump(), log=log)


@router.post("/{name}/stop")
async def stop_service(name: str):
    if name not in ALLOWED_SERVICES:
        return error(f"Service {name} not in whitelist")
    log = await sys_cmd.service_action(name, "stop")
    svc = await sys_cmd.get_service_status(name)
    return ok(svc.model_dump(), log=log)


@router.post("/{name}/restart")
async def restart_service(name: str):
    if name not in ALLOWED_SERVICES:
        return error(f"Service {name} not in whitelist")
    log = await sys_cmd.service_action(name, "restart")
    svc = await sys_cmd.get_service_status(name)
    return ok(svc.model_dump(), log=log)


@router.get("/{name}/logs")
async def service_logs(name: str, lines: int = Query(50, ge=1, le=1000)):
    if name not in ALLOWED_SERVICES:
        return error(f"Service {name} not in whitelist")
    log = await sys_cmd.get_service_logs(name, lines)
    return ok({"logs": log})
