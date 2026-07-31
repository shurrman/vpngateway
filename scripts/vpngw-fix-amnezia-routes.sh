#!/bin/bash
# Fix routing after AmneziaVPN connects/reconnects.
# Behavior depends on current mode (split / all-vpn / all-direct).

set -euo pipefail

# Load configuration
CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

VPN_IF="${VPN_INTERFACE:-amn0}"
LAN_GW="${LAN_GATEWAY:-192.168.50.1}"
LAN_IF="${LAN_INTERFACE:-ens160}"
TABLE="${ROUTING_TABLE:-100}"

MODE_FILE="/opt/vpngateway/config/mode"
MODE="split"
[[ -f "$MODE_FILE" ]] && MODE=$(cat "$MODE_FILE" | tr -d '[:space:]')

echo "=== vpngw-fix-amnezia-routes (mode: $MODE) ==="

# Wait briefly for AmneziaVPN to finish setting up routes
sleep 2

# Check if amn0 exists
if ! ip link show "$VPN_IF" &>/dev/null; then
    echo "WARNING: $VPN_IF does not exist, nothing to fix"
    exit 0
fi

# --- Mode-specific route handling ---

if [[ "$MODE" == "all-vpn" ]]; then
    # All-VPN mode: KEEP AmneziaVPN catch-all routes (we want all traffic through VPN)
    echo "All-VPN mode: keeping AmneziaVPN routes"

    # Just ensure amn0 is the default
    if ! ip route show default | grep -q "$VPN_IF"; then
        ip route replace default dev "$VPN_IF"
        echo "Set default route via $VPN_IF"
    fi

else
    # Split or All-Direct: remove AmneziaVPN catch-all routes
    for route in "0.0.0.0/1" "128.0.0.0/1"; do
        if ip route show "$route" dev "$VPN_IF" 2>/dev/null | grep -q .; then
            ip route del "$route" dev "$VPN_IF" 2>/dev/null || true
            echo "Removed AmneziaVPN route $route via $VPN_IF"
        fi
    done

    # Remove default route via amn0 from main table
    if ip route show default | grep -q "$VPN_IF"; then
        echo "Removing AmneziaVPN default route from main table"
        ip route del default dev "$VPN_IF" 2>/dev/null || true
    fi

    # Ensure default route via LAN gateway
    if ! ip route show default | grep -q "$LAN_GW"; then
        echo "Restoring default route via $LAN_GW"
        ip route add default via "$LAN_GW" dev "$LAN_IF"
    else
        echo "Default route via $LAN_GW already present"
    fi

    if [[ "$MODE" == "split" ]]; then
        # Split mode: set up table 100 and DNS routes via VPN (ISP blocks UDP 53)
        ip route replace default dev "$VPN_IF" table "$TABLE"
        echo "Route table $TABLE: default via $VPN_IF"

        for dns in ${DNS_UPSTREAM:-1.1.1.1 8.8.8.8}; do
            ip route replace "$dns" dev "$VPN_IF"
            echo "Route $dns via $VPN_IF (main table)"
        done
    else
        # All-direct mode: remove DNS routes via VPN
        for dns in ${DNS_UPSTREAM:-1.1.1.1 8.8.8.8}; do
            ip route del "$dns" dev "$VPN_IF" 2>/dev/null || true
        done
        echo "Removed VPN DNS routes (all-direct mode)"
    fi
fi

# Re-run full routing setup (idempotent, mode-aware)
/opt/vpngateway/scripts/vpngw-setup-routing.sh

# Fix AmneziaVPN DNS blocking: allow DNS to LAN gateway (router).
if iptables -L amnvpn.310.blockDNS &>/dev/null; then
    if ! iptables -C amnvpn.310.blockDNS -d "$LAN_GW/32" -p udp --dport 53 -j ACCEPT 2>/dev/null; then
        iptables -I amnvpn.310.blockDNS 1 -d "$LAN_GW/32" -p udp --dport 53 -j ACCEPT
        iptables -I amnvpn.310.blockDNS 2 -d "$LAN_GW/32" -p tcp --dport 53 -j ACCEPT
        echo "Added DNS exception for $LAN_GW"
    else
        echo "DNS exception for $LAN_GW already present"
    fi
fi

# Allow gateway's own outbound traffic via ens160.
if iptables -L amnvpn.100.blockAll &>/dev/null; then
    if ! iptables -C amnvpn.100.blockAll -o "$LAN_IF" -j ACCEPT 2>/dev/null; then
        iptables -I amnvpn.100.blockAll 1 -o "$LAN_IF" -j ACCEPT
        echo "Added direct internet exception for $LAN_IF in blockAll"
    else
        echo "Direct internet exception for $LAN_IF already present"
    fi
fi

echo "=== Routes fixed (mode: $MODE) ==="
