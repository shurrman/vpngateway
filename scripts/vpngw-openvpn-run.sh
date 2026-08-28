#!/bin/bash
# ExecStart wrapper for vpngw-openvpn.service.
#
# Reads the active config name from /opt/vpngateway/config/openvpn/.active,
# then launches openvpn with safety filters that prevent the server from
# turning this client into a default-gateway / DNS / Windows-firewall
# override.
#
# IMPORTANT: this VPN is for *server-pushed subnets only*. The Amnezia
# split-tunneling stays in charge of the public-internet routing. Hence:
#
#   --pull-filter ignore "redirect-gateway"   ← never make tun the default
#   --pull-filter ignore "route 0.0.0.0"      ← server can't sneak it back
#   --pull-filter ignore "dhcp-option DNS"    ← no DNS hijack
#   --pull-filter ignore "dhcp-option WINS"   ← (defensive)
#   --pull-filter ignore "block-outside-dns"  ← Windows-only flag, ignore

set -euo pipefail

OPENVPN_DIR="/opt/vpngateway/config/openvpn"
ACTIVE_FILE="$OPENVPN_DIR/.active"

if [[ ! -f "$ACTIVE_FILE" ]]; then
    echo "error: no active OpenVPN config (missing $ACTIVE_FILE)" >&2
    exit 1
fi

NAME="$(cat "$ACTIVE_FILE" | tr -d '[:space:]')"
if [[ -z "$NAME" ]]; then
    echo "error: $ACTIVE_FILE is empty" >&2
    exit 1
fi
if ! [[ "$NAME" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
    echo "error: invalid active OpenVPN config name: $NAME" >&2
    exit 1
fi

CONF_FILE="$OPENVPN_DIR/$NAME.ovpn"
if [[ ! -f "$CONF_FILE" ]]; then
    echo "error: config not found: $CONF_FILE" >&2
    exit 1
fi

exec /usr/sbin/openvpn \
    --config "$CONF_FILE" \
    --cd "$OPENVPN_DIR" \
    --script-security 2 \
    --route-up /opt/vpngateway/scripts/vpngw-openvpn-up.sh \
    --down     /opt/vpngateway/scripts/vpngw-openvpn-down.sh \
    --pull-filter ignore "redirect-gateway" \
    --pull-filter ignore "route 0.0.0.0" \
    --pull-filter ignore "dhcp-option DNS" \
    --pull-filter ignore "dhcp-option WINS" \
    --pull-filter ignore "block-outside-dns" \
    --writepid /run/vpngw-openvpn.pid
