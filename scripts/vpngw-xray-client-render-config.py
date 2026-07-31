#!/usr/bin/env python3
"""Render XRay client TUN config from the active runtime *.key file.

Runtime layout:
  /opt/vpngateway/config/xray-client/configs/*.key  user supplied endpoints
  /opt/vpngateway/config/xray-client/configs/.active
  /opt/vpngateway/config/xray-client/client.json    generated, mode 600

Supported endpoint inputs:
  * full XRay JSON config with a vless/shadowsocks outbound;
  * vless:// share URI;
  * ss:// Shadowsocks SIP002 URI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

from vpngw_xray_client_lib import (
    NAME_RE,
    XRayClientError,
    build_tun_config,
    load_proxy_outbound,
)

CONFIG_DIR = Path("/opt/vpngateway/config")
XRAY_CLIENT_DIR = CONFIG_DIR / "xray-client"
CONFIGS_DIR = XRAY_CLIENT_DIR / "configs"
ACTIVE_FILE = CONFIGS_DIR / ".active"
OUT = XRAY_CLIENT_DIR / "client.json"
OUTLINE_SIDECAR_OUT = XRAY_CLIENT_DIR / "outline-ss-local.json"
GATEWAY_CONF = CONFIG_DIR / "vpngateway.conf"


def die(msg: str) -> "NoReturn":
    print(f"render-xray-client: error: {msg}", file=sys.stderr)
    sys.exit(1)


def read_gateway_conf() -> dict[str, str]:
    conf: dict[str, str] = {}
    if GATEWAY_CONF.exists():
        for raw in GATEWAY_CONF.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            conf[key.strip()] = val.strip().strip('"').strip("'")
    return conf


def active_source() -> Path:
    try:
        name = ACTIVE_FILE.read_text().strip()
    except FileNotFoundError:
        die(f"active selector missing: {ACTIVE_FILE}")
    if not NAME_RE.match(name):
        die(f"invalid active XRay config name: {name!r}")
    path = CONFIGS_DIR / f"{name}.key"
    if not path.is_file():
        die(f"active XRay config not found: {path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="specific *.key to render")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--check", action="store_true", help="parse only, do not write")
    args = parser.parse_args()

    conf = read_gateway_conf()
    tun_if = conf.get("XRAY_TUN_INTERFACE", "xray0")
    tun_address = conf.get("XRAY_TUN_ADDRESS", "198.18.0.1/30")
    bypass_mark = int(conf.get("XRAY_BYPASS_MARK", "0x2"), 0)
    outbound_interface = conf.get("XRAY_OUTBOUND_INTERFACE") or conf.get("LAN_INTERFACE", "eth0")

    source = args.source or active_source()
    try:
        bundle = load_proxy_outbound(source, bypass_mark, outbound_interface)
    except XRayClientError as e:
        die(str(e))
    config = build_tun_config(bundle, tun_if, tun_address, bypass_mark, outbound_interface)

    if args.check:
        print(json.dumps({
            "source": source.name,
            "protocol": bundle.proxy.get("protocol"),
            "tun_interface": tun_if,
            "outbound_interface": outbound_interface,
            "extra_outbounds": [out.get("tag", "") for out in bundle.extra_outbounds],
            "outline_sidecar": bool(bundle.outline_sidecar),
        }, ensure_ascii=False))
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    tmp.chmod(0o600)
    os.replace(tmp, args.output)
    if bundle.outline_sidecar:
        sidecar_tmp = OUTLINE_SIDECAR_OUT.with_suffix(OUTLINE_SIDECAR_OUT.suffix + ".tmp")
        sidecar_tmp.write_text(json.dumps(bundle.outline_sidecar, indent=2, ensure_ascii=False))
        sidecar_tmp.chmod(0o600)
        os.replace(sidecar_tmp, OUTLINE_SIDECAR_OUT)
    else:
        OUTLINE_SIDECAR_OUT.unlink(missing_ok=True)
    print(f"render-xray-client: wrote {args.output} from {source.name}")


if __name__ == "__main__":
    main()
