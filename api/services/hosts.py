"""Discover LAN neighbours and manage non-persistent gateway access."""

from __future__ import annotations

import ipaddress
import json
import random
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

from config import (
    GATEWAY_IP,
    HOST_ACTIVE_IPSET,
    HOST_ACTIVE_TIMEOUT_SECONDS,
    HOST_BLOCK_IPSET,
    HOST_SCAN_INTERVAL_SECONDS,
    HOST_SCAN_TIMEOUT_SECONDS,
    LAN_GATEWAY,
    LAN_INTERFACE,
    LAN_SUBNET,
)
from models.hosts import HostInfo


_fingerprints: dict[str, tuple[float, str]] = {}
_fingerprints_lock = threading.Lock()


class HostAccessError(RuntimeError):
    """A fixed host-discovery or ipset operation failed."""


def _run(args: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise HostAccessError(detail.strip()) from exc
    return result.stdout


def ensure_access_control(reset: bool = False) -> None:
    """Create the runtime-only blocked-host set and optionally empty it."""
    _run([
        "ipset", "create", HOST_BLOCK_IPSET, "hash:ip",
        "family", "inet", "maxelem", "1024", "-exist",
    ])
    if reset:
        _run(["ipset", "flush", HOST_BLOCK_IPSET])


def reset_access_control() -> None:
    """Restore the documented fail-open default after API service startup."""
    ensure_access_control(reset=True)


def _blocked_ips() -> set[str]:
    ensure_access_control()
    output = _run(["ipset", "list", HOST_BLOCK_IPSET, "-output", "save"])
    blocked = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "add" and parts[1] == HOST_BLOCK_IPSET:
            blocked.add(parts[2])
    return blocked


def _active_ips() -> set[str]:
    """Return clients seen in FORWARD during the configured activity window."""
    _run([
        "ipset", "create", HOST_ACTIVE_IPSET, "hash:ip", "family", "inet",
        "timeout", str(HOST_ACTIVE_TIMEOUT_SECONDS), "maxelem", "1024", "-exist",
    ])
    output = _run(["ipset", "list", HOST_ACTIVE_IPSET, "-output", "save"])
    active = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "add" and parts[1] == HOST_ACTIVE_IPSET:
            active.add(parts[2])
    return active


def _known_hostnames() -> dict[str, str]:
    names: dict[str, str] = {}

    for lease_path in (
        Path("/var/lib/misc/dnsmasq.leases"),
        Path("/var/lib/dnsmasq/dnsmasq.leases"),
    ):
        try:
            lines = lease_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) >= 4 and parts[3] != "*":
                names[parts[2]] = parts[3].rstrip(".")

    try:
        hosts_lines = Path("/etc/hosts").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        hosts_lines = []
    for line in hosts_lines:
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2:
            try:
                ipaddress.ip_address(parts[0])
            except ValueError:
                continue
            names.setdefault(parts[0], parts[1].rstrip("."))
    return names


def _reverse_hostname(ip: str) -> str:
    try:
        output = _run(["getent", "hosts", ip], timeout=0.6)
    except HostAccessError:
        return ""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            return parts[1].rstrip(".")
    return ""


def _fingerprint_label(xml_text: str) -> str:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return "Unknown"

    os_match = root.find(".//osmatch")
    os_class = root.find(".//osclass")
    match_name = os_match.get("name", "").strip() if os_match is not None else ""
    device_type = os_class.get("type", "").strip() if os_class is not None else ""
    if match_name and device_type:
        return f"{match_name} · {device_type}"
    if match_name:
        return match_name
    if os_class is not None:
        os_name = " ".join(
            value for value in (
                os_class.get("vendor", "").strip(),
                os_class.get("osfamily", "").strip(),
                os_class.get("osgen", "").strip(),
            ) if value
        )
        if os_name and device_type:
            return f"{os_name} · {device_type}"
        if os_name or device_type:
            return os_name or device_type

    mac_address = root.find('.//address[@addrtype="mac"]')
    if mac_address is not None and mac_address.get("vendor"):
        return mac_address.get("vendor", "").strip()
    return "Unknown"


def fingerprint_due(ip: str) -> bool:
    with _fingerprints_lock:
        cached = _fingerprints.get(ip)
    return not cached or time.monotonic() - cached[0] >= HOST_SCAN_INTERVAL_SECONDS


