"""Typed wrappers around system commands (ip, iptables, ipset, dig, systemctl)."""

import asyncio
import json
import re
import time

from config import (
    ALLOWED_SERVICES,
    AMNEZIA_INTERFACE,
    EXTERNAL_TUNNEL_FILE,
    IPSET_NAME,
    LAN_INTERFACE,
    XRAY_TUN_INTERFACE,
)
from models.system import (
    InterfaceInfo, ServiceInfo, SystemResources, IpsetInfo, IpRuleInfo, RouteInfo,
)
from services.script_runner import run_command


# In-process cache for the public exit IP / geo lookup.
# GeoIP free tiers have request limits, so we cache for 10 minutes,
# which is plenty since the exit IP only changes when the tunnel
# reconnects to a different DC.
#
# Schema (kept backward-compatible — old frontend reads .ip/.country/.country_code
# of the primary probe; new frontend additionally renders .probes):
#   {
#     "ip": "198.51.100.10",          # primary probe (first non-empty)
#     "country": "Russia",
#     "country_code": "RU",
#     "probes": [
#       {"service": "api.ipify.org", "ip": "...", "country": "...",
#        "country_code": "..."},
#       ...
#     ],
#     "fetched_at": 1778090660.0,
#     "error": None,
#   }
_EXIT_IP_CACHE: dict = {
    "ip": None, "country": None, "country_code": None,
    "probes": [], "fetched_at": 0.0, "error": None,
}
_EXIT_IP_TTL_SEC = 600

# Public IP probes — each returns the IP in its response body.
# We hit several because some VPN providers source-NAT differently per
# destination IP, so a single probe doesn't tell the whole story.
#
# Each entry is (display_name, url, json_field):
#   json_field = None    -> response body is a plain IP (curl just trims)
#   json_field = "ip"    -> JSON response, take the named field
#
# Skipped (verified non-functional behind a VPN exit):
#   bot.whatismyipaddress.com — Cloudflare returns empty body to scripts
#   whatismyipaddress.com/api — explicitly blocks "scripted access" (CF1)
#   2ip.ru/api/, api.2ip.ru   — return HTML / empty for our path
_EXIT_PROBES = (
    ("api.ipify.org",  "https://api.ipify.org",  None),
    ("ipinfo.io",      "https://ipinfo.io/ip",   None),
    ("ifconfig.me",    "https://ifconfig.me/ip", None),
    ("icanhazip.com",  "https://icanhazip.com",  None),
    ("ident.me",       "https://ident.me",       None),
    ("2ip.ru",         "https://2ip.ru",         None),
    ("api.myip.com",   "https://api.myip.com",   "ip"),
)
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_COUNTRY_NAMES_BY_CODE = {
    "CH": "Switzerland",
    "DE": "Germany",
    "EE": "Estonia",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "NL": "Netherlands",
    "PL": "Poland",
    "RU": "Russia",
    "SE": "Sweden",
    "US": "United States",
}


def invalidate_exit_ip_cache() -> None:
    """Force the next /system/status to re-look up the public exit IP.
    Called when the active VPN config is changed."""
    _EXIT_IP_CACHE.update(ip=None, country=None, country_code=None,
                          probes=[], fetched_at=0.0, error=None)


def get_external_tunnel_choice() -> str:
    try:
        selected = EXTERNAL_TUNNEL_FILE.read_text().strip()
    except FileNotFoundError:
        selected = "amnezia"
    return selected if selected in ("amnezia", "xray", "none") else "amnezia"


def get_external_tunnel_interface() -> str | None:
    selected = get_external_tunnel_choice()
    if selected == "xray":
        return XRAY_TUN_INTERFACE
    if selected == "none":
        return None
    return AMNEZIA_INTERFACE


