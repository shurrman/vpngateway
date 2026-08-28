#!/bin/bash
# Start XRay client TUN, optionally with an Outline-prefixed Shadowsocks sidecar.

set -euo pipefail

XRAY_CONFIG="/opt/vpngateway/config/xray-client/client.json"
OUTLINE_CONFIG="/opt/vpngateway/config/xray-client/outline-ss-local.json"
OUTLINE_BIN="/usr/local/bin/vpngw-outline-ss-local"
XRAY_BIN="/usr/local/bin/xray"
FIX_ROUTES="/opt/vpngateway/scripts/vpngw-fix-routes.sh"
XRAY_IF="${XRAY_TUN_INTERFACE:-xray0}"

outline_pid=""
xray_pid=""

cleanup() {
    if [[ -n "$xray_pid" ]]; then
        kill "$xray_pid" 2>/dev/null || true
    fi
    if [[ -n "$outline_pid" ]]; then
        kill "$outline_pid" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
}
trap cleanup TERM INT EXIT

if [[ -s "$OUTLINE_CONFIG" ]]; then
    if [[ ! -x "$OUTLINE_BIN" ]]; then
        echo "outline ss sidecar missing: $OUTLINE_BIN" >&2
        exit 78
    fi
    "$OUTLINE_BIN" -config "$OUTLINE_CONFIG" &
    outline_pid="$!"
    sleep 0.4
    if ! kill -0 "$outline_pid" 2>/dev/null; then
        echo "outline ss sidecar failed to start" >&2
        exit 78
    fi
fi

"$XRAY_BIN" run -c "$XRAY_CONFIG" &
xray_pid="$!"
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ip link show "$XRAY_IF" >/dev/null 2>&1; then
        "$FIX_ROUTES" || true
        break
    fi
    if ! kill -0 "$xray_pid" 2>/dev/null; then
        break
    fi
    sleep 0.3
done
wait "$xray_pid"
