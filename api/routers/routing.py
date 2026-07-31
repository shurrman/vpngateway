"""Routing state and control endpoints."""

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from config import CONFIG_DIR
from models.common import ok, error
from services import system_commands as sys_cmd
from services.script_runner import run_script, run_command

router = APIRouter(prefix="/routing", tags=["routing"])

MODE_FILE = CONFIG_DIR / "mode"
VALID_MODES = {"split", "all-vpn", "all-direct"}


class SetModeRequest(BaseModel):
    mode: str


@router.get("/rules")
async def ip_rules():
    rules = await sys_cmd.get_ip_rules()
    return ok({"rules": [r.model_dump() for r in rules]})


@router.get("/tables")
async def route_tables():
    main_routes = await sys_cmd.get_routes("main")
    table100 = await sys_cmd.get_routes("100")
    return ok({
        "main": [r.model_dump() for r in main_routes],
        "table_100": [r.model_dump() for r in table100],
    })


@router.get("/ipset")
async def ipset_info():
    info = await sys_cmd.get_ipset_info()
    return ok(info.model_dump())


@router.get("/ipset/test/{ip}")
async def ipset_test(ip: str):
    in_set = await sys_cmd.ipset_test(ip)
    return ok({"ip": ip, "in_set": in_set})


@router.get("/mode")
async def get_mode():
    try:
        mode = MODE_FILE.read_text().strip()
    except FileNotFoundError:
        mode = "split"
    return ok({"mode": mode})


@router.post("/mode")
async def set_mode(req: SetModeRequest):
    if req.mode not in VALID_MODES:
        return error(f"Invalid mode: {req.mode}. Valid: {', '.join(sorted(VALID_MODES))}")

    MODE_FILE.write_text(req.mode + "\n")

    # Teardown current routing, then set up new mode
    logs = []
    result = await run_script("teardown-routing")
    logs.append(result.output)

    result = await run_script("setup-routing")
    logs.append(result.output)

    # If the selected external tunnel is up, fix routes for the new mode.
    external_iface = sys_cmd.get_external_tunnel_interface()
    check = await run_command("ip", "link", "show", external_iface) if external_iface else None
    if check and check.success:
        result = await run_script("fix-routes")
        logs.append(result.output)

    return ok({"mode": req.mode}, log="\n".join(logs))


@router.post("/setup")
async def setup_routing():
    result = await run_script("setup-routing")
    if not result.success:
        return error("Setup failed", data={"log": result.output})
    return ok(log=result.output)


@router.post("/teardown")
async def teardown_routing():
    result = await run_script("teardown-routing")
    if not result.success:
        return error("Teardown failed", data={"log": result.output})
    return ok(log=result.output)


@router.post("/fix-routes")
async def fix_routes():
    result = await run_script("fix-routes")
    if not result.success:
        return error("Fix failed", data={"log": result.output})
    return ok(log=result.output)


# Backward-compatible alias
@router.post("/fix-amnezia")
async def fix_amnezia():
    return await fix_routes()