async def _probe_exit(service_name: str, url: str, json_field: str | None) -> dict:
    """Hit one external IP probe through the VPN tunnel.
    Returns {service, ip, error}. Handles both plain-text and JSON
    responses (json_field selects which key to read)."""
    external_iface = get_external_tunnel_interface()
    if not external_iface:
        return {"service": service_name, "ip": None, "error": "no external VPN selected"}
    result = await run_command(
        "curl", "-s", "--max-time", "8",
        "--interface", external_iface,
        url,
        timeout=10,
    )
    if not result.success:
        return {"service": service_name, "ip": None, "error": "request failed"}

    text = result.output.strip()
    candidate = text
    if json_field is not None:
        try:
            data = json.loads(text)
            candidate = str(data.get(json_field) or "").strip()
        except json.JSONDecodeError:
            return {"service": service_name, "ip": None, "error": "invalid JSON"}

    if _IP_RE.match(candidate):
        return {"service": service_name, "ip": candidate, "error": None}
    return {"service": service_name, "ip": None, "error": "no IP in response"}


def _normalize_country_code(value: object) -> str | None:
    code = str(value or "").strip().upper()
    return code if re.match(r"^[A-Z]{2}$", code) else None


async def _geo_lookup_ipinfo(ip: str, external_iface: str) -> tuple[str | None, str | None, str | None]:
    """Look up an IP via ipinfo.io.

    ip-api.com still has stale data for some reassigned hosting ranges
    (for example 203.0.113.10), while ipinfo tracks the current ASN/DC
    correctly. Keep this first, with ip-api as a fallback below.
    """
    geo_result = await run_command(
        "curl", "-s", "--max-time", "8",
        "--interface", external_iface,
        f"https://ipinfo.io/{ip}/json",
        timeout=10,
    )
    if not geo_result.success:
        return None, None, "ipinfo request failed"
    try:
        data = json.loads(geo_result.output)
    except json.JSONDecodeError:
        return None, None, "ipinfo invalid JSON"
    if data.get("bogon"):
        return None, None, "ipinfo bogon"
    code = _normalize_country_code(data.get("country"))
    if code:
        return _COUNTRY_NAMES_BY_CODE.get(code, code), code, None
    return None, None, data.get("error", {}).get("message") or "ipinfo failed"


async def _geo_lookup_ip_api(ip: str, external_iface: str) -> tuple[str | None, str | None, str | None]:
    """Look up an IP's country via ip-api.com (fallback).
    Returns (country, country_code, error)."""
    geo_result = await run_command(
        "curl", "-s", "--max-time", "8",
        "--interface", external_iface,
        f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,message",
        timeout=10,
    )
    if not geo_result.success:
        return None, None, "geo request failed"
    try:
        data = json.loads(geo_result.output)
    except json.JSONDecodeError:
        return None, None, "geo invalid JSON"
    if data.get("status") == "success":
        return data.get("country"), data.get("countryCode"), None
    return None, None, data.get("message") or "geo failed"


async def _geo_lookup(ip: str) -> tuple[str | None, str | None, str | None]:
    """Look up an IP's country through the selected external tunnel."""
    external_iface = get_external_tunnel_interface()
    if not external_iface:
        return None, None, "no external VPN selected"

    country, code, ipinfo_error = await _geo_lookup_ipinfo(ip, external_iface)
    if code:
        return country, code, None

    country, code, ip_api_error = await _geo_lookup_ip_api(ip, external_iface)
    if code:
        return country, code, None
    return None, None, ip_api_error or ipinfo_error or "geo failed"


