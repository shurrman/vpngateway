#!/bin/bash
# Called by openvpn via --down when the tunnel goes away.
#
# Reverses everything vpngw-openvpn-up.sh did:
#   1. Removes MASQUERADE rule on tun_dev.
#   2. Removes FORWARD allow rules.
#   3. Cleans up the runtime state dir.
#
# Errors are tolerated — this needs to be idempotent so the rollback
# script can call it blind.

set -uo pipefail

CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"
LAN_IF="${LAN_INTERFACE:-eth0}"
LAN_SUBNET="${LAN_SUBNET:-192.168.50.0/24}"

STATE_DIR="/run/vpngw-openvpn"
TUN="${dev:-$(cat "$STATE_DIR/tun" 2>/dev/null || echo tun0)}"

# Mirror the up-script: remove home->office NAT, office->home NAT, and the
# two FORWARD rules. The pre-v3.0.6 form of the tun->LAN FORWARD rule was
# state-restricted (RELATED,ESTABLISHED) — try removing that variant too
# so this script also cleans up after older up-scripts.
iptables -t nat -D POSTROUTING -o "$TUN" -j MASQUERADE 2>/dev/null || true
iptables -t nat -D POSTROUTING -o "$LAN_IF" -d "$LAN_SUBNET" ! -s "$LAN_SUBNET" -j MASQUERADE 2>/dev/null || true
iptables -D FORWARD -i "$LAN_IF" -o "$TUN" -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -i "$TUN" -o "$LAN_IF" -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -i "$TUN" -o "$LAN_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true

rm -f "$STATE_DIR"/tun "$STATE_DIR"/pushed-routes "$STATE_DIR"/local-ip "$STATE_DIR"/remote-ip

echo "vpngw-openvpn-down: cleaned up rules for $TUN"
