#!/bin/bash
# Monitor VPN interface — run fix-routes.sh when it appears.
# Safety net for cases when PostUp hook doesn't fire (manual awg, restarts).

set -euo pipefail

# Load configuration
CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

AMNEZIA_IF="${VPN_INTERFACE:-amn0}"
XRAY_IF="${XRAY_TUN_INTERFACE:-xray0}"
FIX_SCRIPT="/opt/vpngateway/scripts/vpngw-fix-routes.sh"

echo "=== vpngw-watch-vpn: monitoring $AMNEZIA_IF and $XRAY_IF ==="

# If VPN interface already exists at startup, fix routes immediately
if ip link show "$AMNEZIA_IF" &>/dev/null || ip link show "$XRAY_IF" &>/dev/null; then
    echo "external tunnel interface already exists, running fix script"
    "$FIX_SCRIPT" || true
fi

# Monitor link events — look for VPN interface appearing
ip monitor link | while read -r line; do
    if echo "$line" | grep -q "$AMNEZIA_IF\|$XRAY_IF"; then
        if echo "$line" | grep -q "state UP\|state UNKNOWN"; then
            echo "$(date): external tunnel interface changed, fixing routes"
            "$FIX_SCRIPT" || true
        fi
    fi
done