async def get_interface_info(iface: str) -> InterfaceInfo:
    result = await run_command("ip", "-j", "addr", "show", iface)
    if not result.success:
        return InterfaceInfo(name=iface, up=False)

    try:
        data = json.loads(result.output)
        if not data:
            return InterfaceInfo(name=iface, up=False)
        info = data[0]
        state = info.get("operstate", "DOWN")
        ip_addr = None
        for addr_info in info.get("addr_info", []):
            if addr_info.get("family") == "inet":
                ip_addr = addr_info.get("local")
                break

        # Get traffic stats
        stats_result = await run_command(
            "cat", f"/sys/class/net/{iface}/statistics/tx_bytes"
        )
        tx = int(stats_result.output.strip()) if stats_result.success else 0
        stats_result = await run_command(
            "cat", f"/sys/class/net/{iface}/statistics/rx_bytes"
        )
        rx = int(stats_result.output.strip()) if stats_result.success else 0

        return InterfaceInfo(
            name=iface,
            up=state in ("UP", "UNKNOWN"),
            ip_address=ip_addr,
            tx_bytes=tx,
            rx_bytes=rx,
        )
    except (json.JSONDecodeError, KeyError, IndexError):
        return InterfaceInfo(name=iface, up=False)


async def get_service_status(name: str) -> ServiceInfo:
    if name not in ALLOWED_SERVICES:
        return ServiceInfo(name=name, active=False, state="unknown", enabled=False)

    unit = f"{name}.service"
    # `Result` reports the outcome of the last service invocation:
    # "success" / "exit-code" / "signal" / "timeout" / "core-dump" / etc.
    # For one-shot services (timer-triggered) ActiveState/SubState are
    # always inactive/dead between runs — the only meaningful health
    # signal is Result.
    result = await run_command(
        "systemctl", "show", unit,
        "--property=ActiveState,SubState,Description,UnitFileState,Result",
        "--no-pager",
    )
    props = {}
    for line in result.output.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v

    active_state = props.get("ActiveState", "unknown")
    sub_state = props.get("SubState", "")
    enabled = props.get("UnitFileState", "") == "enabled"
    last_result = props.get("Result", "")

    # For timer-triggered oneshot services (vpngw-update-iplists),
    # check if the associated timer is active instead of the service itself.
    # If timer is active we treat the service as healthy and replace the
    # state string with one that reflects the LAST RUN's outcome — the
    # service's own SubState is always "dead" between runs (which is
    # systemd-speak for "not currently executing", not "broken"), and
    # surfacing that confuses humans reading the dashboard.
    is_active = active_state == "active"
    timer_unit = f"{name}.timer"
    timer_result = await run_command("systemctl", "is-active", timer_unit)
    if timer_result.success and timer_result.output.strip() == "active":
        is_active = True
        if active_state != "active":
            # Build a human-friendly label: timer waiting + last-run summary.
            if last_result == "success":
                sub_state = "timer waiting, last run OK"
            elif last_result:
                sub_state = f"timer waiting, last run FAILED ({last_result})"
            else:
                sub_state = "timer waiting"
            enabled = True
            # Also flip the displayed top-level state to "active" — the
            # unit IS healthy from a one-shot-with-timer perspective, even
            # though .service itself is inactive between runs.
            active_state = "active"

    return ServiceInfo(
        name=name,
        description=props.get("Description", ""),
        active=is_active,
        state=f"{active_state} ({sub_state})" if sub_state else active_state,
        enabled=enabled,
    )


async def get_all_services() -> list[ServiceInfo]:
    services = []
    for name in sorted(ALLOWED_SERVICES):
        services.append(await get_service_status(name))
    return services


async def get_system_resources() -> SystemResources:
    # Uptime
    uptime_result = await run_command("uptime", "-p")
    uptime_str = uptime_result.output.strip() if uptime_result.success else "unknown"

    # Load
    load_result = await run_command("cat", "/proc/loadavg")
    load = [0.0, 0.0, 0.0]
    if load_result.success:
        parts = load_result.output.strip().split()
        load = [float(parts[i]) for i in range(3)]

    # Memory
    mem_result = await run_command("free", "-m")
    mem_total = mem_used = 0
    if mem_result.success:
        for line in mem_result.output.split("\n"):
            if line.startswith("Mem:"):
                parts = line.split()
                mem_total = int(parts[1])
                mem_used = int(parts[2])
                break

    # CPU count
    cpu_result = await run_command("nproc")
    cpu_count = int(cpu_result.output.strip()) if cpu_result.success else 1

    return SystemResources(
        uptime=uptime_str,
        load_average=load,
        memory_total_mb=mem_total,
        memory_used_mb=mem_used,
        memory_percent=round(mem_used / mem_total * 100, 1) if mem_total else 0,
        cpu_count=cpu_count,
    )


