#!/bin/bash
# Fix routing after VPN tunnel connects/reconnects.
# Called by awg-quick PostUp hook or vpngw-watch-vpn.sh.
# Behavior depends on current mode (split / all-vpn / all-direct).

set -euo pipefail

# Load configuration
CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

AMNEZIA_IF="${VPN_INTERFACE:-amn0}"
XRAY_IF="${XRAY_TUN_INTERFACE:-xray0}"
XRAY_ADDR="${XRAY_TUN_ADDRESS:-198.18.0.1/30}"
LAN_GW="${LAN_GATEWAY:-192.168.50.1}"
LAN_IF="${LAN_INTERFACE:-ens160}"
TABLE="${ROUTING_TABLE:-100}"
EXTERNAL_TUNNEL_FILE="/opt/vpngateway/config/external-tunnel"

MODE_FILE="/opt/vpngateway/config/mode"
MODE="split"
[[ -f "$MODE_FILE" ]] && MODE=$(cat "$MODE_FILE" | tr -d '[:space:]')

echo "=== vpngw-fix-routes (mode: $MODE) ==="

external_tunnel() {
    local selected=""
    if [[ -f "$EXTERNAL_TUNNEL_FILE" ]]; then
        selected="$(cat "$EXTERNAL_TUNNEL_FILE" | tr -d '[:space:]')"
    fi
    case "$selected" in
        amnezia|xray|none) printf '%s' "$selected"; return ;;
    esac
    if systemctl is-active --quiet vpngw-xray-client 2>/dev/null; then
        printf 'xray'
    elif systemctl is-active --quiet vpngw-vpn 2>/dev/null; then
        printf 'amnezia'
    else
        printf 'amnezia'
    fi
}

EXTERNAL_TUNNEL="$(external_tunnel)"
case "$EXTERNAL_TUNNEL" in
    xray) VPN_IF="$XRAY_IF" ;;
    none) VPN_IF="" ;;
    *) VPN_IF="$AMNEZIA_IF" ;;
esac
echo "External tunnel: $EXTERNAL_TUNNEL${VPN_IF:+ ($VPN_IF)}"

# Check if VPN interface exists
if [[ -z "$VPN_IF" ]]; then
    echo "WARNING: no external tunnel selected"
    /opt/vpngateway/scripts/vpngw-setup-routing.sh
    exit 0
fi
if ! ip link show "$VPN_IF" &>/dev/null; then
    echo "WARNING: $VPN_IF does not exist, nothing to fix"
    /opt/vpngateway/scripts/vpngw-setup-routing.sh
    exit 0
fi

if [[ "$EXTERNAL_TUNNEL" == "xray" ]]; then
    ip addr replace "$XRAY_ADDR" dev "$XRAY_IF"
    ip link set "$XRAY_IF" up
    sysctl -w "net.ipv4.conf.${XRAY_IF}.rp_filter=0" >/dev/null 2>&1 || true
    sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null 2>&1 || true
    echo "XRay TUN $XRAY_IF address: $XRAY_ADDR"
fi

# --- Mode-specific route handling ---

if [[ "$MODE" == "all-vpn" ]]; then
    # All-VPN mode: set VPN as default route
    echo "All-VPN mode: setting default via $VPN_IF"
    if ! ip route show default | grep -q "$VPN_IF"; then
        ip route replace default dev "$VPN_IF"
        echo "Set default route via $VPN_IF"
    fi

elif [[ "$MODE" == "all-direct" ]]; then
    # All-Direct mode: ensure default route via LAN, remove VPN DNS routes
    if ! ip route show default | grep -q "$LAN_GW"; then
        ip route replace default via "$LAN_GW" dev "$LAN_IF"
    fi
    for dns in ${DNS_UPSTREAM:-8.8.8.8 8.8.4.4}; do
        ip route del "$dns" dev "$VPN_IF" 2>/dev/null || true
    done
    echo "All-direct mode: default via $LAN_GW, VPN DNS routes removed"

else
    # Split mode: table 100 via VPN, DNS routes via VPN, default via LAN
    if ! ip route show default | grep -q "$LAN_GW"; then
        ip route replace default via "$LAN_GW" dev "$LAN_IF"
    fi
    echo "Default route via $LAN_GW"

    ip route replace default dev "$VPN_IF" table "$TABLE"
    echo "Route table $TABLE: default via $VPN_IF"

    # DNS routes via VPN (ISP blocks UDP 53 to external DNS)
    for dns in ${DNS_UPSTREAM:-1.1.1.1 8.8.8.8}; do
        ip route replace "$dns" dev "$VPN_IF"
        echo "Route $dns via $VPN_IF (main table)"
    done
fi

# Re-run full routing setup (idempotent, mode-aware)
/opt/vpngateway/scripts/vpngw-setup-routing.sh

echo "=== Routes fixed (mode: $MODE) ==="
