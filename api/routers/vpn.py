"""VPN tunnel management endpoints."""

import asyncio
import re
import secrets
import socket
import time
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from config import (
    EXTERNAL_TUNNEL_FILE, SCRIPTS, VPN_ACTIVE_FILE, VPN_CONFIGS_DIR,
    VPN_INTERFACE,
)
from models.common import error, ok
from services import system_commands as sys_cmd
from services.script_runner import run_command

router = APIRouter(prefix="/vpn", tags=["vpn"])

VPN_SERVICE = "vpngw-vpn"
PING_DOC_IP = "203.0.113.1"
HARD_TEST_HOST = "speed.cloudflare.com"
HARD_TEST_URL = "https://speed.cloudflare.com/__down?bytes=1048576"
PROTECTED_CONFIG_NAMES: set[str] = set()
POSTUP = "PostUp = /opt/vpngateway/scripts/vpngw-fix-routes.sh"
POSTDOWN = "PostDown = /opt/vpngateway/scripts/vpngw-on-vpn-down.sh"
OPTIONAL_EMPTY_INTERFACE_KEYS = {"I1", "I2", "I3", "I4", "I5"}

# Filename of an AmneziaWG config in VPN_CONFIGS_DIR, without ".conf".
# We require a short, safe identifier so it can be passed to a shell helper
# script and trusted as a path component.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class ConfigUpload(BaseModel):
    name: str = ""
    filename: str = ""
    content: str
    overwrite: bool = False

# ISO 3166-1 alpha-2 -> human-readable country name. Config filenames may
# optionally include a variant suffix, for example DE-VLESS.conf.
COUNTRY_NAMES = {
    "CH": "Switzerland",
    "NL": "Netherlands",
    "RU": "Russia",
    "KZ": "Kazakhstan",
    "DE": "Germany",
    "FR": "France",
    "GB": "United Kingdom",
    "US": "United States",
    "TR": "Türkiye",
    "FI": "Finland",
    "SE": "Sweden",
    "NO": "Norway",
    "PL": "Poland",
    "CZ": "Czechia",
    "AT": "Austria",
    "BE": "Belgium",
    "IT": "Italy",
    "ES": "Spain",
    "JP": "Japan",
    "SG": "Singapore",
    "HK": "Hong Kong",
    "KR": "South Korea",
    "UA": "Ukraine",
    "GE": "Georgia",
    "AM": "Armenia",
    "BY": "Belarus",
    "MD": "Moldova",
    "EE": "Estonia",
    "LV": "Latvia",
    "LT": "Lithuania",
    "RO": "Romania",
    "BG": "Bulgaria",
    "RS": "Serbia",
    "AE": "UAE",
    "IL": "Israel",
    "IN": "India",
    "ID": "Indonesia",
    "TH": "Thailand",
    "VN": "Vietnam",
    "AU": "Australia",
    "NZ": "New Zealand",
    "CA": "Canada",
    "BR": "Brazil",
    "AR": "Argentina",
    "MX": "Mexico",
    "ZA": "South Africa",
}


def _format_variant_token(token: str) -> str:
    upper = token.upper()
    if token.isupper() or any(ch.isdigit() for ch in token):
        return upper
    return token[:1].upper() + token[1:]


def _config_display(name: str) -> dict[str, str | None]:
    """Build stable API identity fields from a config filename stem.

    `name` remains the technical id used for activation.  For display, plain
    country-code files keep the old behavior (DE -> Germany), while variant
    files use the first token as the country and keep the suffix visible
    (DE-VLESS -> Germany VLESS).
    """
    parts = [part for part in re.split(r"[-_]+", name) if part]
    country_code = parts[0].upper() if parts and len(parts[0]) == 2 else None

    if not country_code:
        return {
            "country_code": None,
            "country_name": name,
            "variant": None,
            "display_name": name,
        }

    country_name = COUNTRY_NAMES.get(country_code, country_code)
    variant = " ".join(_format_variant_token(part) for part in parts[1:]) or None
    display_name = f"{country_name} {variant}" if variant else country_name
    return {
        "country_code": country_code,
        "country_name": country_name,
        "variant": variant,
        "display_name": display_name,
    }


def _read_active() -> str | None:
    try:
        return VPN_ACTIVE_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _read_external_tunnel() -> str:
    try:
        val = EXTERNAL_TUNNEL_FILE.read_text().strip()
    except FileNotFoundError:
        return "amnezia"
    return val if val in ("amnezia", "xray", "none") else "amnezia"


