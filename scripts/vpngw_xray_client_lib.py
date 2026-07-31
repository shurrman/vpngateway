#!/usr/bin/env python3
"""Shared helpers for outbound XRay client runtime configs."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROXY_PROTOCOLS = {"vless", "shadowsocks"}
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
OUTLINE_SS_LOCAL_HOST = "127.0.0.1"
OUTLINE_SS_LOCAL_PORT = 19081


class XRayClientError(RuntimeError):
    pass


@dataclass
class SubscriptionEntry:
    display_name: str
    content: str
    protocol: str
    endpoint: str
    format: str


@dataclass
class OutboundBundle:
    proxy: dict[str, Any]
    extra_outbounds: list[dict[str, Any]]
    outline_sidecar: dict[str, Any] | None = None


def b64decode_loose(text: str) -> str:
    padded = text.strip().replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    return base64.b64decode(padded).decode("utf-8")


def one(query: dict[str, list[str]], key: str, default: str = "") -> str:
    vals = query.get(key)
    return vals[0] if vals else default


def raw_query_bytes(query: str, key: str) -> bytes:
    for part in query.split("&"):
        raw_key, sep, raw_val = part.partition("=")
        if not sep:
            continue
        if urllib.parse.unquote_plus(raw_key) == key:
            return urllib.parse.unquote_to_bytes(raw_val)
    return b""


def bypass_sockopt(bypass_mark: int, outbound_interface: str) -> dict[str, Any]:
    sockopt: dict[str, Any] = {"mark": bypass_mark}
    if outbound_interface:
        sockopt["interface"] = outbound_interface
    return sockopt


def with_bypass_sockopt(
    outbound: dict[str, Any],
    bypass_mark: int,
    outbound_interface: str,
    tag: str | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(outbound)
    if tag is not None:
        out["tag"] = tag
    stream = out.setdefault("streamSettings", {})
    sockopt = stream.setdefault("sockopt", {})
    sockopt["mark"] = bypass_mark
    if outbound_interface:
        sockopt["interface"] = outbound_interface
    return out


def with_bypass_mark(
    outbound: dict[str, Any],
    bypass_mark: int,
    outbound_interface: str,
) -> dict[str, Any]:
    return with_bypass_sockopt(outbound, bypass_mark, outbound_interface, tag="proxy")


def _dialer_proxy_tag(outbound: dict[str, Any]) -> str:
    stream = outbound.get("streamSettings")
    if not isinstance(stream, dict):
        return ""
    sockopt = stream.get("sockopt")
    if not isinstance(sockopt, dict):
        return ""
    tag = sockopt.get("dialerProxy")
    return tag if isinstance(tag, str) else ""


def _collect_dialer_proxy_outbounds(
    proxy: dict[str, Any],
    outbounds: list[Any],
    bypass_mark: int,
    outbound_interface: str,
) -> list[dict[str, Any]]:
    by_tag = {
        outbound.get("tag"): outbound
        for outbound in outbounds
        if isinstance(outbound, dict) and isinstance(outbound.get("tag"), str)
    }
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = proxy
    while True:
        tag = _dialer_proxy_tag(current)
        if not tag:
            return collected
        if tag in seen:
            raise XRayClientError(f"dialerProxy cycle detected at outbound tag: {tag}")
        seen.add(tag)
        source = by_tag.get(tag)
        if not isinstance(source, dict):
            raise XRayClientError(f"dialerProxy outbound not found: {tag}")
        out = with_bypass_sockopt(source, bypass_mark, outbound_interface)
        collected.append(out)
        current = out


def find_proxy_outbound_bundle(
    config: dict[str, Any],
    bypass_mark: int,
    outbound_interface: str,
) -> OutboundBundle:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        raise XRayClientError("JSON config has no outbounds array")
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        if outbound.get("protocol") in PROXY_PROTOCOLS:
            proxy = with_bypass_mark(outbound, bypass_mark, outbound_interface)
            extra = _collect_dialer_proxy_outbounds(proxy, outbounds, bypass_mark, outbound_interface)
            return OutboundBundle(proxy=proxy, extra_outbounds=extra)
    raise XRayClientError("JSON config has no vless/shadowsocks outbound")


def find_proxy_outbound(
    config: dict[str, Any],
    bypass_mark: int,
    outbound_interface: str,
) -> dict[str, Any]:
    return find_proxy_outbound_bundle(config, bypass_mark, outbound_interface).proxy


def parse_vless_uri(uri: str, bypass_mark: int, outbound_interface: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme != "vless":
        raise XRayClientError("not a vless:// URI")
    uuid = urllib.parse.unquote(parsed.username or "")
    host = parsed.hostname
    port = parsed.port
    if not uuid or not host or not port:
        raise XRayClientError("vless URI must contain uuid, host, and port")

    query = urllib.parse.parse_qs(parsed.query)
    user: dict[str, Any] = {
        "id": uuid,
        "encryption": one(query, "encryption", "none"),
        "level": 0,
    }
    flow = one(query, "flow")
    if flow:
        user["flow"] = flow

    network = one(query, "type", "tcp") or "tcp"
    security = one(query, "security", "none") or "none"
    stream: dict[str, Any] = {
        "network": network,
        "security": security,
        "sockopt": bypass_sockopt(bypass_mark, outbound_interface),
    }

    if security == "reality":
        reality: dict[str, Any] = {}
        if one(query, "sni"):
            reality["serverName"] = one(query, "sni")
        if one(query, "fp"):
            reality["fingerprint"] = one(query, "fp")
        if one(query, "pbk"):
            reality["publicKey"] = one(query, "pbk")
        if one(query, "sid"):
            reality["shortId"] = one(query, "sid")
        if one(query, "spx"):
            reality["spiderX"] = urllib.parse.unquote(one(query, "spx"))
        stream["realitySettings"] = reality
    elif security == "tls":
        tls: dict[str, Any] = {}
        if one(query, "sni"):
            tls["serverName"] = one(query, "sni")
        if one(query, "fp"):
            tls["fingerprint"] = one(query, "fp")
        if one(query, "alpn"):
            tls["alpn"] = one(query, "alpn").split(",")
        stream["tlsSettings"] = tls

    path = urllib.parse.unquote(one(query, "path"))
    host_header = one(query, "host")
    service_name = one(query, "serviceName")
    mode = one(query, "mode")

    if network == "ws":
        ws: dict[str, Any] = {}
        if path:
            ws["path"] = path
        if host_header:
            ws["headers"] = {"Host": host_header}
        stream["wsSettings"] = ws
    elif network == "grpc":
        grpc: dict[str, Any] = {}
        if service_name:
            grpc["serviceName"] = service_name
        stream["grpcSettings"] = grpc
    elif network == "xhttp":
        xhttp: dict[str, Any] = {}
        if path:
            xhttp["path"] = path
        if host_header:
            xhttp["host"] = host_header
        if mode:
            xhttp["mode"] = mode
        stream["xhttpSettings"] = xhttp
    elif network == "httpupgrade":
        hup: dict[str, Any] = {}
        if path:
            hup["path"] = path
        if host_header:
            hup["host"] = host_header
        stream["httpupgradeSettings"] = hup

    return {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": host,
                "port": port,
                "users": [user],
            }],
        },
        "streamSettings": stream,
    }


def parse_ss_userinfo(userinfo: str) -> tuple[str, str]:
    decoded = urllib.parse.unquote(userinfo)
    if ":" not in decoded:
        decoded = b64decode_loose(decoded)
    if ":" not in decoded:
        raise XRayClientError("ss URI userinfo must contain method:password")
    method, password = decoded.split(":", 1)
    if not method or not password:
        raise XRayClientError("ss URI method/password is empty")
    return method, password


def parse_ss_uri(
    uri: str,
    bypass_mark: int,
    outbound_interface: str,
    outline_listen_host: str = OUTLINE_SS_LOCAL_HOST,
    outline_listen_port: int = OUTLINE_SS_LOCAL_PORT,
) -> OutboundBundle:
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme != "ss":
        raise XRayClientError("not an ss:// URI")

    host = parsed.hostname
    port = parsed.port
    userinfo = parsed.username or ""

    if host and port and userinfo:
        method, password = parse_ss_userinfo(userinfo)
    else:
        blob = uri[5:].split("#", 1)[0].split("?", 1)[0]
        decoded = b64decode_loose(blob)
        creds, _, endpoint = decoded.rpartition("@")
        if not creds or not endpoint or ":" not in endpoint:
            raise XRayClientError("unsupported ss URI form")
        method, password = parse_ss_userinfo(creds)
        host, port_text = endpoint.rsplit(":", 1)
        port = int(port_text)

    if not host or not port:
        raise XRayClientError("ss URI must contain host and port")

    query = urllib.parse.parse_qs(parsed.query)
    if one(query, "prefix"):
        prefix = raw_query_bytes(parsed.query, "prefix")
        if not prefix:
            raise XRayClientError("ss URI prefix is empty")
        return OutboundBundle(
            proxy={
                "tag": "proxy",
                "protocol": "socks",
                "settings": {
                    "servers": [{
                        "address": outline_listen_host,
                        "port": outline_listen_port,
                    }],
                },
                "streamSettings": {"sockopt": {"mark": bypass_mark}},
            },
            extra_outbounds=[],
            outline_sidecar={
                "listen": f"{outline_listen_host}:{outline_listen_port}",
                "server": f"{host}:{port}",
                "method": method,
                "password": password,
                "prefix_b64": base64.b64encode(prefix).decode("ascii"),
                "outbound_interface": outbound_interface,
                "mark": bypass_mark,
            },
        )
    settings: dict[str, Any] = {
        "address": host,
        "port": port,
        "method": method,
        "password": password,
        "level": 0,
    }
    if one(query, "uot"):
        settings["uot"] = one(query, "uot").lower() in ("1", "true", "yes")

    return OutboundBundle(
        proxy={
            "tag": "proxy",
            "protocol": "shadowsocks",
            "settings": settings,
            "streamSettings": {"sockopt": bypass_sockopt(bypass_mark, outbound_interface)},
        },
        extra_outbounds=[],
    )


def load_proxy_outbound(
    source: Path,
    bypass_mark: int,
    outbound_interface: str,
    outline_listen_port: int = OUTLINE_SS_LOCAL_PORT,
) -> OutboundBundle:
    text = source.read_text().strip()
    return load_proxy_outbound_text(text, source.name, bypass_mark, outbound_interface, outline_listen_port)


def load_proxy_outbound_text(
    text: str,
    label: str,
    bypass_mark: int,
    outbound_interface: str,
    outline_listen_port: int = OUTLINE_SS_LOCAL_PORT,
) -> OutboundBundle:
    if not text:
        raise XRayClientError(f"empty config: {label}")
    if text.startswith("{"):
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            raise XRayClientError(f"{label} is not valid JSON: {e}") from e
        if not isinstance(config, dict):
            raise XRayClientError("JSON config must be an object")
        return find_proxy_outbound_bundle(config, bypass_mark, outbound_interface)
    first_line = text.splitlines()[0].strip()
    if first_line.startswith("vless://"):
        return OutboundBundle(parse_vless_uri(first_line, bypass_mark, outbound_interface), [])
    if first_line.startswith("ss://"):
        return parse_ss_uri(first_line, bypass_mark, outbound_interface, outline_listen_port=outline_listen_port)
    raise XRayClientError(f"unsupported XRay client config format: {label}")


def outbound_summary(outbound: dict[str, Any]) -> tuple[str, str]:
    proto = outbound.get("protocol", "")
    endpoint = ""
    settings = outbound.get("settings") or {}
    if proto == "vless":
        vnext = settings.get("vnext") or []
        if vnext and isinstance(vnext[0], dict):
            host = vnext[0].get("address", "")
            port = vnext[0].get("port", "")
            endpoint = f"{host}:{port}" if host and port else host
    elif proto == "shadowsocks":
        host = settings.get("address", "")
        port = settings.get("port", "")
        servers = settings.get("servers") or []
        if servers and isinstance(servers[0], dict):
            host = servers[0].get("address", host)
            port = servers[0].get("port", port)
        endpoint = f"{host}:{port}" if host and port else host
    return ("ss" if proto == "shadowsocks" else proto, endpoint)


def summarize_text(text: str, label: str) -> dict[str, str]:
    if not text.strip():
        return {"protocol": "unknown", "format": "empty", "endpoint": ""}
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return {"protocol": "unknown", "format": "json-invalid", "endpoint": ""}
        if not isinstance(data, dict):
            return {"protocol": "unknown", "format": "json-invalid", "endpoint": ""}
        try:
            proxy = find_proxy_outbound(data, 0, "")
        except XRayClientError:
            return {"protocol": "unknown", "format": "json", "endpoint": ""}
        protocol, endpoint = outbound_summary(proxy)
        return {"protocol": protocol, "format": "json", "endpoint": endpoint}
    first = stripped.splitlines()[0].strip()
    if first.startswith("vless://"):
        parsed = urllib.parse.urlsplit(first)
        endpoint = f"{parsed.hostname}:{parsed.port}" if parsed.hostname and parsed.port else ""
        return {"protocol": "vless", "format": "uri", "endpoint": endpoint}
    if first.startswith("ss://"):
        parsed = urllib.parse.urlsplit(first)
        endpoint = ""
        if parsed.hostname and parsed.port:
            endpoint = f"{parsed.hostname}:{parsed.port}"
        query = urllib.parse.parse_qs(parsed.query)
        if one(query, "prefix"):
            return {
                "protocol": "ss",
                "format": "uri-outline",
                "endpoint": endpoint,
                "requires": "outline-ss-local",
            }
        return {"protocol": "ss", "format": "uri", "endpoint": endpoint}
    return {"protocol": "unknown", "format": "unknown", "endpoint": ""}


def build_tun_config(
    bundle: OutboundBundle,
    tun_if: str,
    tun_address: str,
    bypass_mark: int,
    outbound_interface: str,
) -> dict[str, Any]:
    direct = {
        "tag": "direct",
        "protocol": "freedom",
        "settings": {"domainStrategy": "UseIPv4"},
        "streamSettings": {"sockopt": bypass_sockopt(bypass_mark, outbound_interface)},
    }
    rules = []
    if bundle.outline_sidecar:
        # The Outline sidecar currently handles TCP SOCKS CONNECT. Drop QUIC
        # early so browsers fall back to HTTPS-over-TCP instead of retrying UDP.
        rules.append({
            "type": "field",
            "network": "udp",
            "port": "443",
            "outboundTag": "blocked",
        })
    rules.append({"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"})
    return {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/client-access.log",
            "error": "/var/log/xray/client-error.log",
        },
        "inbounds": [{
            "tag": "xray-tun-in",
            "protocol": "tun",
            "settings": {
                "name": tun_if,
                "mtu": 1500,
                "gateway": [tun_address],
                "userLevel": 0,
            },
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
            },
        }],
        "outbounds": [
            bundle.proxy,
            *bundle.extra_outbounds,
            direct,
            {"tag": "blocked", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": rules,
        },
    }


def build_socks_probe_config(
    bundle: OutboundBundle,
    port: int,
    bypass_mark: int,
    outbound_interface: str,
    log_file: str,
    outline_socks_port: int = OUTLINE_SS_LOCAL_PORT,
) -> dict[str, Any]:
    proxy = copy.deepcopy(bundle.proxy)
    if bundle.outline_sidecar:
        servers = proxy.get("settings", {}).get("servers", [])
        if servers and isinstance(servers[0], dict):
            servers[0]["port"] = outline_socks_port
    direct = {
        "tag": "direct",
        "protocol": "freedom",
        "settings": {"domainStrategy": "UseIPv4"},
        "streamSettings": {"sockopt": bypass_sockopt(bypass_mark, outbound_interface)},
    }
    return {
        "log": {
            "loglevel": "warning",
            "access": "none",
            "error": log_file,
        },
        "inbounds": [{
            "tag": "probe-socks",
            "listen": "127.0.0.1",
            "port": port,
            "protocol": "socks",
            "settings": {"udp": False, "auth": "noauth"},
        }],
        "outbounds": [proxy, *bundle.extra_outbounds, direct, {"tag": "blocked", "protocol": "blackhole"}],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}],
        },
    }


def subscription_url_from_key(text: str) -> str:
    url, _headers = subscription_source_from_key(text)
    return url


def subscription_source_from_key(text: str) -> tuple[str, dict[str, str]]:
    raw = text.strip()
    headers: dict[str, str] = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise XRayClientError(f"subscription key JSON is invalid: {e}") from e
        if not isinstance(data, dict):
            raise XRayClientError("subscription key JSON must be an object")
        raw_url = data.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise XRayClientError("subscription key JSON must contain url")
        raw = raw_url.strip()
        source_headers = data.get("headers")
        if isinstance(source_headers, dict):
            hwid = source_headers.get("X-HWID") or source_headers.get("X-Hwid")
            if isinstance(hwid, str) and hwid.strip():
                headers["X-HWID"] = hwid.strip()
        for key in ("hwid", "x_hwid", "x-hwid"):
            hwid = data.get(key)
            if isinstance(hwid, str) and hwid.strip():
                headers["X-HWID"] = hwid.strip()
    if raw.startswith("happ://add/"):
        raw = raw[len("happ://add/"):]
    raw = urllib.parse.unquote(raw)
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise XRayClientError("subscription key must contain an http(s) URL")
    return raw, headers


def slugify(text: str, fallback: str = "node") -> str:
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if not ascii_text:
        ascii_text = fallback
    return ascii_text[:32].strip("-") or fallback


def stable_config_name(subscription: str, index: int, display_name: str, endpoint: str) -> str:
    slug = slugify(display_name, slugify(endpoint, "node"))
    digest = hashlib.sha1(f"{display_name}|{endpoint}".encode()).hexdigest()[:6]
    prefix = f"{subscription}-{index:02d}-"
    max_slug = max(8, 64 - len(prefix) - 1 - len(digest))
    name = f"{prefix}{slug[:max_slug].strip('-')}-{digest}"
    return name[:64]


def display_name_from_uri(uri: str) -> str:
    parsed = urllib.parse.urlsplit(uri)
    frag = urllib.parse.unquote(parsed.fragment or "").strip()
    if frag:
        return frag
    host = parsed.hostname or "node"
    return host


def parse_subscription_payload(payload: str) -> list[SubscriptionEntry]:
    text = payload.strip()
    if not text:
        return []

    candidates: list[str] = []
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            entries: list[SubscriptionEntry] = []
            for idx, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    continue
                content = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                summary = summarize_text(content, f"subscription[{idx}]")
                if summary["protocol"] == "unknown":
                    continue
                display = (
                    str(item.get("remarks") or item.get("name") or item.get("ps") or "").strip()
                    or summary["endpoint"]
                    or f"node-{idx:02d}"
                )
                entries.append(SubscriptionEntry(
                    display_name=display,
                    content=content + "\n",
                    protocol=summary["protocol"],
                    endpoint=summary["endpoint"],
                    format=summary["format"],
                ))
            return entries
        if isinstance(data, dict):
            content = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            summary = summarize_text(content, "subscription")
            if summary["protocol"] != "unknown":
                display = str(data.get("remarks") or data.get("name") or data.get("ps") or "").strip()
                return [SubscriptionEntry(display or summary["endpoint"] or "node", content + "\n", summary["protocol"], summary["endpoint"], summary["format"])]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1 and not text.startswith(("vless://", "ss://")):
        try:
            decoded = b64decode_loose(text)
        except Exception:
            decoded = ""
        if decoded:
            candidates = [line.strip() for line in decoded.splitlines() if line.strip()]
    if not candidates:
        candidates = lines if lines else [text]

    entries = []
    for idx, item in enumerate(candidates, start=1):
        if not item.startswith(("vless://", "ss://")):
            continue
        summary = summarize_text(item, f"subscription[{idx}]")
        entries.append(SubscriptionEntry(
            display_name=display_name_from_uri(item),
            content=item + "\n",
            protocol=summary["protocol"],
            endpoint=summary["endpoint"],
            format=summary["format"],
        ))
    return entries
