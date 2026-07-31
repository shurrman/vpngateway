"""OpenVPN client management endpoints.

OpenVPN runs side-by-side with the AmneziaWG split-tunneling layer. It is
NOT used for public-internet routing; its job is to reach private subnets
the OpenVPN server pushes (typically a home LAN like 192.168.60.0/24).

The vpngw-openvpn-run.sh wrapper applies these safety filters so the
server can't accidentally turn this client into a default-gateway:
  --pull-filter ignore "redirect-gateway"
  --pull-filter ignore "route 0.0.0.0"
  --pull-filter ignore "dhcp-option DNS"
"""

from __future__ import annotations

import re

from fastapi import APIRouter

from config import OPENVPN_ACTIVE_FILE, OPENVPN_DIR, OPENVPN_STATE_DIR
from models.common import error, ok
from services import system_commands as sys_cmd

router = APIRouter(prefix="/openvpn", tags=["openvpn"])

OPENVPN_SERVICE = "vpngw-openvpn"

# Same constraint as for AmneziaWG configs — short, path-safe identifier.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _read_active() -> str | None:
    try:
        return OPENVPN_ACTIVE_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _read_state_file(name: str) -> str:
    """Read a single-line file from /run/vpngw-openvpn/, "" if absent."""
    try:
        return (OPENVPN_STATE_DIR / name).read_text().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def _read_pushed_routes() -> list[str]:
    """Return the list of subnets the OpenVPN server pushed at last connect.

    Populated by vpngw-openvpn-up.sh from the route_network_N /
    route_netmask_N env vars openvpn provides on --route-up.
    """
    raw = _read_state_file("pushed-routes")
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _peek_endpoint(conf_path) -> str:
    """Extract the first `remote <host> <port>` line from a .ovpn file."""
    try:
        for line in conf_path.read_text().splitlines():
            s = line.strip()
            if s.startswith("remote ") and not s.startswith("remote-"):
                parts = s.split()
                if len(parts) >= 3:
                    return f"{parts[1]}:{parts[2]}"
                if len(parts) == 2:
                    return parts[1]
    except OSError:
        pass
    return ""


@router.get("/status")
async def openvpn_status():
    """Aggregated OpenVPN state for the dashboard tile.

    Shape:
      {
        "service":  {name, active, state, ...},
        "interface": {name=tun0, up, ip_address, tx_bytes, rx_bytes},
        "active":    "<config name>" | null,
        "endpoint":  "host:port" or "",
        "local_ip":  pushed tunnel IP (e.g. 10.8.0.6),
        "remote_ip": pushed peer IP,
        "pushed_routes": ["192.168.60.0/24", ...],
      }
    """
    svc = await sys_cmd.get_service_status(OPENVPN_SERVICE)
    # tun0 may or may not exist; get_interface_info returns up=False if missing.
    iface = await sys_cmd.get_interface_info("tun0")

    active = _read_active()
    endpoint = ""
    if active:
        path = OPENVPN_DIR / f"{active}.ovpn"
        if path.is_file():
            endpoint = _peek_endpoint(path)

    return ok({
        "service": svc.model_dump(),
        "interface": iface.model_dump(),
        "active": active,
        "endpoint": endpoint,
        "local_ip": _read_state_file("local-ip"),
        "remote_ip": _read_state_file("remote-ip"),
        "pushed_routes": _read_pushed_routes(),
    })


@router.get("/configs")
async def list_configs():
    """List available .ovpn files in /opt/vpngateway/config/openvpn/."""
    active = _read_active()
    items = []
    if OPENVPN_DIR.is_dir():
        for path in sorted(OPENVPN_DIR.glob("*.ovpn")):
            name = path.stem
            items.append({
                "name": name,
                "endpoint": _peek_endpoint(path),
                "active": name == active,
            })
    return ok({"configs": items, "active": active})


@router.post("/enable")
async def enable():
    """Start vpngw-openvpn (also enables it on boot)."""
    if not _read_active():
        return error("no active OpenVPN config selected")
    enable_log = await sys_cmd.run_systemctl("enable", OPENVPN_SERVICE)
    start_log = await sys_cmd.service_action(OPENVPN_SERVICE, "start")
    svc = await sys_cmd.get_service_status(OPENVPN_SERVICE)
    return ok({"service": svc.model_dump()},
              log=(enable_log + "\n" + start_log).strip())


@router.post("/disable")
async def disable():
    """Stop and disable vpngw-openvpn."""
    stop_log = await sys_cmd.service_action(OPENVPN_SERVICE, "stop")
    disable_log = await sys_cmd.run_systemctl("disable", OPENVPN_SERVICE)
    svc = await sys_cmd.get_service_status(OPENVPN_SERVICE)
    return ok({"service": svc.model_dump()},
              log=(stop_log + "\n" + disable_log).strip())


@router.post("/configs/{name}/activate")
async def activate(name: str):
    """Set <name> as the active OpenVPN config and (if service is running)
    restart it so the new config takes effect immediately."""
    if not _NAME_RE.match(name):
        return error(f"invalid config name: {name!r}")
    src = OPENVPN_DIR / f"{name}.ovpn"
    if not src.is_file():
        return error(f"config not found: {name}")

    OPENVPN_DIR.mkdir(parents=True, exist_ok=True)
    OPENVPN_ACTIVE_FILE.write_text(name)

    # If the service is currently running, restart so the new .active is
    # picked up by the wrapper script. Otherwise just record the choice.
    svc = await sys_cmd.get_service_status(OPENVPN_SERVICE)
    log = ""
    if svc.active:
        log = await sys_cmd.service_action(OPENVPN_SERVICE, "restart")
    svc = await sys_cmd.get_service_status(OPENVPN_SERVICE)
    return ok({"active": name, "service": svc.model_dump()}, log=log)
