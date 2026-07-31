#!/bin/bash
# Called by awg-quick PostDown hook when VPN tunnel goes down.
# Cleans up VPN routes and ensures LAN default route is present.

set -euo pipefail

CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

VPN_IF="${VPN_INTERFACE:-amn0}"
LAN_GW="${LAN_GATEWAY:-192.168.50.1}"
LAN_IF="${LAN_INTERFACE:-ens160}"
TABLE="${ROUTING_TABLE:-100}"
EXTERNAL_TUNNEL_FILE="/opt/vpngateway/config/external-tunnel"

echo "=== vpngw-on-vpn-down: $VPN_IF went down ==="

ACTIVE_EXTERNAL=""
if [[ -f "$EXTERNAL_TUNNEL_FILE" ]]; then
    ACTIVE_EXTERNAL="$(cat "$EXTERNAL_TUNNEL_FILE" | tr -d '[:space:]')"
fi
if [[ "$ACTIVE_EXTERNAL" == "xray" ]]; then
    echo "External tunnel is xray; keeping route table for xray0"
    exit 0
fi

# Flush VPN routing table
ip route flush table "$TABLE" 2>/dev/null || true
echo "Flushed route table $TABLE"

# Remove DNS routes via VPN
for dns in ${DNS_UPSTREAM:-8.8.8.8 8.8.4.4}; do
    ip route del "$dns" dev "$VPN_IF" 2>/dev/null || true
done

# Ensure default route via LAN gateway
if ! ip route show default | grep -q "$LAN_GW"; then
    ip route replace default via "$LAN_GW" dev "$LAN_IF"
    echo "Restored default route via $LAN_GW"
fi

echo "=== VPN down cleanup complete ==="