def _speed_label(speed_bps: float) -> str:
    if speed_bps >= 1024 * 1024:
        return f"{speed_bps / 1024 / 1024:.2f} MB/s"
    if speed_bps >= 1024:
        return f"{speed_bps / 1024:.0f} KB/s"
    return f"{speed_bps:.0f} B/s"


def _validate_name(name: str) -> str:
    clean = name.strip()
    if clean.endswith(".conf"):
        clean = clean[:-5]
    if not _NAME_RE.match(clean):
        raise ValueError(f"invalid config name: {name!r}")
    return clean


def _adapt_amneziawg_text(raw: str) -> str:
    lines = raw.splitlines()
    out: list[str] = []
    section: str | None = None
    has_table = has_postup = has_postdown = False
    interface_done = False

    def flush_interface_extras() -> None:
        nonlocal has_table, has_postup, has_postdown
        if not has_table:
            out.append("Table = off")
            has_table = True
        if not has_postup:
            out.append(POSTUP)
            has_postup = True
        if not has_postdown:
            out.append(POSTDOWN)
            has_postdown = True

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "Interface" and not interface_done:
                flush_interface_extras()
                if out and out[-1].strip():
                    out.append("")
                interface_done = True
            section = stripped[1:-1]
            out.append(line)
            continue

        if section == "Interface":
            if "=" in stripped:
                key, value = stripped.split("=", 1)
                key = key.strip()
                if key in OPTIONAL_EMPTY_INTERFACE_KEYS and not value.strip():
                    continue
                low = key.lower()
                if low == "dns":
                    continue
                if low == "table":
                    has_table = True
                elif low == "postup":
                    has_postup = True
                elif low == "postdown":
                    has_postdown = True

        out.append(line)

    if section == "Interface" and not interface_done:
        flush_interface_extras()

    return "\n".join(out).rstrip() + "\n"


def _looks_like_amneziawg_config(text: str) -> bool:
    low = text.lower()
    required = ("[interface]", "[peer]", "privatekey", "publickey", "endpoint")
    return all(token in low for token in required)


def _parse_interface_value(conf_path: Path, key: str) -> str:
    try:
        in_interface = False
        for raw in conf_path.read_text().splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                in_interface = line.lower() == "[interface]"
                continue
            if in_interface and line.lower().startswith(key.lower()):
                left, _, val = line.partition("=")
                if left.strip().lower() == key.lower():
                    return val.strip()
    except OSError:
        pass
    return ""


def _probe_iface_name() -> str:
    return f"awgt{secrets.token_hex(4)}"


def _strip_runtime_lines(src: Path, dst: Path) -> None:
    skip_keys = {
        "address", "dns", "table", "mtu", "preup", "postup",
        "predown", "postdown", "saveconfig",
    }
    out = []
    for raw in src.read_text().splitlines():
        stripped = raw.strip()
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip().lower()
            if key in skip_keys:
                continue
        out.append(raw)
    dst.write_text("\n".join(out) + "\n")
    dst.chmod(0o600)


async def _run_checked(*args: str, timeout: int = 10) -> tuple[bool, str]:
    result = await run_command(*args, timeout=timeout)
    return result.success, result.output.strip()


async def _awg_transfer(iface: str) -> tuple[int, int]:
    result = await run_command("awg", "show", iface, "transfer", timeout=4)
    rx = 0
    tx = 0
    if result.success:
        for line in result.output.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    rx += int(parts[1])
                    tx += int(parts[2])
                except ValueError:
                    continue
    return rx, tx


async def _awg_latest_handshake(iface: str) -> int:
    result = await run_command("awg", "show", iface, "latest-handshakes", timeout=4)
    latest = 0
    if result.success:
        for line in result.output.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    latest = max(latest, int(parts[1]))
                except ValueError:
                    continue
    return latest


async def _add_route(ip: str, iface: str) -> None:
    await run_command("ip", "route", "add", f"{ip}/32", "dev", iface, timeout=4)


async def _del_route(ip: str, iface: str) -> None:
    await run_command("ip", "route", "del", f"{ip}/32", "dev", iface, timeout=4)


