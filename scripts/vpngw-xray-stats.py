#!/usr/bin/env python3
"""Emit a JSON blob with persistent xray byte counters for the dashboard.

Output schema (unchanged — parsed by /api/v1/xray/status):
  {
    "inbound_uplink":   <bytes>,
    "inbound_downlink": <bytes>,
    "outbound_uplink":  <bytes>,
    "outbound_downlink": <bytes>,
    "users": { "<email>": { "uplink": <bytes>, "downlink": <bytes> } }
  }

Source of truth: `/var/lib/vpngw-xray/stats.json` written by
`vpngw-xray-stats-snapshot.py`. xray-core itself keeps counters in
RAM, so every `systemctl restart vpngw-xray` (add/revoke client, host
reboot, crash) wipes them — the snapshotter persists them and tracks
in-memory→on-disk diffs.

To make sure the file is fresh enough for whoever's reading, this
script TRIGGERS A SNAPSHOT FIRST, then re-reads the file. Cost is
~50 ms (one xray-CLI subprocess), called at most once per /xray/status
poll (≈ every 10 seconds).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

STATE_FILE = Path("/var/lib/vpngw-xray/stats.json")
SNAPSHOT_BIN = Path("/opt/vpngateway/scripts/vpngw-xray-stats-snapshot.py")

# Counter names emitted by xray for inbound/outbound. Hard-coded —
# they're determined by inbound/outbound tags in server.json.template.
TAG_INBOUND  = "vless-in"
TAG_OUTBOUND = "amnezia"


def emit(obj: dict) -> "NoReturn":
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def main() -> None:
    # Refresh persisted state. If the snapshot script is missing or xray
    # is down, the file may stay stale but at least we serve last-known.
    if SNAPSHOT_BIN.exists():
        try:
            subprocess.run([str(SNAPSHOT_BIN)],
                           capture_output=True, timeout=8)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass  # serve whatever's on disk

    if not STATE_FILE.exists():
        emit({
            "inbound_uplink":    0,
            "inbound_downlink":  0,
            "outbound_uplink":   0,
            "outbound_downlink": 0,
            "users":             {},
        })

    try:
        state = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        emit({"error": f"stats state unreadable: {e}"})

    counters = state.get("counters", {})

    def total(name: str) -> int:
        entry = counters.get(name, {})
        return int(entry.get("total", 0))

    out: dict = {
        "inbound_uplink":    total(f"inbound>>>{TAG_INBOUND}>>>traffic>>>uplink"),
        "inbound_downlink":  total(f"inbound>>>{TAG_INBOUND}>>>traffic>>>downlink"),
        "outbound_uplink":   total(f"outbound>>>{TAG_OUTBOUND}>>>traffic>>>uplink"),
        "outbound_downlink": total(f"outbound>>>{TAG_OUTBOUND}>>>traffic>>>downlink"),
        "users":             {},
    }

    for name, entry in counters.items():
        if not name.startswith("user>>>"):
            continue
        parts = name.split(">>>")
        if len(parts) < 4:
            continue
        email     = parts[1]
        direction = parts[3]
        if direction not in ("uplink", "downlink"):
            continue
        u = out["users"].setdefault(email, {"uplink": 0, "downlink": 0})
        u[direction] = int(entry.get("total", 0))

    emit(out)


if __name__ == "__main__":
    main()