async def get_ipset_info() -> IpsetInfo:
    result = await run_command("ipset", "list", IPSET_NAME, "-t")
    entries = 0
    max_entries = 131072
    memory = 0
    set_type = "hash:net"

    if result.success:
        for line in result.output.split("\n"):
            if line.startswith("Number of entries:"):
                entries = int(line.split(":")[1].strip())
            elif line.startswith("Size in memory:"):
                memory = int(line.split(":")[1].strip())
            elif line.startswith("Header:"):
                m = re.search(r"maxelem\s+(\d+)", line)
                if m:
                    max_entries = int(m.group(1))
            elif line.startswith("Type:"):
                set_type = line.split(":")[1].strip()

    return IpsetInfo(
        name=IPSET_NAME,
        type=set_type,
        entries=entries,
        max_entries=max_entries,
        memory_bytes=memory,
    )


async def ipset_test(ip: str) -> bool:
    result = await run_command("ipset", "test", IPSET_NAME, ip)
    return result.success


async def get_ip_rules() -> list[IpRuleInfo]:
    result = await run_command("ip", "rule", "list")
    rules = []
    if result.success:
        for line in result.output.strip().split("\n"):
            m = re.match(r"(\d+):\s+(.+?)\s+(lookup\s+\S+|unreachable|prohibit)", line)
            if m:
                rules.append(IpRuleInfo(
                    priority=int(m.group(1)),
                    selector=m.group(2).strip(),
                    action=m.group(3).strip(),
                ))
    return rules


async def get_routes(table: str = "main") -> list[RouteInfo]:
    result = await run_command("ip", "route", "show", "table", table)
    routes = []
    if result.success:
        for line in result.output.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            dst = parts[0] if parts else "?"
            dev = ""
            gw = None
            for i, p in enumerate(parts):
                if p == "dev" and i + 1 < len(parts):
                    dev = parts[i + 1]
                elif p == "via" and i + 1 < len(parts):
                    gw = parts[i + 1]
            routes.append(RouteInfo(
                destination=dst,
                gateway=gw,
                device=dev,
                extra=line,
            ))
    return routes


async def dig_query(domain: str, qtype: str = "A") -> list[str]:
    result = await run_command(
        "dig", "+short", f"+time=5", f"+tries=1", domain, qtype, "@127.0.0.1"
    )
    if not result.success:
        return []
    return [line.strip() for line in result.output.strip().split("\n") if line.strip()]


async def service_action(name: str, action: str) -> str:
    if name not in ALLOWED_SERVICES:
        return f"Service {name} not in whitelist"
    if action not in ("start", "stop", "restart", "enable", "disable"):
        return f"Invalid action: {action}"
    result = await run_command("systemctl", action, f"{name}.service")
    return result.output


async def run_systemctl(action: str, name: str) -> str:
    """Run a whitelisted systemctl action against a whitelisted unit.
    Convenience wrapper kept for callers that pass action first."""
    return await service_action(name, action)


async def get_service_logs(name: str, lines: int = 50) -> str:
    if name not in ALLOWED_SERVICES:
        return f"Service {name} not in whitelist"
    result = await run_command(
        "journalctl", "-u", f"{name}.service",
        "--no-pager", "-n", str(lines), "--output=short-iso",
    )
    return result.output if result.success else ""


