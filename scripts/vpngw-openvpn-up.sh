#!/bin/bash
# Called by openvpn via --route-up after the tunnel comes up and the
# server-pushed routes have been added to the kernel routing table.
#
# Environment provided by openvpn (see openvpn(8) "Environmental Variables"):
#   dev          — tunnel interface name (e.g. tun0)
#   ifconfig_local        — our local tunnel IP
#   ifconfig_remote       — peer tunnel IP / netmask
#   route_network_N       — server-pushed route destination
#   route_netmask_N       — netmask
#   route_gateway_N       — gateway (typically the peer)
#
# Our job:
#   1. Add MASQUERADE on tun_dev so server-side hosts see our tunnel IP
#      (clients in the LAN otherwise have no route back).
#   2. Allow forwarding LAN ↔ tun.
#   3. Drop a marker file recording the iptables rules we added so the
#      down-script (and the rollback script) can remove only ours.
#
# Server's pushed default route (redirect-gateway) is filtered out by
# --pull-filter on the openvpn command line; this script only fires after
# the remaining routes (specific subnets) are installed.

set -euo pipefail

CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"
LAN_IF="${LAN_INTERFACE:-eth0}"
LAN_SUBNET="${LAN_SUBNET:-192.168.50.0/24}"

TUN="${dev:-${1:-tun0}}"
STATE_DIR="/run/vpngw-openvpn"
mkdir -p "$STATE_DIR"
echo "$TUN" > "$STATE_DIR/tun"

ipt_add() {
    local table="$1" chain="$2"
    shift 2
    if ! iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
        iptables -t "$table" -A "$chain" "$@"
    fi
}

ipt_insert_top() {
    # Insert at position 1, only if not already present.
    local table="$1" chain="$2"
    shift 2
    if ! iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
        iptables -t "$table" -I "$chain" 1 "$@"
    fi
}

# 1. NAT outbound on tun (home -> office direction).
ipt_add nat POSTROUTING -o "$TUN" -j MASQUERADE

# 2. NAT incoming office -> home traffic so home hosts don't need a static
#    route back to the OpenVPN-pushed subnets. Without this, an office host
#    192.168.60.10 connecting to home host 192.168.50.20 would have its
#    reply dropped: 192.168.50.20's default gateway is the LAN router
#    (192.168.50.1), not us, and the router doesn't know 192.168.60.0/24.
#    Source-NAT'ing to 192.168.50.2 (our eth0 IP) makes the home host
#    reply to us, then conntrack reverses the NAT and routes back via tun.
#
#    Match: traffic going OUT eth0 destined to home LAN, but originating
#    from outside home LAN (i.e. from anywhere reached via tun0 — pushed
#    subnets, the tun-side address pool, etc.). Inserted at position 1 so
#    it fires BEFORE the existing `-d 192.168.0.0/16 -j RETURN` in
#    POSTROUTING that preserves source IP for inter-subnet traffic.
ipt_insert_top nat POSTROUTING -o "$LAN_IF" -d "$LAN_SUBNET" ! -s "$LAN_SUBNET" -j MASQUERADE

# 3. Forwarding LAN -> tun and back. The default FORWARD policy is ACCEPT
#    so these are belt-and-suspenders for the case someone tightens the
#    policy later.
ipt_add filter FORWARD -i "$LAN_IF" -o "$TUN" -j ACCEPT
ipt_add filter FORWARD -i "$TUN" -o "$LAN_IF" -j ACCEPT

# 3. Record the pushed routes so the API can show them on the dashboard.
ROUTES_FILE="$STATE_DIR/pushed-routes"
: > "$ROUTES_FILE"
i=1
while :; do
    netvar="route_network_${i}"
    maskvar="route_netmask_${i}"
    net="${!netvar:-}"
    mask="${!maskvar:-}"
    [[ -z "$net" ]] && break
    # Convert dotted-quad netmask to CIDR prefix (e.g. 255.255.255.0 -> 24).
    if [[ -n "$mask" ]]; then
        prefix=0
        IFS='.' read -ra octets <<< "$mask"
        for o in "${octets[@]}"; do
            case "$o" in
                255) prefix=$((prefix+8));;
                254) prefix=$((prefix+7));;
                252) prefix=$((prefix+6));;
                248) prefix=$((prefix+5));;
                240) prefix=$((prefix+4));;
                224) prefix=$((prefix+3));;
                192) prefix=$((prefix+2));;
                128) prefix=$((prefix+1));;
                0)   ;;
            esac
        done
        echo "${net}/${prefix}" >> "$ROUTES_FILE"
    else
        echo "${net}" >> "$ROUTES_FILE"
    fi
    i=$((i+1))
done

# Local + remote tunnel addresses.
echo "${ifconfig_local:-}" > "$STATE_DIR/local-ip"
echo "${ifconfig_remote:-}" > "$STATE_DIR/remote-ip"

echo "vpngw-openvpn-up: $TUN ready, $(wc -l < "$ROUTES_FILE") pushed route(s) recorded"
