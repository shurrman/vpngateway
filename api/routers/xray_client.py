"""XRay client external tunnel management.

This is separate from routers/xray.py:
  * /xray is the optional public inbound service (clients connect to us);
  * /xray-client is the outbound external VPN tunnel (we connect to providers).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from config import (
    EXTERNAL_TUNNEL_FILE,
    GATEWAY_CONF,
    SCRIPTS,
    SCRIPTS_DIR,
    XRAY_CLIENT_ACTIVE_FILE,
    XRAY_CLIENT_CONFIGS_DIR,
    XRAY_CLIENT_HWID_FILE,
    XRAY_CLIENT_SUBSCRIPTION_STATE_DIR,
    XRAY_CLIENT_SUBSCRIPTIONS_DIR,
    XRAY_TUN_INTERFACE,
)
from models.common import error, ok
from services import system_commands as sys_cmd
from services.script_runner import run_command

_LOCAL_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
for _scripts_path in (SCRIPTS_DIR, _LOCAL_SCRIPTS):
    if _scripts_path.exists() and str(_scripts_path) not in sys.path:
        sys.path.insert(0, str(_scripts_path))

from vpngw_xray_client_lib import (  # noqa: E402
    NAME_RE,
    XRayClientError,
    build_socks_probe_config,
    load_proxy_outbound,
    load_proxy_outbound_text,
    parse_subscription_payload,
    stable_config_name,
    subscription_source_from_key,
    subscription_url_from_key,
    summarize_text,
)

router = APIRouter(prefix="/xray-client", tags=["xray-client"])

XRAY_CLIENT_SERVICE = "vpngw-xray-client"
XRAY_BINARY = Path("/usr/local/bin/xray")
OUTLINE_SS_BINARY = Path("/usr/local/bin/vpngw-outline-ss-local")
PING_URL = "https://api.ipify.org"
HARD_TEST_URL = "https://speed.cloudflare.com/__down?bytes=1048576"
SUBSCRIPTION_TEST_CONCURRENCY = 8
SUBSCRIPTION_USER_AGENTS = (
    "vpngateway-xray-client/1",
    "Happ/2.6.0",
    "Incy/1.0",
)
AUTO_HWID_SUBSCRIPTION_HOSTS = (
    "auth.easy-api.live",
)


class SubscriptionCreate(BaseModel):
    name: str
    url: str
    hwid: str = ""


class ConfigUpload(BaseModel):
    name: str = ""
    filename: str = ""
    content: str
    overwrite: bool = False


def _read_active() -> str | None:
    try:
        name = XRAY_CLIENT_ACTIVE_FILE.read_text().strip()
    except FileNotFoundError:
        return None
    return name if NAME_RE.match(name) else None


def _read_external_tunnel() -> str:
    try:
        val = EXTERNAL_TUNNEL_FILE.read_text().strip()
    except FileNotFoundError:
        return "amnezia"
    return val if val in ("amnezia", "xray", "none") else "amnezia"


def _read_gateway_conf() -> dict[str, str]:
    conf: dict[str, str] = {}
    if GATEWAY_CONF.exists():
        for raw in GATEWAY_CONF.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            conf[key.strip()] = val.strip().strip('"').strip("'")
    return conf


def _config_summary(path: Path) -> dict:
    try:
        text = path.read_text().strip()
    except OSError:
        summary = {"protocol": "unknown", "format": "unreadable", "endpoint": ""}
    else:
        summary = summarize_text(text, path.name)
    return {"name": path.stem, **summary}


def _validate_config_name(raw: str) -> str:
    name = (raw or "").strip()
    if name.lower().endswith(".key"):
        name = name[:-4]
    if not NAME_RE.match(name):
        raise XRayClientError(f"invalid XRay config name: {raw!r}")
    return name


def _validate_config_text(text: str, label: str) -> str:
    clean = text.strip()
    if not clean:
        raise XRayClientError("uploaded file is empty")
    load_proxy_outbound_text(clean, label or "uploaded.key", 0, "")
    return clean + "\n"


def _subscription_for_config(name: str) -> str:
    for sub in _subscription_items():
        state = _load_subscription_state(sub["name"]) or {}
        entries = state.get("entries") if isinstance(state.get("entries"), list) else []
        for entry in entries:
            entry_name = entry.get("name") if isinstance(entry, dict) else None
            if entry_name == name:
                return sub["name"]
    return ""


def _load_subscription_state(name: str) -> dict | None:
    path = XRAY_CLIENT_SUBSCRIPTION_STATE_DIR / f"{name}.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _subscription_fetch_error(url: str, err: BaseException) -> XRayClientError:
    host = urllib.parse.urlsplit(url).hostname or "subscription host"
    if isinstance(err, urllib.error.HTTPError):
        return XRayClientError(
            f"subscription fetch failed: HTTP {err.code} {err.reason} from {host}"
        )
    if isinstance(err, urllib.error.URLError):
        return XRayClientError(f"subscription fetch failed from {host}: {err.reason}")
    return XRayClientError(f"subscription fetch failed from {host}: {err}")


def _supported_subscription_entries(entries: list[Any]) -> tuple[list[Any], list[Any]]:
    supported = []
    rejected = []
    bad_markers = (
        "приложение не поддерживается",
        "отключили hwid",
        "лимит количества устройств",
        "device limit",
        "unsupported app",
        "hwid",
    )
    for entry in entries:
        display = str(getattr(entry, "display_name", "")).strip()
        endpoint = str(getattr(entry, "endpoint", "")).strip()
        low_display = display.lower()
        if endpoint == "0.0.0.0:1" or any(marker in low_display for marker in bad_markers):
            rejected.append(entry)
        else:
            supported.append(entry)
    return supported, rejected


def _unsupported_subscription_error(rejected: list[Any]) -> XRayClientError:
    names = []
    for entry in rejected[:3]:
        display = str(getattr(entry, "display_name", "")).strip()
        if display:
            names.append(display)
    hint = "; ".join(names) if names else "provider returned placeholder configs"
    return XRayClientError(
        "subscription returned provider placeholder configs instead of usable nodes: "
        f"{hint}. If this provider binds subscriptions to a device, configure its X-HWID "
        "for this gateway or reset the provider device limit."
    )


def _subscription_host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _subscription_uses_auto_hwid(url: str) -> bool:
    host = _subscription_host(url)
    return host in AUTO_HWID_SUBSCRIPTION_HOSTS


def _headers_have_hwid(headers: dict[str, str]) -> bool:
    return any(key.lower() == "x-hwid" and value.strip() for key, value in headers.items())


def _runtime_gateway_hwid() -> str:
    try:
        existing = XRAY_CLIENT_HWID_FILE.read_text().strip()
    except OSError:
        existing = ""
    if existing:
        return existing

    XRAY_CLIENT_HWID_FILE.parent.mkdir(parents=True, exist_ok=True)
    hwid = secrets.token_hex(16)
    tmp = XRAY_CLIENT_HWID_FILE.with_suffix(".tmp")
    tmp.write_text(hwid + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, XRAY_CLIENT_HWID_FILE)
    return hwid


def _write_subscription_source(path: Path, url: str, hwid: str = "") -> None:
    tmp = path.with_suffix(".key.tmp")
    tmp.write_text(_subscription_key_text(url, hwid))
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _subscription_hwid(url: str, explicit_hwid: str = "") -> str:
    clean_hwid = explicit_hwid.strip()
    if clean_hwid:
        return clean_hwid
    if _subscription_uses_auto_hwid(url):
        return _runtime_gateway_hwid()
    return ""


def _subscription_key_text(url: str, hwid: str = "") -> str:
    url = subscription_url_from_key(url)
    clean_hwid = hwid.strip()
    if not clean_hwid:
        return url + "\n"
    return json.dumps(
        {
            "url": url,
            "headers": {"X-HWID": clean_hwid},
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def _delete_subscription_files(name: str) -> dict[str, Any]:
    if not NAME_RE.match(name):
        raise XRayClientError(f"invalid subscription name: {name!r}")

    key_path = XRAY_CLIENT_SUBSCRIPTIONS_DIR / f"{name}.key"
    state_path = XRAY_CLIENT_SUBSCRIPTION_STATE_DIR / f"{name}.json"
    if not key_path.exists() and not state_path.exists():
        raise XRayClientError(f"subscription not found: {name}")

    current_active = _read_active()
    state = _load_subscription_state(name) or {}
    generated_names: set[str] = set()
    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    for entry in entries:
        entry_name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(entry_name, str):
            generated_names.add(entry_name)
    for path in XRAY_CLIENT_CONFIGS_DIR.glob(f"{name}-*.key"):
        generated_names.add(path.stem)

    removed_configs = []
    retained_active = ""
    for cfg_name in sorted(generated_names):
        if current_active and cfg_name == current_active:
            retained_active = cfg_name
            continue
        cfg_path = XRAY_CLIENT_CONFIGS_DIR / f"{cfg_name}.key"
        if cfg_path.exists():
            cfg_path.unlink()
            removed_configs.append(cfg_name)

    key_removed = False
    state_removed = False
    if key_path.exists():
        key_path.unlink()
        key_removed = True
    if state_path.exists():
        state_path.unlink()
        state_removed = True

    return {
        "subscription": name,
        "removed_configs": removed_configs,
        "removed_count": len(removed_configs),
        "retained_active": retained_active,
        "source_removed": key_removed,
        "state_removed": state_removed,
    }


async def _run_subscription_checks(
    entries: list[Any],
    runner: Any,
    *,
    timeout: int,
    default_failure: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(SUBSCRIPTION_TEST_CONCURRENCY)
    ordered_entries = [
        entry for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ]

    async def run_one(entry: dict[str, Any]) -> dict[str, Any]:
        cfg_name = entry["name"]
        async with semaphore:
            try:
                result = await runner(cfg_name, timeout=timeout)
            except XRayClientError as e:
                result = {
                    "name": cfg_name,
                    "ok": False,
                    "error": str(e),
                    **(default_failure or {}),
                }
            result["display_name"] = entry.get("display_name", cfg_name)
            result["endpoint"] = entry.get("endpoint", "")
            return result

    if not ordered_entries:
        return []
    return await asyncio.gather(*(run_one(entry) for entry in ordered_entries))


def _subscription_items() -> list[dict]:
    items = []
    if XRAY_CLIENT_SUBSCRIPTIONS_DIR.is_dir():
        for path in sorted(XRAY_CLIENT_SUBSCRIPTIONS_DIR.glob("*.key")):
            if not NAME_RE.match(path.stem):
                continue
            state = _load_subscription_state(path.stem) or {}
            entries = state.get("entries") if isinstance(state.get("entries"), list) else []
            items.append({
                "name": path.stem,
                "format": "subscription",
                "generated_count": len(entries),
                "last_refresh": state.get("last_refresh", 0),
                "last_error": state.get("last_error", ""),
            })
    return items


def _list_configs_and_groups() -> tuple[list[dict], list[dict]]:
    active = _read_active()
    generated: set[str] = set()
    config_by_name: dict[str, dict] = {}

    if XRAY_CLIENT_CONFIGS_DIR.is_dir():
        for path in sorted(XRAY_CLIENT_CONFIGS_DIR.glob("*.key")):
            if not NAME_RE.match(path.stem):
                continue
            item = _config_summary(path)
            item["active"] = item["name"] == active
            item["display_name"] = item["name"]
            item["group"] = "standalone"
            config_by_name[item["name"]] = item

    groups: list[dict] = []
    for sub in _subscription_items():
        state = _load_subscription_state(sub["name"]) or {}
        entries = state.get("entries") if isinstance(state.get("entries"), list) else []
        configs = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            generated.add(name)
            item = config_by_name.get(name)
            if not item:
                continue
            item = {**item}
            item["group"] = sub["name"]
            item["display_name"] = entry.get("display_name") or item["name"]
            item["subscription"] = sub["name"]
            item["subscription_generated"] = True
            configs.append(item)
        groups.append({
            "id": sub["name"],
            "title": sub["name"],
            "kind": "subscription",
            "last_refresh": sub["last_refresh"],
            "last_error": sub["last_error"],
            "configs": configs,
        })

    standalone = []
    for name, item in config_by_name.items():
        if name in generated:
            continue
        display = name[5:] if name.startswith("xray-") else name
        standalone.append({**item, "display_name": display, "group": "standalone"})

    if standalone:
        groups.insert(0, {
            "id": "standalone",
            "title": "Standalone",
            "kind": "standalone",
            "configs": standalone,
        })

    flat = []
    for group in groups:
        flat.extend(group.get("configs", []))
    return flat, groups


async def _select(target: str) -> tuple[bool, str]:
    script = SCRIPTS.get("select-external-tunnel")
    if not script or not script.is_file():
        return False, "select-external-tunnel helper script not deployed"
    result = await run_command(str(script), target, timeout=40)
    return result.success, result.output.strip()


async def _refresh_subscription(name: str) -> dict:
    if not NAME_RE.match(name):
        raise XRayClientError(f"invalid subscription name: {name!r}")
    key_path = XRAY_CLIENT_SUBSCRIPTIONS_DIR / f"{name}.key"
    if not key_path.is_file():
        raise XRayClientError(f"subscription not found: {name}")
    url, source_headers = subscription_source_from_key(key_path.read_text())
    if _subscription_uses_auto_hwid(url) and not _headers_have_hwid(source_headers):
        source_headers = {**source_headers, "X-HWID": _runtime_gateway_hwid()}
        _write_subscription_source(key_path, url, source_headers["X-HWID"])

    def fetch(user_agent: str) -> str:
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json,text/plain,*/*",
        }
        headers.update(source_headers)
        req = urllib.request.Request(
            url,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(2 * 1024 * 1024)
        return body.decode("utf-8", errors="replace")

    entries = []
    fetch_user_agent = ""
    last_fetch_error: XRayClientError | None = None
    last_unsupported_error: XRayClientError | None = None
    fetched_any = False
    for user_agent in SUBSCRIPTION_USER_AGENTS:
        try:
            payload = await asyncio.to_thread(fetch, user_agent)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last_fetch_error = _subscription_fetch_error(url, e)
            continue
        fetched_any = True
        raw_entries = parse_subscription_payload(payload)
        entries, rejected_entries = _supported_subscription_entries(raw_entries)
        if raw_entries and not entries and rejected_entries:
            last_unsupported_error = _unsupported_subscription_error(rejected_entries)
        if entries:
            fetch_user_agent = user_agent
            break
    if not entries:
        if not fetched_any and last_fetch_error:
            raise last_fetch_error
        if last_unsupported_error:
            raise last_unsupported_error
        raise XRayClientError(
            "subscription returned no supported VLESS/SS entries "
            "after trying app-compatible User-Agents"
        )

    XRAY_CLIENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    XRAY_CLIENT_SUBSCRIPTION_STATE_DIR.mkdir(parents=True, exist_ok=True)

    current_active = _read_active()
    new_names: set[str] = set()
    meta_entries = []
    for idx, entry in enumerate(entries, start=1):
        cfg_name = stable_config_name(name, idx, entry.display_name, entry.endpoint)
        new_names.add(cfg_name)
        path = XRAY_CLIENT_CONFIGS_DIR / f"{cfg_name}.key"
        tmp = path.with_suffix(".key.tmp")
        tmp.write_text(entry.content)
        tmp.chmod(0o600)
        os.replace(tmp, path)
        meta_entries.append({
            "name": cfg_name,
            "display_name": entry.display_name,
            "protocol": entry.protocol,
            "endpoint": entry.endpoint,
            "format": entry.format,
        })

    state_path = XRAY_CLIENT_SUBSCRIPTION_STATE_DIR / f"{name}.json"
    stale_names: set[str] = set()
    old_state = _load_subscription_state(name) or {}
    old_entries = old_state.get("entries") if isinstance(old_state.get("entries"), list) else []
    for old in old_entries:
        old_name = old.get("name") if isinstance(old, dict) else None
        if isinstance(old_name, str) and old_name not in new_names:
            stale_names.add(old_name)
    for old_path in XRAY_CLIENT_CONFIGS_DIR.glob(f"{name}-*.key"):
        if old_path.stem not in new_names:
            stale_names.add(old_path.stem)

    retained_active = ""
    removed_names = []
    for old_name in sorted(stale_names):
        if current_active and old_name == current_active:
            retained_active = old_name
            continue
        old_path = XRAY_CLIENT_CONFIGS_DIR / f"{old_name}.key"
        if old_path.exists():
            old_path.unlink()
            removed_names.append(old_name)

    state = {
        "name": name,
        "last_refresh": int(time.time()),
        "last_error": "",
        "pruned": removed_names,
        "removed_active": False,
        "retained_active": retained_active,
        "fetch_user_agent": fetch_user_agent,
        "entries": meta_entries,
    }
    tmp_state = state_path.with_suffix(".json.tmp")
    tmp_state.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp_state.chmod(0o600)
    os.replace(tmp_state, state_path)
    return state


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _speed_label(speed_bps: float) -> str:
    if speed_bps >= 1024 * 1024:
        return f"{speed_bps / 1024 / 1024:.2f} MB/s"
    if speed_bps >= 1024:
        return f"{speed_bps / 1024:.0f} KB/s"
    return f"{int(speed_bps)} B/s"


async def _run_socks_probe(name: str) -> tuple[int, Path, Path, asyncio.subprocess.Process]:
    if not NAME_RE.match(name):
        raise XRayClientError(f"invalid XRay config name: {name!r}")
    src = XRAY_CLIENT_CONFIGS_DIR / f"{name}.key"
    if not src.is_file():
        raise XRayClientError(f"XRay config not found: {name}")
    if not XRAY_BINARY.is_file():
        raise XRayClientError(f"xray binary missing: {XRAY_BINARY}")

    conf = _read_gateway_conf()
    bypass_mark = int(conf.get("XRAY_BYPASS_MARK", "0x2"), 0)
    outbound_interface = conf.get("XRAY_OUTBOUND_INTERFACE") or conf.get("LAN_INTERFACE", "eth0")
    sidecar_port = _free_port()
    bundle = load_proxy_outbound(src, bypass_mark, outbound_interface, outline_listen_port=sidecar_port)

    run_dir = Path("/run/vpngw-xray-client-ping")
    run_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    cfg_path = run_dir / f"{name}-{port}.json"
    err_path = run_dir / f"{name}-{port}.log"
    sidecar_proc: asyncio.subprocess.Process | None = None
    sidecar_cfg_path = run_dir / f"{name}-{sidecar_port}-outline.json"
    sidecar_log_path = run_dir / f"{name}-{sidecar_port}-outline.log"
    if bundle.outline_sidecar:
        if not OUTLINE_SS_BINARY.is_file():
            raise XRayClientError(f"outline ss sidecar missing: {OUTLINE_SS_BINARY}")
        sidecar_cfg_path.write_text(json.dumps(bundle.outline_sidecar, ensure_ascii=False))
        sidecar_cfg_path.chmod(0o600)
        sidecar_log = sidecar_log_path.open("w")
        sidecar_proc = await asyncio.create_subprocess_exec(
            str(OUTLINE_SS_BINARY), "-config", str(sidecar_cfg_path),
            stdout=sidecar_log,
            stderr=asyncio.subprocess.STDOUT,
        )
        await asyncio.sleep(0.4)
        sidecar_log.close()
        if sidecar_proc.returncode is not None:
            sidecar_cfg_path.unlink(missing_ok=True)
            sidecar_log_path.unlink(missing_ok=True)
            raise XRayClientError("outline ss sidecar failed to start")
    config = build_socks_probe_config(
        bundle,
        port,
        bypass_mark,
        outbound_interface,
        str(err_path),
        outline_socks_port=sidecar_port,
    )
    cfg_path.write_text(json.dumps(config, ensure_ascii=False))
    cfg_path.chmod(0o600)

    proc = await asyncio.create_subprocess_exec(
        str(XRAY_BINARY), "run", "-c", str(cfg_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await asyncio.sleep(0.8)
    proc._vpngw_sidecar_proc = sidecar_proc  # type: ignore[attr-defined]
    proc._vpngw_sidecar_cfg_path = sidecar_cfg_path  # type: ignore[attr-defined]
    proc._vpngw_sidecar_log_path = sidecar_log_path  # type: ignore[attr-defined]
    return port, cfg_path, err_path, proc


async def _stop_socks_probe(proc: asyncio.subprocess.Process, cfg_path: Path, err_path: Path) -> None:
    if proc.returncode is None:
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    cfg_path.unlink(missing_ok=True)
    err_path.unlink(missing_ok=True)
    sidecar_proc = getattr(proc, "_vpngw_sidecar_proc", None)
    if sidecar_proc and sidecar_proc.returncode is None:
        sidecar_proc.terminate()
        try:
            await asyncio.wait_for(sidecar_proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            sidecar_proc.kill()
            await sidecar_proc.wait()
    sidecar_cfg_path = getattr(proc, "_vpngw_sidecar_cfg_path", None)
    if sidecar_cfg_path:
        sidecar_cfg_path.unlink(missing_ok=True)
    sidecar_log_path = getattr(proc, "_vpngw_sidecar_log_path", None)
    if sidecar_log_path:
        sidecar_log_path.unlink(missing_ok=True)


async def _ping_config(name: str, timeout: int = 12) -> dict:
    port, cfg_path, err_path, proc = await _run_socks_probe(name)
    try:
        started_at = time.monotonic()
        curl = await run_command(
            "curl",
            "--socks5-hostname", f"127.0.0.1:{port}",
            "-4",
            "-ksS",
            "-m", str(timeout),
            "-w", "\\n%{http_code} %{time_total}",
            PING_URL,
            timeout=timeout + 3,
        )
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        lines = curl.output.strip().splitlines()
        exit_ip = lines[0].strip() if lines else ""
        http_code = ""
        time_total = 0.0
        if lines:
            tail = lines[-1].split()
            if len(tail) >= 2 and tail[0].isdigit():
                http_code = tail[0]
                try:
                    time_total = float(tail[1])
                except ValueError:
                    time_total = 0.0
                if len(lines) >= 2:
                    exit_ip = lines[-2].strip()
        return {
            "name": name,
            "isolated": True,
            "probe_backend": "xray-socks",
            "ok": curl.success and http_code == "200" and bool(exit_ip),
            "http_code": http_code,
            "time_ms": int(time_total * 1000) if time_total else elapsed_ms,
            "exit_ip": exit_ip if http_code == "200" else "",
            "error": "" if curl.success else curl.output.strip()[:300],
        }
    finally:
        await _stop_socks_probe(proc, cfg_path, err_path)


async def _hard_test_config(name: str, timeout: int = 25) -> dict:
    port, cfg_path, err_path, proc = await _run_socks_probe(name)
    try:
        curl = await run_command(
            "curl",
            "--socks5-hostname", f"127.0.0.1:{port}",
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
        ok_result = curl.success and http_code == "200" and downloaded > 0 and speed_bps > 0
        return {
            "name": name,
            "isolated": True,
            "probe_backend": "xray-socks",
            "ok": ok_result,
            "http_code": http_code,
            "bytes": downloaded,
            "time_ms": int(time_total * 1000) if time_total else 0,
            "speed_bps": int(speed_bps) if speed_bps > 0 else 0,
            "speed_mbps": round(speed_bps / 1024 / 1024, 3) if speed_bps > 0 else 0,
            "speed_label": _speed_label(speed_bps) if speed_bps > 0 else "0",
            "error": "" if ok_result else (curl.output.strip()[:300] if curl.output else "download failed"),
        }
    finally:
        await _stop_socks_probe(proc, cfg_path, err_path)


async def _hard_test_config_after_ping(name: str, timeout: int = 25) -> dict:
    ping = await _ping_config(name, timeout=8)
    if not ping.get("ok"):
        return {
            "name": name,
            "isolated": True,
            "probe_backend": "xray-socks",
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


def _xray_ping_failure(name: str, err_text: str) -> dict:
    return {
        "name": name,
        "isolated": True,
        "probe_backend": "xray-socks",
        "ok": False,
        "http_code": "",
        "time_ms": 0,
        "exit_ip": "",
        "error": err_text,
    }


def _xray_hard_test_failure(name: str, err_text: str) -> dict:
    return {
        "name": name,
        "isolated": True,
        "probe_backend": "xray-socks",
        "ok": False,
        "http_code": "",
        "bytes": 0,
        "time_ms": 0,
        "speed_bps": 0,
        "speed_mbps": 0,
        "speed_label": "0",
        "error": err_text,
    }


@router.get("/status")
async def status():
    svc = await sys_cmd.get_service_status(XRAY_CLIENT_SERVICE)
    iface = await sys_cmd.get_interface_info(XRAY_TUN_INTERFACE)
    active = _read_active()
    endpoint = ""
    protocol = ""
    if active:
        path = XRAY_CLIENT_CONFIGS_DIR / f"{active}.key"
        if path.is_file():
            summary = _config_summary(path)
            endpoint = summary.get("endpoint", "")
            protocol = summary.get("protocol", "")
    return ok({
        "service": svc.model_dump(),
        "interface": iface.model_dump(),
        "active": active,
        "endpoint": endpoint,
        "protocol": protocol,
        "external_active": _read_external_tunnel() == "xray",
    })


@router.get("/configs")
async def list_configs():
    active = _read_active()
    configs, groups = _list_configs_and_groups()
    return ok({
        "configs": configs,
        "groups": groups,
        "subscriptions": _subscription_items(),
        "active": active,
    })


@router.post("/configs")
async def upload_config(payload: ConfigUpload):
    try:
        name = _validate_config_name(payload.name or payload.filename)
        content = _validate_config_text(payload.content, payload.filename or name)
    except XRayClientError as e:
        return error(str(e))

    generated_by = _subscription_for_config(name)
    if generated_by:
        return error(
            f"config is generated by subscription {generated_by!r}; "
            "refresh or delete the subscription instead"
        )

    XRAY_CLIENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    dst = XRAY_CLIENT_CONFIGS_DIR / f"{name}.key"
    active = _read_active()
    existed = dst.exists()
    if existed and not payload.overwrite:
        return error(f"config already exists: {name}")
    if existed and name == active:
        return error("refusing to overwrite the active XRay config")

    tmp = dst.with_suffix(".key.tmp")
    tmp.write_text(content)
    tmp.chmod(0o600)
    os.replace(tmp, dst)
    item = _config_summary(dst)
    item["active"] = name == active
    item["display_name"] = name[5:] if name.startswith("xray-") else name
    item["group"] = "standalone"
    return ok({**item, "overwritten": existed})


@router.post("/enable")
async def enable():
    if not _read_active():
        return error("no active XRay config selected")
    success, log = await _select("xray")
    if not success:
        return error(f"enable xray failed: {log[:500]}")
    svc = await sys_cmd.get_service_status(XRAY_CLIENT_SERVICE)
    iface = await sys_cmd.get_interface_info(XRAY_TUN_INTERFACE)
    sys_cmd.invalidate_exit_ip_cache()
    return ok({"service": svc.model_dump(), "interface": iface.model_dump()}, log=log)


@router.post("/disable")
async def disable():
    if _read_external_tunnel() == "xray":
        success, log = await _select("none")
        if not success:
            return error(f"disable xray failed: {log[:500]}")
    else:
        log = await sys_cmd.service_action(XRAY_CLIENT_SERVICE, "stop")
    svc = await sys_cmd.get_service_status(XRAY_CLIENT_SERVICE)
    sys_cmd.invalidate_exit_ip_cache()
    return ok({"service": svc.model_dump()}, log=log)


@router.post("/configs/{name}/activate")
async def activate(name: str):
    if not NAME_RE.match(name):
        return error(f"invalid XRay config name: {name!r}")
    src = XRAY_CLIENT_CONFIGS_DIR / f"{name}.key"
    if not src.is_file():
        return error(f"XRay config not found: {name}")

    XRAY_CLIENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    XRAY_CLIENT_ACTIVE_FILE.write_text(name)

    svc = await sys_cmd.get_service_status(XRAY_CLIENT_SERVICE)
    log = ""
    if svc.active or _read_external_tunnel() == "xray":
        success, log = await _select("xray")
        if not success:
            return error(f"switch xray config failed: {log[:500]}")
    svc = await sys_cmd.get_service_status(XRAY_CLIENT_SERVICE)
    iface = await sys_cmd.get_interface_info(XRAY_TUN_INTERFACE)
    sys_cmd.invalidate_exit_ip_cache()
    return ok({
        "active": name,
        "service": svc.model_dump(),
        "interface": iface.model_dump(),
    }, log=log)


@router.delete("/configs/{name}")
async def delete_config(name: str):
    try:
        clean = _validate_config_name(name)
    except XRayClientError as e:
        return error(str(e))

    active = _read_active()
    if clean == active:
        return error("refusing to delete the active XRay config")

    generated_by = _subscription_for_config(clean)
    if generated_by:
        return error(
            f"config is generated by subscription {generated_by!r}; "
            "delete or refresh the subscription instead"
        )

    path = XRAY_CLIENT_CONFIGS_DIR / f"{clean}.key"
    if not path.is_file():
        return error(f"XRay config not found: {clean}")
    path.unlink()
    return ok({"name": clean, "removed": True})


@router.post("/configs/{name}/ping")
async def ping_config(name: str):
    if not NAME_RE.match(name):
        return error(f"invalid XRay config name: {name!r}")
    try:
        result = await _ping_config(name)
    except XRayClientError as e:
        result = _xray_ping_failure(name, str(e))
    return ok(result)


@router.post("/configs/{name}/hard-test")
async def hard_test_config(name: str, skip_ping: bool = False):
    if not NAME_RE.match(name):
        return error(f"invalid XRay config name: {name!r}")
    try:
        result = (
            await _hard_test_config(name)
            if skip_ping
            else await _hard_test_config_after_ping(name)
        )
    except XRayClientError as e:
        result = _xray_hard_test_failure(name, str(e))
    return ok(result)


@router.post("/subscriptions")
async def add_subscription(payload: SubscriptionCreate):
    name = payload.name.strip()
    if not NAME_RE.match(name):
        return error(f"invalid subscription name: {name!r}")
    try:
        url = subscription_url_from_key(payload.url)
    except XRayClientError as e:
        return error(str(e))

    XRAY_CLIENT_SUBSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = XRAY_CLIENT_SUBSCRIPTIONS_DIR / f"{name}.key"
    try:
        previous_source = path.read_text() if path.exists() else None
    except OSError:
        previous_source = None
    _write_subscription_source(path, url, _subscription_hwid(url, payload.hwid))
    try:
        state = await _refresh_subscription(name)
    except XRayClientError as e:
        if previous_source is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            tmp = path.with_suffix(".key.tmp")
            tmp.write_text(previous_source)
            tmp.chmod(0o600)
            os.replace(tmp, path)
        return error(f"subscription add failed: {e}")
    return ok({
        "subscription": name,
        "generated_count": len(state.get("entries", [])),
        "pruned_count": len(state.get("pruned", [])),
        "removed_active": bool(state.get("removed_active")),
    })


@router.post("/subscriptions/{name}/refresh")
async def refresh_subscription(name: str):
    try:
        state = await _refresh_subscription(name)
    except XRayClientError as e:
        XRAY_CLIENT_SUBSCRIPTION_STATE_DIR.mkdir(parents=True, exist_ok=True)
        if NAME_RE.match(name):
            state_path = XRAY_CLIENT_SUBSCRIPTION_STATE_DIR / f"{name}.json"
            old_state = _load_subscription_state(name) or {"name": name, "entries": []}
            old_state["last_error"] = str(e)
            state_path.write_text(json.dumps(old_state, ensure_ascii=False, indent=2))
            state_path.chmod(0o600)
        return error(f"refresh subscription failed: {e}")
    return ok({
        "subscription": name,
        "generated_count": len(state.get("entries", [])),
        "last_refresh": state.get("last_refresh", 0),
        "pruned_count": len(state.get("pruned", [])),
        "removed_active": bool(state.get("removed_active")),
        "retained_active": state.get("retained_active", ""),
    })


@router.delete("/subscriptions/{name}")
async def delete_subscription(name: str):
    try:
        result = _delete_subscription_files(name)
    except XRayClientError as e:
        return error(str(e))
    return ok(result)


@router.post("/subscriptions/{name}/ping")
async def ping_subscription(name: str):
    state = _load_subscription_state(name)
    if not state:
        return error(f"subscription has no generated state: {name}")
    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    results = await _run_subscription_checks(entries, _ping_config, timeout=8)
    return ok({"subscription": name, "results": results})


@router.post("/subscriptions/{name}/hard-test")
async def hard_test_subscription(name: str):
    state = _load_subscription_state(name)
    if not state:
        return error(f"subscription has no generated state: {name}")
    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    results = await _run_subscription_checks(
        entries,
        _hard_test_config_after_ping,
        timeout=20,
        default_failure={"speed_bps": 0, "speed_mbps": 0, "speed_label": "0"},
    )
    return ok({"subscription": name, "results": results})
