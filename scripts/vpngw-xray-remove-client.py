#!/usr/bin/env python3
"""Revoke a VLESS client by UUID — removes the entry from clients.json,
re-renders server.json, and restarts vpngw-xray so the connection is
terminated immediately.

Usage:
  vpngw-xray-remove-client.py --uuid <uuid>
  vpngw-xray-remove-client.py --uuid <uuid> --json   # machine output
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid as _uuid
from pathlib import Path

XRAY_DIR = Path("/opt/vpngateway/config/xray")
CLIENTS_FILE = XRAY_DIR / "clients.json"
RENDER_SCRIPT = Path("/opt/vpngateway/scripts/vpngw-xray-render-config.py")
SNAPSHOT_SCRIPT = Path("/opt/vpngateway/scripts/vpngw-xray-stats-snapshot.py")


def die(msg: str, code: int = 1) -> "NoReturn":
    print(f"remove-client: error: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--uuid", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        target = str(_uuid.UUID(args.uuid))
    except ValueError:
        die(f"not a valid UUID: {args.uuid}")

    if not CLIENTS_FILE.exists():
        die(f"{CLIENTS_FILE} missing — no clients to remove")

    clients = json.loads(CLIENTS_FILE.read_text())
    new_clients = [c for c in clients if c.get("uuid") != target]
    if len(new_clients) == len(clients):
        die(f"no client with uuid={target}")

    removed = next(c for c in clients if c.get("uuid") == target)

    tmp = CLIENTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new_clients, indent=2, ensure_ascii=False))
    tmp.chmod(0o600)
    os.replace(tmp, CLIENTS_FILE)

    subprocess.run([str(RENDER_SCRIPT)], check=True)
    # Persist the surviving clients' stats BEFORE try-restart wipes
    # xray's in-memory counters. The removed user's name is no longer in
    # clients.json, so snapshot's GC drops its persisted entry — exactly
    # what we want; the UI removes the row immediately on revoke anyway.
    if SNAPSHOT_SCRIPT.exists():
        subprocess.run([str(SNAPSHOT_SCRIPT)], check=False)
    subprocess.run(["systemctl", "try-restart", "vpngw-xray.service"],
                   check=False)

    if args.json:
        print(json.dumps({"removed": removed}, ensure_ascii=False))
    else:
        print(f"client removed: {removed.get('name', '?')} ({target})")


if __name__ == "__main__":
    main()