async def _wait_for_handshake(iface: str, timeout: int = 8) -> dict:
    started_at = time.monotonic()
    await _add_route(PING_DOC_IP, iface)
    try:
        while time.monotonic() - started_at < timeout:
            await run_command(
                "timeout", "2", "ping", "-n", "-I", iface, "-c", "1", "-W", "1",
                PING_DOC_IP,
                timeout=3,
            )
            hs = await _awg_latest_handshake(iface)
            rx, tx = await _awg_transfer(iface)
            if hs > 0 and rx > 0:
                return {
                    "ok": True,
                    "handshake": hs,
                    "rx": rx,
                    "tx": tx,
                    "time_ms": int((time.monotonic() - started_at) * 1000),
                }
            await asyncio.sleep(0.5)
    finally:
        await _del_route(PING_DOC_IP, iface)
    hs = await _awg_latest_handshake(iface)
    rx, tx = await _awg_transfer(iface)
    return {
        "ok": False,
        "handshake": hs,
        "rx": rx,
        "tx": tx,
        "time_ms": int((time.monotonic() - started_at) * 1000),
        "error": "handshake failed",
    }


async def _resolve_ipv4(host: str) -> str:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    if not infos:
        raise RuntimeError(f"resolve failed: {host}")
    return infos[0][4][0]


async def _setup_temp_interface(name: str) -> tuple[str, Path]:
    src = VPN_CONFIGS_DIR / f"{name}.conf"
    if not src.is_file():
        raise RuntimeError(f"config not found: {name}")
    iface = _probe_iface_name()
    tmpconf = Path("/run") / f"{iface}.conf"
    _strip_runtime_lines(src, tmpconf)

    ok_link, out = await _run_checked("ip", "link", "add", iface, "type", "amneziawg", timeout=5)
    if not ok_link:
        tmpconf.unlink(missing_ok=True)
        raise RuntimeError(f"ip link add failed: {out[:200]}")
    ok_conf, out = await _run_checked("awg", "setconf", iface, str(tmpconf), timeout=5)
    if not ok_conf:
        await run_command("ip", "link", "del", iface, timeout=5)
        tmpconf.unlink(missing_ok=True)
        raise RuntimeError(f"awg setconf failed: {out[:200]}")

    addr = _parse_interface_value(src, "Address").split(",", 1)[0].strip()
    mtu = _parse_interface_value(src, "MTU").strip() or "1420"
    if addr:
        await run_command("ip", "address", "add", addr, "dev", iface, timeout=5)
    await run_command("ip", "link", "set", "dev", iface, "mtu", mtu, timeout=5)
    await run_command("ip", "link", "set", "up", "dev", iface, timeout=5)
    return iface, tmpconf


async def _cleanup_temp_interface(iface: str, tmpconf: Path | None = None) -> None:
    await run_command("ip", "link", "del", iface, timeout=5)
    if tmpconf:
        tmpconf.unlink(missing_ok=True)


async def _probe_interface_for_config(name: str) -> tuple[str, Path | None, bool]:
    active = _read_active()
    if name == active and _read_external_tunnel() == "amnezia":
        svc = await sys_cmd.get_service_status(VPN_SERVICE)
        iface = await sys_cmd.get_interface_info(VPN_INTERFACE)
        if svc.active and iface.up:
            return VPN_INTERFACE, None, True
    iface_name, tmpconf = await _setup_temp_interface(name)
    return iface_name, tmpconf, False


async def _ping_config(name: str, timeout: int = 8) -> dict:
    iface = ""
    tmpconf: Path | None = None
    live = False
    try:
        iface, tmpconf, live = await _probe_interface_for_config(name)
        result = await _wait_for_handshake(iface, timeout=timeout)
        return {"name": name, "interface": iface, "live": live, **result}
    finally:
        if iface and not live:
            await _cleanup_temp_interface(iface, tmpconf)


