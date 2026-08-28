#!/bin/bash
# Monitor amn0 interface — run fix-amnezia-routes.sh when it appears.
# This handles AmneziaVPN connecting, disconnecting, and reconnecting.

set -euo pipefail

# Load configuration
CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

VPN_IF="${VPN_INTERFACE:-amn0}"
FIX_SCRIPT="/opt/vpngateway/scripts/vpngw-fix-amnezia-routes.sh"

echo "=== vpngw-watch-amn0: monitoring $VPN_IF ==="

# If amn0 already exists at startup, fix routes immediately
if ip link show "$VPN_IF" &>/dev/null; then
    echo "$VPN_IF already exists, running fix script"
    "$FIX_SCRIPT" || true
fi

# Monitor link events — look for amn0 appearing
ip monitor link | while read -r line; do
    if echo "$line" | grep -q "$VPN_IF"; then
        if echo "$line" | grep -q "state UP\|state UNKNOWN"; then
            echo "$(date): $VPN_IF came up, fixing routes"
            "$FIX_SCRIPT" || true
        fi
    fi
done