async def check_internet() -> dict:
    """Check ISP-side internet connectivity (gateway → upstream host).

    We deliberately ping 9.9.9.9 (Quad9), NOT 8.8.8.8: the gateway has
    static routes `8.8.8.8 dev amn0` and `1.1.1.1 dev amn0` (added by
    vpngw-fix-routes.sh so dnsmasq's upstream DNS escapes Russian ISP
    DNS hijacking). Those force ICMP to 8.8.8.8 through the VPN tunnel,
    where the provider often drops it — giving false-negative reds on
    the dashboard's "Internet" card. 9.9.9.9 is not in that pin-list,
    so it goes through the normal default route via the ISP.
    """
    from config import LAN_GATEWAY

    target = "9.9.9.9"
    gw_result = await run_command("ping", "-c1", "-W3", LAN_GATEWAY)
    inet_result = await run_command("ping", "-c1", "-W5", target)

    return {
        "gateway": {"ip": LAN_GATEWAY, "reachable": gw_result.success},
        "internet": {"target": target, "reachable": inet_result.success},
    }


async def get_exit_ip_info(force: bool = False) -> dict:
    """
    Probe the public IP that several external services see when the
    gateway connects through the VPN tunnel, and look up the country of
    each unique IP via ip-api.com.

    A single probe used to be enough until we noticed this provider's
    routing layer applies different source-NAT depending on the
    destination IP — api.ipify.org sees a Russian exit while ipinfo.io
    sees the WG endpoint itself, on the same tunnel and same active
    config. Polling several services exposes the variation.

    Result is cached in process for _EXIT_IP_TTL_SEC seconds.
    """
    now = time.time()
    cached_age = now - _EXIT_IP_CACHE["fetched_at"]
    if (not force and _EXIT_IP_CACHE.get("ip")
            and cached_age < _EXIT_IP_TTL_SEC):
        return dict(_EXIT_IP_CACHE)

    # Hit all probes in parallel — total wall time = slowest probe (~8s),
    # not sum.
    probes = await asyncio.gather(
        *(_probe_exit(name, url, jf) for name, url, jf in _EXIT_PROBES),
        return_exceptions=False,
    )

    # Geolocate each unique IP — usually 1–3 unique IPs across 4 probes,
    # so we save a few ip-api requests and stay under the 45 req/min quota.
    unique_ips = sorted({p["ip"] for p in probes if p["ip"]})
    geo = await asyncio.gather(*(_geo_lookup(ip) for ip in unique_ips))
    geo_by_ip = {
        ip: {"country": c, "country_code": cc}
        for ip, (c, cc, _err) in zip(unique_ips, geo)
    }

    # Annotate each probe with its IP's country.
    annotated = []
    for p in probes:
        if p["ip"] and p["ip"] in geo_by_ip:
            annotated.append({**p, **geo_by_ip[p["ip"]]})
        else:
            annotated.append({**p, "country": None, "country_code": None})

    # Primary = first probe that returned an IP. Used by the legacy
    # single-IP fields (.ip / .country / .country_code) so older clients
    # and the dashboard's main address line keep working unchanged.
    primary = next((a for a in annotated if a["ip"]), None)

    _EXIT_IP_CACHE.update(
        ip=primary["ip"] if primary else None,
        country=primary["country"] if primary else None,
        country_code=primary["country_code"] if primary else None,
        probes=annotated,
        fetched_at=now,
        error=None if primary else "all exit-IP probes failed",
    )
    return dict(_EXIT_IP_CACHE)


async def get_domains_count() -> int:
    """Count non-comment, non-empty lines across all config/domains/*.lst
    files (main + aws + cloudflare + any other category). Each file
    produces its own /etc/dnsmasq.d/vpn-domains-<cat>.conf but they all
    populate the same vpn_domains ipset."""
    from config import DOMAINS_DIR
    total = 0
    if not DOMAINS_DIR.is_dir():
        return 0
    for path in DOMAINS_DIR.glob("*.lst"):
        if path.name.startswith("."):
            continue
        try:
            for line in path.read_text(encoding="utf-8").split("\n"):
                s = line.strip()
                if s and not s.startswith("#"):
                    total += 1
        except (OSError, UnicodeDecodeError):
            continue
    return total