async def _hard_test_config(name: str, timeout: int = 25) -> dict:
    iface = ""
    tmpconf: Path | None = None
    live = False
    test_ip = ""
    try:
        iface, tmpconf, live = await _probe_interface_for_config(name)
        test_ip = await _resolve_ipv4(HARD_TEST_HOST)
        await _add_route(test_ip, iface)
        curl = await run_command(
            "curl",
            "--interface", iface,
            "--resolve", f"{HARD_TEST_HOST}:443:{test_ip}",
            "-4",
            "-ksSL",
            "--connect-timeout", "8",
            "-m", str(timeout),
            "-o", "/dev/null",
            "-w", "%{http_code} %{size_download} %{speed_download} %{time_total}",
            HARD_TEST_URL,
            timeout=timeout + 5,
        )
        line = curl.output.strip().splitlines()[-1] if curl.output.strip() else ""
        parts = line.split()
        http_code = parts[0] if parts else ""
        try:
            downloaded = int(float(parts[1])) if len(parts) >= 2 else 0
        except ValueError:
            downloaded = 0
        try:
            speed_bps = float(parts[2]) if len(parts) >= 3 else 0.0
        except ValueError:
            speed_bps = 0.0
        try:
            time_total = float(parts[3]) if len(parts) >= 4 else 0.0
        except ValueError:
            time_total = 0.0
        rx, tx = await _awg_transfer(iface)
        ok_result = curl.success and http_code == "200" and downloaded > 0 and speed_bps > 0
        return {
            "name": name,
            "interface": iface,
            "live": live,
            "ok": ok_result,
            "http_code": http_code,
            "bytes": downloaded,
            "rx": rx,
            "tx": tx,
            "time_ms": int(time_total * 1000) if time_total else 0,
            "speed_bps": int(speed_bps) if speed_bps > 0 else 0,
            "speed_mbps": round(speed_bps / 1024 / 1024, 3) if speed_bps > 0 else 0,
            "speed_label": _speed_label(speed_bps) if speed_bps > 0 else "0",
            "error": "" if ok_result else (curl.output.strip()[:300] if curl.output else "download failed"),
        }
    finally:
        if test_ip:
            await _del_route(test_ip, iface)
        if iface and not live:
            await _cleanup_temp_interface(iface, tmpconf)


async def _hard_test_config_after_ping(name: str, timeout: int = 25) -> dict:
    ping = await _ping_config(name, timeout=8)
    if not ping.get("ok"):
        return {
            "name": name,
            "ok": False,
            "skipped": True,
            "ping": ping,
            "http_code": "",
            "bytes": 0,
            "time_ms": 0,
            "speed_bps": 0,
            "speed_mbps": 0,
            "speed_label": "0",
            "error": "ping failed; hard test skipped",
        }
    result = await _hard_test_config(name, timeout=timeout)
    result["ping"] = ping
    return result


async def _select_external(target: str) -> tuple[bool, str]:
    script = SCRIPTS.get("select-external-tunnel")
    if not script or not script.is_file():
        return False, "select-external-tunnel helper script not deployed"
    result = await run_command(str(script), target, timeout=40)
    return result.success, result.output.strip()


def _parse_endpoint(conf_path) -> str:
    """Extract the [Peer].Endpoint value from an AmneziaWG config file.
    Returns empty string if not found or unreadable."""
    try:
        for raw in conf_path.read_text().splitlines():
            s = raw.strip()
            if s.startswith("Endpoint"):
                _, _, val = s.partition("=")
                return val.strip()
    except OSError:
        pass
    return ""


@router.get("/status")
async def vpn_status():
    iface = await sys_cmd.get_interface_info(VPN_INTERFACE)
    svc = await sys_cmd.get_service_status(VPN_SERVICE)
    return ok({
        "interface": iface.model_dump(),
        "service": svc.model_dump(),
    })


@router.post("/start")
async def vpn_start():
    success, log = await _select_external("amnezia")
    if not success:
        return error(f"start Amnezia failed: {log[:500]}")
    iface = await sys_cmd.get_interface_info(VPN_INTERFACE)
    svc = await sys_cmd.get_service_status(VPN_SERVICE)
    sys_cmd.invalidate_exit_ip_cache()
    return ok({"interface": iface.model_dump(), "service": svc.model_dump()}, log=log)


@router.post("/stop")
async def vpn_stop():
    if _read_external_tunnel() == "amnezia":
        success, log = await _select_external("none")
        if not success:
            return error(f"stop Amnezia failed: {log[:500]}")
    else:
        log = await sys_cmd.service_action(VPN_SERVICE, "stop")
    svc = await sys_cmd.get_service_status(VPN_SERVICE)
    sys_cmd.invalidate_exit_ip_cache()
    return ok({"service": svc.model_dump()}, log=log)


@router.post("/restart")
async def vpn_restart():
    log = await sys_cmd.service_action(VPN_SERVICE, "restart")
    iface = await sys_cmd.get_interface_info(VPN_INTERFACE)
    svc = await sys_cmd.get_service_status(VPN_SERVICE)
    return ok({"interface": iface.model_dump(), "service": svc.model_dump()}, log=log)


