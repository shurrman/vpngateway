#!/bin/bash
# Select the public-internet external tunnel backend.
#
# Usage:
#   vpngw-select-external-tunnel.sh amnezia
#   vpngw-select-external-tunnel.sh xray
#   vpngw-select-external-tunnel.sh none

set -euo pipefail

TARGET="${1:-}"
case "$TARGET" in
    amnezia|xray|none) ;;
    *)
        echo "usage: $(basename "$0") amnezia|xray|none" >&2
        exit 2
        ;;
esac

CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

STATE_FILE="/opt/vpngateway/config/external-tunnel"
XRAY_CLIENT_ACTIVE="/opt/vpngateway/config/xray-client/configs/.active"
XRAY_CLIENT_RENDER="/opt/vpngateway/scripts/vpngw-xray-client-render-config.py"
FIX_ROUTES="/opt/vpngateway/scripts/vpngw-fix-routes.sh"

mkdir -p "$(dirname "$STATE_FILE")"

stop_service() {
    local svc="$1"
    systemctl stop "$svc" 2>/dev/null || true
}

start_service() {
    local svc="$1"
    systemctl start "$svc"
}

start_or_restart_service() {
    local svc="$1"
    if systemctl is-active --quiet "$svc"; then
        systemctl restart "$svc"
    else
        systemctl start "$svc"
    fi
}

case "$TARGET" in
    amnezia)
        start_service vpngw-vpn
        printf '%s\n' "amnezia" > "$STATE_FILE"
        stop_service vpngw-xray-client
        "$FIX_ROUTES" || true
        ;;

    xray)
        if [[ ! -s "$XRAY_CLIENT_ACTIVE" ]]; then
            echo "error: no active XRay client config selected" >&2
            exit 3
        fi
        "$XRAY_CLIENT_RENDER" --check >/dev/null
        start_or_restart_service vpngw-xray-client
        # Write the desired backend before stopping Amnezia so awg PostDown
        # does not clear route table 100 while XRay is taking over.  We start
        # XRay first, so a bad config does not drop the currently working
        # Amnezia path.
        printf '%s\n' "xray" > "$STATE_FILE"
        stop_service vpngw-vpn
        "$FIX_ROUTES" || true
        ;;

    none)
        printf '%s\n' "none" > "$STATE_FILE"
        stop_service vpngw-xray-client
        stop_service vpngw-vpn
        "$FIX_ROUTES" || true
        ;;
esac

echo "external tunnel: $TARGET"