def scan_host_fingerprint(ip: str) -> str:
    """Run one bounded nmap OS probe and update the in-memory cache."""
    if not fingerprint_due(ip):
        with _fingerprints_lock:
            return _fingerprints[ip][1]

    if shutil.which("nmap") is None:
        label = "nmap unavailable"
    else:
        try:
            output = _run([
                "nmap", "-O", "-F", "--osscan-limit", "--max-os-tries", "1",
                "-T3", "-n", "-Pn", "--host-timeout",
                f"{HOST_SCAN_TIMEOUT_SECONDS}s", "-oX", "-", ip,
            ], timeout=HOST_SCAN_TIMEOUT_SECONDS + 5)
            label = _fingerprint_label(output)
        except HostAccessError:
            label = "Unknown"

    with _fingerprints_lock:
        _fingerprints[ip] = (time.monotonic(), label)
    return label


def fingerprint_for(ip: str) -> str:
    with _fingerprints_lock:
        cached = _fingerprints.get(ip)
    return cached[1] if cached else ""


def shuffled_due_hosts() -> list[str]:
    hosts = [host.ip for host in list_hosts() if fingerprint_due(host.ip)]
    random.shuffle(hosts)
    return hosts


def list_hosts() -> list[HostInfo]:
    """Return usable IPv4 neighbours on the configured LAN interface."""
    try:
        network = ipaddress.ip_network(LAN_SUBNET, strict=False)
    except ValueError as exc:
        raise HostAccessError(f"invalid LAN_SUBNET: {LAN_SUBNET}") from exc

    try:
        neighbours = json.loads(_run(["ip", "-j", "neigh", "show", "dev", LAN_INTERFACE]))
    except json.JSONDecodeError as exc:
        raise HostAccessError("ip neigh returned invalid JSON") from exc

    blocked = _blocked_ips()
    active = _active_ips()
    known_names = _known_hostnames()
    rows: list[dict[str, str]] = []
    excluded = {GATEWAY_IP, LAN_GATEWAY}

    for neighbour in neighbours:
        ip = str(neighbour.get("dst", ""))
        mac = str(neighbour.get("lladdr", "")).lower()
        state = neighbour.get("state", [])
        states = {state} if isinstance(state, str) else set(state)
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            address.version != 4
            or address not in network
            or ip in excluded
            or ip not in active
            or not mac
            or states.intersection({"FAILED", "INCOMPLETE", "NOARP"})
        ):
            continue
        rows.append({"ip": ip, "mac": mac})

    unresolved = [row["ip"] for row in rows if row["ip"] not in known_names]
    if unresolved:
        with ThreadPoolExecutor(max_workers=min(8, len(unresolved))) as pool:
            resolved = pool.map(_reverse_hostname, unresolved)
        for ip, hostname in zip(unresolved, resolved):
            if hostname:
                known_names[ip] = hostname

    hosts = [
        HostInfo(
            ip=row["ip"],
            hostname=known_names.get(row["ip"], ""),
            mac=row["mac"],
            device=fingerprint_for(row["ip"]),
            vpn_allowed=row["ip"] not in blocked,
        )
        for row in rows
    ]
    hosts.sort(key=lambda host: int(ipaddress.ip_address(host.ip)))
    return hosts


def set_host_access(ip: str, enabled: bool) -> HostInfo:
    """Allow all forwarding or restrict one LAN host to private networks."""
    try:
        address = ipaddress.ip_address(ip)
        network = ipaddress.ip_network(LAN_SUBNET, strict=False)
    except ValueError as exc:
        raise HostAccessError(f"invalid host IP: {ip}") from exc

    if (
        address.version != 4
        or address not in network
        or address in {network.network_address, network.broadcast_address}
        or ip in {GATEWAY_IP, LAN_GATEWAY}
    ):
        raise HostAccessError(f"host IP is outside the controllable LAN range: {ip}")

    ensure_access_control()
    action = "del" if enabled else "add"
    _run(["ipset", action, HOST_BLOCK_IPSET, ip, "-exist"])

    host = next((item for item in list_hosts() if item.ip == ip), None)
    if host:
        host.vpn_allowed = enabled
        return host
    return HostInfo(ip=ip, mac="", vpn_allowed=enabled)
