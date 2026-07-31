#!/bin/bash
# Tear down VPN split tunneling routing — reverse of vpngw-setup-routing.sh

set -euo pipefail

# Load configuration
CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

AMNEZIA_IF="${VPN_INTERFACE:-amn0}"
XRAY_IF="${XRAY_TUN_INTERFACE:-xray0}"
LAN_IF="${LAN_INTERFACE:-ens160}"
IPSET_NAME="${IPSET_NAME:-vpn_domains}"
FWMARK="${FWMARK:-0x1}"
TABLE="${ROUTING_TABLE:-100}"

echo "=== vpngw-teardown-routing ==="

# --- iptables helper: delete rule if present ---
ipt_del() {
    local table="$1" chain="$2"
    shift 2
    if iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
        iptables -t "$table" -D "$chain" "$@"
        return 0
    fi
    return 1
}

# --- Remove FORWARD rules ---
ipt_del filter FORWARD -i "$LAN_IF" -o "$LAN_IF" -j ACCEPT || true
for tunnel_if in "$AMNEZIA_IF" "$XRAY_IF"; do
    ipt_del filter FORWARD -i "$tunnel_if" -o "$LAN_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT || true
    ipt_del filter FORWARD -i "$LAN_IF" -o "$tunnel_if" -j ACCEPT || true
done

# --- Remove NAT rules ---
ipt_del nat PREROUTING -i "$LAN_IF" -p udp --dport 53 -j REDIRECT --to-ports 53 || true
ipt_del nat PREROUTING -i "$LAN_IF" -p tcp --dport 53 -j REDIRECT --to-ports 53 || true
ipt_del nat POSTROUTING -o "$LAN_IF" -j MASQUERADE || true
ipt_del nat POSTROUTING -o "$AMNEZIA_IF" -j MASQUERADE || true
ipt_del nat POSTROUTING -o "$XRAY_IF" -j MASQUERADE || true

# --- Remove mangle rules ---
ipt_del mangle OUTPUT -m mark --mark 0x0 -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
ipt_del mangle PREROUTING -m mark --mark 0x0 -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
ipt_del mangle OUTPUT -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
ipt_del mangle PREROUTING -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
for tunnel_if in "$AMNEZIA_IF" "$XRAY_IF"; do
    ipt_del mangle FORWARD -o "$tunnel_if" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1320 || true
    ipt_del mangle FORWARD -i "$tunnel_if" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1320 || true
done

# --- Remove default routes via external tunnels from main table (all-vpn) ---
for tunnel_if in "$AMNEZIA_IF" "$XRAY_IF"; do
    if ip route show default dev "$tunnel_if" 2>/dev/null | grep -q .; then
        ip route del default dev "$tunnel_if" 2>/dev/null || true
        echo "Removed default route via $tunnel_if from main table"
    fi
done

# --- Remove DNS routes via external tunnels from main table ---
for dns in ${DNS_UPSTREAM:-8.8.8.8 8.8.4.4}; do
    ip route del "$dns" dev "$AMNEZIA_IF" 2>/dev/null || true
    ip route del "$dns" dev "$XRAY_IF" 2>/dev/null || true
done

# --- Restore default route via LAN gateway if missing ---
LAN_GW="${LAN_GATEWAY:-192.168.50.1}"
if ! ip route show default | grep -q "$LAN_GW"; then
    ip route add default via "$LAN_GW" dev "$LAN_IF" 2>/dev/null || true
    echo "Restored default route via $LAN_GW"
fi

# --- Remove ip route table ---
ip route flush table "$TABLE" 2>/dev/null || true
echo "Flushed route table $TABLE"

# --- Remove ip rule ---
while ip rule show | grep -q "fwmark ${FWMARK} lookup ${TABLE}"; do
    ip rule del fwmark "$FWMARK" table "$TABLE"
done
echo "Removed ip rule for fwmark $FWMARK"

# --- Destroy ipset ---
if ipset list "$IPSET_NAME" &>/dev/null; then
    ipset destroy "$IPSET_NAME"
    echo "Destroyed ipset $IPSET_NAME"
fi

echo "=== Teardown complete ==="
