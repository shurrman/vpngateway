#!/usr/bin/env python3
"""Render /opt/vpngateway/config/xray/server.json from server-params.json
and clients.json.

Called by:
  * vpngw-xray.service        — ExecStartPre, so every restart picks up
                                changes to the client list.
  * vpngw-xray-add-client.py  — after appending a client.
  * vpngw-xray-remove-client.py — after revoking a client.
  * vpngw-xray-init.sh        — at first install.

The rendered config is the canonical schema; the *.template file in the
repo is a human-readable mirror, not consumed at runtime.

NB: writes atomically (write-to-tmp + rename) so a partial flush can't
leave xray with a half-parsed JSON.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

XRAY_DIR = Path("/opt/vpngateway/config/xray")
PARAMS = XRAY_DIR / "server-params.json"
CLIENTS = XRAY_DIR / "clients.json"
OUT = XRAY_DIR / "server.json"

# Match api/config.py — single source of truth.
INTERNAL_PORT = 8443
STATS_PORT = 10085


def die(msg: str) -> "NoReturn":
    print(f"render-config: error: {msg}", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        die(f"required file is missing: {path}")
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")


def build_config(params: dict, clients: list[dict]) -> dict:
    """Assemble the xray server.json structure.

    Schema kept in lockstep with config/xray/server.json.template; if you
    diverge, update both.
    """
    if not clients:
        # xray will refuse to start with zero clients on a VLESS inbound.
        # Emit a single dummy client so the service comes up — operator
        # then adds real ones via the API.
        clients = [{
            "uuid": "00000000-0000-0000-0000-000000000000",
            "name": "_placeholder",
        }]

    xray_clients = [
        {
            "id": c["uuid"],
            "level": 0,
            "email": f"{c.get('name', 'unnamed')}@vpngateway",
        }
        for c in clients
    ]

    return {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error":  "/var/log/xray/error.log",
        },
        "stats": {},
        "policy": {
            "system": {
                "statsInboundUplink":   True,
                "statsInboundDownlink": True,
                "statsOutboundUplink":  True,
                "statsOutboundDownlink": True,
            },
            # Per-user accounting — every client is level=0 (see below),
            # so this enables stats names like
            #   user>>><email>>>>traffic>>>(up|down)link
            # which the stats parser surfaces in the `users` dict.
            "levels": {
                "0": {"statsUserUplink": True, "statsUserDownlink": True},
            },
        },
        "api": {
            "tag": "api",
            "services": ["StatsService"],
        },
        "inbounds": [
            {
                "tag": "api",
                "listen": "127.0.0.1",
                "port": STATS_PORT,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
            },
            {
                "tag": "vless-in",
                "listen": "127.0.0.1",
                "port": INTERNAL_PORT,
                "protocol": "vless",
                "settings": {
                    "clients": xray_clients,
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "none",
                    "xhttpSettings": {
                        "path": params["xhttp_path"],
                        "host": params["public_host"],
                        "mode": "auto",
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"],
                },
            },
        ],
        "outbounds": [
            {
                # SO_MARK=1 routes every xray-originated packet via amn0
                # (existing fwmark 0x1 -> table 100 rule). domainStrategy
                # UseIP forces DNS resolution before the connect so the
                # resolver runs locally on the gateway, not on the
                # tunnel-far-end (which would expose client DNS).
                "tag": "amnezia",
                "protocol": "freedom",
                "settings": {"domainStrategy": "UseIP"},
                "streamSettings": {"sockopt": {"mark": 1}},
            },
            {
                "tag": "blocked",
                "protocol": "blackhole",
            },
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"},
            ],
        },
    }


def main() -> None:
    params = load_json(PARAMS)
    clients = load_json(CLIENTS)
    if not isinstance(params, dict):
        die(f"{PARAMS} must be a JSON object")
    if not isinstance(clients, list):
        die(f"{CLIENTS} must be a JSON list")
    for key in ("xhttp_path", "public_host"):
        if not params.get(key):
            die(f"{PARAMS} is missing required key: {key}")

    cfg = build_config(params, clients)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    tmp.chmod(0o600)
    os.replace(tmp, OUT)
    print(f"render-config: wrote {OUT} ({len(clients)} client(s))")


if __name__ == "__main__":
    main()
