"""System status and resources endpoints."""

from fastapi import APIRouter

from config import LAN_INTERFACE, VPN_INTERFACE, XRAY_TUN_INTERFACE
from models.common import ok
from services import system_commands as sys_cmd

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def dashboard_status():
    """Aggregated dashboard — VPN, services, ipset, resources in one call."""
    vpn = await sys_cmd.get_interface_info(VPN_INTERFACE)
    xray_tun = await sys_cmd.get_interface_info(XRAY_TUN_INTERFACE)
    lan = await sys_cmd.get_interface_info(LAN_INTERFACE)
    services = await sys_cmd.get_all_services()
    ipset = await sys_cmd.get_ipset_info()
    resources = await sys_cmd.get_system_resources()
    domains_count = await sys_cmd.get_domains_count()
    connectivity = await sys_cmd.check_internet()
    external_choice = sys_cmd.get_external_tunnel_choice()
    external_iface = sys_cmd.get_external_tunnel_interface()
    external_up = (
        (external_choice == "amnezia" and vpn.up)
        or (external_choice == "xray" and xray_tun.up)
    )
    # Public exit IP / country (cached 10 min so dashboard polls don't
    # hammer ip-api.com). Skip lookup when selected external tunnel is down.
    exit_ip = await sys_cmd.get_exit_ip_info() if external_up else {
        "ip": None, "country": None, "country_code": None,
        "probes": [], "fetched_at": 0, "error": "external VPN down",
    }

    return ok({
        "vpn": vpn.model_dump(),
        "xray_tun": xray_tun.model_dump(),
        "external_tunnel": {
            "type": external_choice,
            "interface": external_iface,
            "up": external_up,
        },
        "lan": lan.model_dump(),
        "services": {s.name: s.active for s in services},
        "domains_count": domains_count,
        "ipset_entries": ipset.entries,
        "resources": resources.model_dump(),
        "connectivity": connectivity,
        "exit_ip": exit_ip,
    })


@router.post("/exit-ip/refresh")
async def refresh_exit_ip():
    """Force re-lookup of the public exit IP and country (bypass cache)."""
    vpn = await sys_cmd.get_interface_info(VPN_INTERFACE)
    xray_tun = await sys_cmd.get_interface_info(XRAY_TUN_INTERFACE)
    external_choice = sys_cmd.get_external_tunnel_choice()
    external_up = (
        (external_choice == "amnezia" and vpn.up)
        or (external_choice == "xray" and xray_tun.up)
    )
    if not external_up:
        return ok({
            "ip": None, "country": None, "country_code": None,
            "probes": [], "fetched_at": 0, "error": "external VPN down",
        })
    info = await sys_cmd.get_exit_ip_info(force=True)
    return ok(info)


@router.get("/interfaces")
async def interfaces():
    vpn = await sys_cmd.get_interface_info(VPN_INTERFACE)
    xray_tun = await sys_cmd.get_interface_info(XRAY_TUN_INTERFACE)
    lan = await sys_cmd.get_interface_info(LAN_INTERFACE)
    return ok({
        "vpn": vpn.model_dump(),
        "xray_tun": xray_tun.model_dump(),
        "lan": lan.model_dump(),
    })


@router.get("/resources")
async def resources():
    res = await sys_cmd.get_system_resources()
    return ok(res.model_dump())