@router.get("/configs")
async def list_configs():
    """List available AmneziaWG configs in /opt/vpngateway/config/configs/.
    The filename stem is the technical id; display fields are derived from it."""
    active = _read_active()
    items = []
    if VPN_CONFIGS_DIR.is_dir():
        for path in sorted(VPN_CONFIGS_DIR.glob("*.conf")):
            name = path.stem
            display = _config_display(name)
            items.append({
                "name": name,
                **display,
                "endpoint": _parse_endpoint(path),
                "active": name == active,
            })
    return ok({"configs": items, "active": active})


@router.post("/configs")
async def upload_config(payload: ConfigUpload):
    """Upload an AmneziaWG .conf into the runtime config library.

    The body is JSON by design: the browser reads the selected .conf as text
    and posts it here, avoiding an extra python-multipart runtime dependency.
    """
    try:
        name = _validate_name(payload.name or payload.filename)
    except ValueError as e:
        return error(str(e))

    if name in PROTECTED_CONFIG_NAMES:
        return error(f"config is protected and cannot be overwritten: {name}")

    raw = payload.content
    if not raw or not _looks_like_amneziawg_config(raw):
        return error("uploaded file does not look like an AmneziaWG .conf")

    dst = VPN_CONFIGS_DIR / f"{name}.conf"
    active = _read_active()
    existed = dst.exists()
    if existed and not payload.overwrite:
        return error(f"config already exists: {name}")
    if existed and name == active:
        return error("refusing to overwrite the active Amnezia config")

    VPN_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    dst.write_text(_adapt_amneziawg_text(raw))
    dst.chmod(0o600)
    display = _config_display(name)
    return ok({
        "name": name,
        **display,
        "endpoint": _parse_endpoint(dst),
        "active": name == active,
        "overwritten": existed,
    })


@router.post("/configs/{name}/activate")
async def activate_config(name: str):
    """Switch the active AmneziaWG config: copy configs/<name>.conf into
    /etc/amnezia/amneziawg/amn0.conf and restart the tunnel.
    The exit-IP cache is invalidated so the dashboard re-resolves the
    new country on the next /system/status call."""
    if not _NAME_RE.match(name):
        return error(f"invalid config name: {name!r}")

    src = VPN_CONFIGS_DIR / f"{name}.conf"
    if not src.is_file():
        return error(f"config not found: {name}")

    script = SCRIPTS.get("switch-vpn")
    if not script or not script.is_file():
        return error("switch-vpn helper script not deployed")

    # Run the helper synchronously — it stops vpngw-vpn, swaps the file,
    # starts vpngw-vpn, and runs the route fixer. ~3-5 seconds total.
    proc = await asyncio.create_subprocess_exec(
        str(script), name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return error("switch timed out after 30s")

    out = stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return error(f"switch failed (exit {proc.returncode})", data={"log": out})

    # The exit IP almost certainly changed — drop the geo cache so the
    # next dashboard refresh shows the new country.
    sys_cmd.invalidate_exit_ip_cache()

    iface = await sys_cmd.get_interface_info(VPN_INTERFACE)
    return ok({"active": name, "interface": iface.model_dump()}, log=out)


@router.delete("/configs/{name}")
async def delete_config(name: str):
    try:
        clean = _validate_name(name)
    except ValueError as e:
        return error(str(e))

    if clean in PROTECTED_CONFIG_NAMES:
        return error(f"config is protected and cannot be deleted: {clean}")
    active = _read_active()
    if clean == active:
        return error("refusing to delete the active Amnezia config")

    path = VPN_CONFIGS_DIR / f"{clean}.conf"
    if not path.is_file():
        return error(f"config not found: {clean}")
    path.unlink()
    return ok({"name": clean, "removed": True})


@router.post("/configs/{name}/ping")
async def ping_config(name: str):
    try:
        clean = _validate_name(name)
        result = await _ping_config(clean)
    except (RuntimeError, ValueError) as e:
        return error(str(e))
    return ok(result)


@router.post("/configs/{name}/hard-test")
async def hard_test_config(name: str, skip_ping: bool = False):
    try:
        clean = _validate_name(name)
        result = (
            await _hard_test_config(clean)
            if skip_ping
            else await _hard_test_config_after_ping(clean)
        )
    except (RuntimeError, ValueError) as e:
        return error(str(e))
    return ok(result)
