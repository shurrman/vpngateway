"""DNS configuration and query endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from config import DNSMASQ_CONF
from models.common import ok, error
from services import system_commands as sys_cmd
from services.script_runner import run_command

router = APIRouter(prefix="/dns", tags=["dns"])


class DnsQueryRequest(BaseModel):
    domain: str
    type: str = "A"


@router.get("/config")
async def dns_config():
    """Parse and return current dnsmasq configuration."""
    try:
        content = DNSMASQ_CONF.read_text()
    except FileNotFoundError:
        return error("dnsmasq.conf not found")

    upstream = []
    local_zones = []
    cache_size = 0
    listen = []

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("server=") and "/" not in line:
            upstream.append(line.split("=", 1)[1])
        elif line.startswith("server=/"):
            parts = line.split("/")
            if len(parts) >= 3:
                local_zones.append({"zone": parts[1], "server": parts[2]})
        elif line.startswith("cache-size="):
            cache_size = int(line.split("=", 1)[1])
        elif line.startswith("listen-address="):
            listen.append(line.split("=", 1)[1])

    return ok({
        "upstream_servers": upstream,
        "local_zones": local_zones,
        "cache_size": cache_size,
        "listen_addresses": listen,
    })


@router.post("/query")
async def dns_query(req: DnsQueryRequest):
    ips = await sys_cmd.dig_query(req.domain, req.type)
    return ok({
        "domain": req.domain,
        "type": req.type,
        "records": ips,
    })


@router.post("/flush")
async def flush_dns():
    result = await run_command("systemctl", "restart", "dnsmasq")
    if not result.success:
        return error("Failed to restart dnsmasq", data={"log": result.output})
    return ok(log="dnsmasq restarted, DNS cache flushed")
