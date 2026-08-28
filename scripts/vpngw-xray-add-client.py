#!/usr/bin/env python3
"""Add a new VLESS client to /opt/vpngateway/config/xray/clients.json,
re-render server.json, and (optionally) restart vpngw-xray so the new
UUID is honoured immediately.

Usage:
  vpngw-xray-add-client.py --name <label>          # adds + restarts service
  vpngw-xray-add-client.py --name <label> --no-restart
                                                   # used by init script
                                                   # where the service
                                                   # is not yet started
  vpngw-xray-add-client.py --name <label> --json   # machine-readable
                                                   # output for the API

Prints (text mode) the client UUID and a copy-pasteable vless:// share URL.
In --json mode prints {name, uuid, created, share_url}.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
import uuid
from pathlib import Path

XRAY_DIR = Path("/opt/vpngateway/config/xray")
PARAMS_FILE = XRAY_DIR / "server-params.json"
CLIENTS_FILE = XRAY_DIR / "clients.json"
RENDER_SCRIPT = Path("/opt/vpngateway/scripts/vpngw-xray-render-config.py")
SNAPSHOT_SCRIPT = Path("/opt/vpngateway/scripts/vpngw-xray-stats-snapshot.py")

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def die(msg: str, code: int = 1) -> "NoReturn":
    print(f"add-client: error: {msg}", file=sys.stderr)
    sys.exit(code)


def share_url(uuid_str: str, name: str, params: dict) -> str:
    """Assemble the vless://... URI a client app can import.

    Format (compatible with v2rayN / NekoBox / Hiddify / Streisand):
      vless://<uuid>@<host>:443
              ?encryption=none
              &security=tls
              &sni=<host>
              &alpn=h2,http%2F1.1
              &type=xhttp
              &host=<host>
              &path=<urlencoded-path>
              &mode=auto
              #<remark>
    """
    host = params["public_host"]
    path = params["xhttp_path"]
    qs = urllib.parse.urlencode({
        "encryption": "none",
        "security":   "tls",
        "sni":        host,
        "alpn":       "h2,http/1.1",
        "type":       "xhttp",
        "host":       host,
        "path":       path,
        "mode":       "auto",
    }, quote_via=urllib.parse.quote)
    remark = urllib.parse.quote(f"{host}-{name}")
    return f"vless://{uuid_str}@{host}:443?{qs}#{remark}"


def load_clients() -> list[dict]:
    if not CLIENTS_FILE.exists():
        return []
    return json.loads(CLIENTS_FILE.read_text())


def save_clients(clients: list[dict]) -> None:
    tmp = CLIENTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clients, indent=2, ensure_ascii=False))
    tmp.chmod(0o600)
    os.replace(tmp, CLIENTS_FILE)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True,
                   help="human label, [A-Za-z0-9_-]{1,32}")
    p.add_argument("--no-restart", action="store_true",
                   help="skip systemctl restart vpngw-xray "
                        "(used by init script before first start)")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of text")
    args = p.parse_args()

    if not _NAME_RE.match(args.name):
        die(f"invalid name {args.name!r} (must match {_NAME_RE.pattern})")

    if not PARAMS_FILE.exists():
        die(f"{PARAMS_FILE} missing — run vpngw-xray-init.sh first")
    params = json.loads(PARAMS_FILE.read_text())

    clients = load_clients()
    if any(c.get("name") == args.name for c in clients):
        die(f"client name already exists: {args.name}")

    new = {
        "uuid": str(uuid.uuid4()),
        "name": args.name,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    clients.append(new)
    save_clients(clients)

    # Re-render server.json so xray picks the new UUID up at next start.
    subprocess.run([str(RENDER_SCRIPT)], check=True)

    if not args.no_restart:
        # Persist xray's in-memory counters BEFORE try-restart, otherwise
        # every existing client's stats get wiped to zero. Snapshot also
        # garbage-collects state entries for users not in clients.json,
        # so adding a never-before-seen client name starts cleanly at 0.
        if SNAPSHOT_SCRIPT.exists():
            subprocess.run([str(SNAPSHOT_SCRIPT)], check=False)
        # try-restart: if the service isn't enabled/running yet (fresh
        # install during init), do nothing instead of erroring.
        subprocess.run(["systemctl", "try-restart", "vpngw-xray.service"],
                       check=False)

    url = share_url(new["uuid"], new["name"], params)
    if args.json:
        out = dict(new)
        out["share_url"] = url
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"client added:")
        print(f"  name : {new['name']}")
        print(f"  uuid : {new['uuid']}")
        print(f"  url  : {url}")


if __name__ == "__main__":
    main()
