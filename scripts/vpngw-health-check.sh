#!/bin/bash
# VPN Gateway health check — runs every 2 minutes via systemd timer.
# Sends email alert on state transition (OK→PROBLEM or PROBLEM→OK).
# Also sends notification on gateway reboot.

set -euo pipefail

# Load configuration
GW_CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$GW_CONF" ]] && source "$GW_CONF"

AMNEZIA_IF="${VPN_INTERFACE:-amn0}"
XRAY_IF="${XRAY_TUN_INTERFACE:-xray0}"
LAN_GW="${LAN_GATEWAY:-192.168.50.1}"
export GATEWAY_HOSTNAME="${GATEWAY_HOSTNAME:-vpngateway}"
STATE_FILE="/tmp/vpngw-health-state"
BOOT_FLAG="/tmp/vpngw-boot-notified"
CONF="/opt/vpngateway/config/notifications.conf"
SEND_EMAIL="/opt/vpngateway/scripts/vpngw-send-email.py"
PYTHON="/opt/vpngateway/api/venv/bin/python3"
EXTERNAL_TUNNEL_FILE="/opt/vpngateway/config/external-tunnel"

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
    xray)
        EXTERNAL_IF="$XRAY_IF"
        EXTERNAL_SERVICE="vpngw-xray-client"
        ;;
    none)
        EXTERNAL_IF=""
        EXTERNAL_SERVICE=""
        ;;
    *)
        EXTERNAL_IF="$AMNEZIA_IF"
        EXTERNAL_SERVICE="vpngw-vpn"
        ;;
esac

# --- Reboot notification (once per boot) ---
if [[ ! -f "$BOOT_FLAG" ]]; then
    echo "First health check after boot"
    uptime_str=$(uptime -p 2>/dev/null || echo "unknown")
    $PYTHON "$SEND_EMAIL" "$CONF" \
        "[VPN Gateway] Reboot: $(date '+%Y-%m-%d %H:%M')" \
        "VPN Gateway has been restarted.
Uptime: $uptime_str
Mode: $(cat /opt/vpngateway/config/mode 2>/dev/null || echo unknown)
External tunnel: $EXTERNAL_TUNNEL" || true
    touch "$BOOT_FLAG"
fi

# --- Collect problems ---
problems=()

# Check selected external VPN tunnel, unless intentionally disabled.
if [[ -n "$EXTERNAL_IF" && ! -d /sys/class/net/$EXTERNAL_IF ]]; then
    problems+=("External VPN tunnel $EXTERNAL_IF is DOWN (interface does not exist)")
fi

# Check critical services
critical_services=(vpngw-routing vpngw-watch-vpn vpngw-api dnsmasq)
if [[ -n "$EXTERNAL_SERVICE" ]]; then
    critical_services+=("$EXTERNAL_SERVICE")
fi
for svc in "${critical_services[@]}"; do
    if ! systemctl is-active --quiet "$svc"; then
        problems+=("Service $svc is not active")
    fi
done

# Check DNS resolution
dns_result=$(dig +short +timeout=3 +tries=1 youtube.com @127.0.0.1 2>/dev/null || true)
if [[ -z "$dns_result" ]]; then
    problems+=("DNS resolution failed (youtube.com via dnsmasq)")
fi

# Check internet connectivity via LAN gateway (ISP router reachable?)
if ! ping -c1 -W3 "$LAN_GW" &>/dev/null; then
    problems+=("LAN gateway $LAN_GW is unreachable (router down?)")
fi

# Check internet connectivity (external IP reachable?).
# Use 9.9.9.9 (Quad9), NOT 8.8.8.8: vpngw-fix-routes.sh installs static
# routes `8.8.8.8 dev amn0` and `1.1.1.1 dev amn0` so dnsmasq's upstream
# DNS escapes Russian ISP DNS hijacking. Side effect: ICMP/HTTPS to 8.8.8.8
# from the gateway also goes through the VPN, where this provider's NAT
# silently drops it (verified with tcpdump — packets leave amn0, no replies
# come back) — giving false PROBLEM alerts. 9.9.9.9 is not in the pin-list
# so it goes via the default route through eth0 → ISP.
if ! ping -c1 -W5 9.9.9.9 &>/dev/null; then
    problems+=("Internet is unreachable (ping 9.9.9.9 failed)")
fi

# --- Read previous state ---
prev_state=""
[[ -f "$STATE_FILE" ]] && prev_state=$(cat "$STATE_FILE")

# --- Determine current state and send notifications on transition ---
if [[ ${#problems[@]} -gt 0 ]]; then
    current_state="PROBLEM"
    if [[ "$prev_state" != "PROBLEM" ]]; then
        # `printf -- '...'` ends option parsing — without it bash builtin
        # printf reads the leading "- " of the format as an option flag
        # and aborts with `printf: -: invalid option` (which under
        # `set -euo pipefail` kills the whole script before the alert is
        # actually sent). This bug was latent until the Internet check
        # started failing for the first time on 2026-05-07.
        message=$(printf -- '- %s\n' "${problems[@]}")
        echo "State change: ${prev_state:-INIT} -> PROBLEM"
        $PYTHON "$SEND_EMAIL" "$CONF" \
            "[VPN Gateway] ALERT: $(date '+%H:%M')" \
            "Problems detected on VPN Gateway:

$message" || true
    fi
else
    current_state="OK"
    if [[ "$prev_state" == "PROBLEM" ]]; then
        echo "State change: PROBLEM -> OK"
        $PYTHON "$SEND_EMAIL" "$CONF" \
            "[VPN Gateway] RESOLVED: $(date '+%H:%M')" \
            "All checks passed. VPN gateway is fully operational." || true
    fi
fi

echo "$current_state" > "$STATE_FILE"
