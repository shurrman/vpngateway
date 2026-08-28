#!/usr/bin/env python3
"""Persist xray-core's in-memory stat counters to disk so they survive
the next `systemctl restart vpngw-xray`.

The problem we solve: every operator action that modifies clients.json
(add/revoke a client) ends with `systemctl try-restart vpngw-xray`, which
wipes xray's in-memory byte counters. From the UI's POV all per-client
"downloaded / sent" columns reset to 0 every time you touch the table —
useless for accounting.

Strategy: keep a JSON state file `/var/lib/vpngw-xray/stats.json` with
the *accumulated total* and the *last value we saw in xray* for every
counter name. On each merge:

    if curr >= last_seen:    # counter still growing — normal flow
        total += (curr - last_seen)
    else:                    # curr < last_seen → xray reset to 0
        total += curr        # already counted what we saw before;
                             # whatever's in xray now is the new partial
    last_seen = curr

The script is called:
  * by vpngw-xray-stats.py before reading the file (so HTTP polls see
    a fresh accumulated total)
  * by vpngw-xray-add-client.py / remove-client.py BEFORE try-restart,
    so the about-to-be-wiped in-memory counters get captured
  * by the systemd timer every 60s, catching xray crashes that bypass
    our scripts

Garbage collection: user>>>X@vpngateway counters whose X isn't in
clients.json get dropped from state.json. We don't keep ghosts of
revoked clients.

Usage:
  vpngw-xray-stats-snapshot.py                 # merge once
  vpngw-xray-stats-snapshot.py --emit-json     # also print state.json
  vpngw-xray-stats-snapshot.py --purge-user X  # drop user X explicitly
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE_DIR = Path("/var/lib/vpngw-xray")
STATE_FILE = STATE_DIR / "stats.json"
CLIENTS_FILE = Path("/opt/vpngateway/config/xray/clients.json")
XRAY_BIN = "/usr/local/bin/xray"
STATS_ADDR = "127.0.0.1:10085"


def fetch_current() -> dict[str, int]:
    """Return {counter_name: value} from xray, or {} if xray is down /
    statsquery times out. Returning {} means "no fresh sample" — merge
    leaves persisted totals untouched."""
    if not Path(XRAY_BIN).exists():
        return {}
    try:
        proc = subprocess.run(
            [XRAY_BIN, "api", "statsquery",
             "--server", STATS_ADDR, "--pattern", ""],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}
    if proc.returncode != 0:
        return {}
    result: dict[str, int] = {}
    # Modern xray emits JSON {"stat":[{"name":..,"value":..}]}; older
    # builds emit textual `name: "..."  value: NNN` — accept both.
    try:
        obj = json.loads(proc.stdout)
        for stat in obj.get("stat", []):
            result[stat["name"]] = int(stat.get("value", 0))
        return result
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    for m in re.finditer(
        r'name:\s*"([^"]+)"\s+value:\s*(-?\d+)', proc.stdout
    ):
        result[m.group(1)] = int(m.group(2))
    return result


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"updated_at": None, "counters": {}}
    try:
        d = json.loads(STATE_FILE.read_text())
        if not isinstance(d, dict):
            return {"updated_at": None, "counters": {}}
        d.setdefault("counters", {})
        return d
    except json.JSONDecodeError:
        return {"updated_at": None, "counters": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.chmod(0o644)
    os.replace(tmp, STATE_FILE)


def load_active_names() -> set[str]:
    """Names currently in clients.json — used both to keep counters for
    active users and to garbage-collect counters of revoked ones."""
    try:
        clients = json.loads(CLIENTS_FILE.read_text())
        return {c["name"] for c in clients if c.get("name")}
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return set()


def _user_name_from_counter(name: str) -> str | None:
    """For a `user>>><email>>>>traffic>>>...` counter return the username
    part of the email (everything before '@'). For non-user counters
    returns None."""
    if not name.startswith("user>>>"):
        return None
    parts = name.split(">>>", 2)
    if len(parts) < 2:
        return None
    email = parts[1]
    return email.split("@", 1)[0]


def merge(state: dict, current: dict[str, int],
          active_names: set[str]) -> dict:
    counters = state.get("counters", {})

    for name, curr in current.items():
        # Skip user counters whose name was revoked — these are about to
        # be GC'd anyway and we don't want stale totals to grow.
        uname = _user_name_from_counter(name)
        if uname is not None and uname not in active_names:
            continue

        entry = counters.get(name, {"total": 0, "last_seen": 0})
        if curr >= entry["last_seen"]:
            entry["total"] += curr - entry["last_seen"]
        else:
            # xray restarted: counter reset and (maybe) re-grew to `curr`.
            entry["total"] += curr
        entry["last_seen"] = curr
        counters[name] = entry

    # GC: drop counters for users not in clients.json (revoked).
    for name in list(counters.keys()):
        uname = _user_name_from_counter(name)
        if uname is not None and uname not in active_names:
            del counters[name]

    state["counters"] = counters
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"
    )
    return state


def purge_user(state: dict, uname: str) -> dict:
    """Drop all user>>>NAME@*>>>* entries for a single user — used when
    add-client wants to pre-clear a stale entry that survives if the
    same name was reused, or when remove-client wants to be explicit."""
    counters = state.get("counters", {})
    drop = [n for n in counters if _user_name_from_counter(n) == uname]
    for n in drop:
        del counters[n]
    state["counters"] = counters
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"
    )
    return state


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--emit-json", action="store_true",
                   help="print the persisted state to stdout after merging")
    p.add_argument("--purge-user", metavar="NAME",
                   help="drop all stat entries for a single user "
                        "(no merge from xray performed)")
    args = p.parse_args()

    state = load_state()
    if args.purge_user:
        state = purge_user(state, args.purge_user)
    else:
        current = fetch_current()
        active = load_active_names()
        state = merge(state, current, active)
    save_state(state)

    if args.emit_json:
        json.dump(state, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
