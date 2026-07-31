#!/bin/bash
# Switch the active AmneziaWG config.
#
# Usage:  vpngw-switch-vpn.sh <NAME>
# Where NAME matches /opt/vpngateway/config/configs/<NAME>.conf
#
# 1. Stops vpngw-vpn (which runs `awg-quick down amn0`).
# 2. Copies configs/<NAME>.conf -> /etc/amnezia/amneziawg/amn0.conf.
# 3. Starts vpngw-vpn (`awg-quick up amn0`), which runs the PostUp hook.
# 4. Records the new active name in configs/.active.

set -euo pipefail

NAME="${1:-}"
if [[ -z "$NAME" ]]; then
    echo "usage: $(basename "$0") <NAME>" >&2
    exit 2
fi
if ! [[ "$NAME" =~ ^[A-Za-z0-9_-]{1,32}$ ]]; then
    echo "error: invalid config name: $NAME" >&2
    exit 2
fi

CONFIGS_DIR="/opt/vpngateway/config/configs"
SRC="$CONFIGS_DIR/$NAME.conf"
DST="/etc/amnezia/amneziawg/amn0.conf"
ACTIVE_FILE="$CONFIGS_DIR/.active"
EXTERNAL_TUNNEL_FILE="/opt/vpngateway/config/external-tunnel"

if [[ ! -f "$SRC" ]]; then
    echo "error: config not found: $SRC" >&2
    exit 3
fi

echo "=== switching VPN to $NAME ==="

# Read previous active for logging
PREV="$(cat "$ACTIVE_FILE" 2>/dev/null || echo '<unknown>')"
echo "previous: $PREV"

# AmneziaWG and XRay-client are mutually exclusive external tunnels.
mkdir -p "$(dirname "$EXTERNAL_TUNNEL_FILE")"
printf '%s\n' "amnezia" > "$EXTERNAL_TUNNEL_FILE"
systemctl stop vpngw-xray-client 2>/dev/null || true

# Stop tunnel — best-effort, ignore failure if already down
systemctl stop vpngw-vpn 2>/dev/null || true

# Replace the kernel-side config
install -o root -g root -m 600 "$SRC" "$DST"
echo "wrote $DST from $SRC"

# Update the active marker BEFORE bringing the tunnel back up so any
# hook that reads it sees the new value.
mkdir -p "$CONFIGS_DIR"
printf '%s' "$NAME" > "$ACTIVE_FILE"

# Start tunnel — PostUp hook in amn0.conf will fix routes on its own.
systemctl start vpngw-vpn
echo "started vpngw-vpn"

# Belt-and-suspenders: re-run the route fixer in case the PostUp ran
# before the interface was fully ready.
/opt/vpngateway/scripts/vpngw-fix-routes.sh || true

# Flush the kernel route cache and the conntrack table so client devices
# don't keep multiplexing HTTP/2 traffic over now-dead TLS sessions
# (the encrypted tunnel changed keys; old packets are silently dropped
# by the new server, and the browser would otherwise wait for a TCP
# timeout before opening a fresh connection through the new exit).
ip route flush cache 2>/dev/null || true
if command -v conntrack >/dev/null 2>&1; then
    # `-F` flushes everything — that includes the LAN→gateway:443 entry
    # for the in-flight API request, but TCP on both sides is intact so
    # the connection is just re-tracked from the next packet onward.
    conntrack -F 2>/dev/null || true
    echo "flushed conntrack"
fi

echo "=== active=$NAME (was $PREV) ==="
