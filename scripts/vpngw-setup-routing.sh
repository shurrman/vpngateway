#!/bin/bash
# Set up VPN routing based on mode (split / all-vpn / all-direct).
# Modes are stored in /opt/vpngateway/config/mode.
#
# This script is idempotent — safe to run multiple times.

set -euo pipefail

# Load configuration
CONF="/opt/vpngateway/config/vpngateway.conf"
[[ -f "$CONF" ]] && source "$CONF"

AMNEZIA_IF="${VPN_INTERFACE:-amn0}"
XRAY_IF="${XRAY_TUN_INTERFACE:-xray0}"
XRAY_ADDR="${XRAY_TUN_ADDRESS:-198.18.0.1/30}"
LAN_IF="${LAN_INTERFACE:-ens160}"
LAN_GW="${LAN_GATEWAY:-192.168.50.1}"
IPSET_NAME="${IPSET_NAME:-vpn_domains}"
FWMARK="${FWMARK:-0x1}"
XRAY_BYPASS_MARK="${XRAY_BYPASS_MARK:-0x2}"
TABLE="${ROUTING_TABLE:-100}"
MAXELEM="${IPSET_MAXELEM:-131072}"
EXTERNAL_TUNNEL_FILE="/opt/vpngateway/config/external-tunnel"

MODE_FILE="/opt/vpngateway/config/mode"
MODE="split"
[[ -f "$MODE_FILE" ]] && MODE=$(cat "$MODE_FILE" | tr -d '[:space:]')

echo "=== vpngw-setup-routing (mode: $MODE) ==="

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
    xray) VPN_IF="$XRAY_IF"; NEED_TUNNEL_NAT=0 ;;
    none) VPN_IF=""; NEED_TUNNEL_NAT=0 ;;
    *) VPN_IF="$AMNEZIA_IF"; NEED_TUNNEL_NAT=1 ;;
esac
echo "External tunnel: $EXTERNAL_TUNNEL${VPN_IF:+ ($VPN_IF)}"

ensure_xray_tun_ready() {
    if [[ "$EXTERNAL_TUNNEL" != "xray" ]]; then
        return 0
    fi
    if ! ip link show "$XRAY_IF" &>/dev/null; then
        return 0
    fi
    ip addr replace "$XRAY_ADDR" dev "$XRAY_IF"
    ip link set "$XRAY_IF" up
    sysctl -w "net.ipv4.conf.${XRAY_IF}.rp_filter=0" >/dev/null 2>&1 || true
    sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null 2>&1 || true
    echo "XRay TUN $XRAY_IF address: $XRAY_ADDR"
}

ensure_xray_tun_ready

# --- iptables helper: add rule only if not present ---
ipt_add() {
    local table="$1" chain="$2"
    shift 2
    if ! iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
        iptables -t "$table" -A "$chain" "$@"
        return 0
    fi
    return 1
}

ipt_del() {
    local table="$1" chain="$2"
    shift 2
    if iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
        iptables -t "$table" -D "$chain" "$@"
        return 0
    fi
    return 1
}

case "$MODE" in

  all-vpn)
    # Route ALL traffic through the selected external tunnel.

    if [[ -z "$VPN_IF" ]]; then
        echo "WARNING: no external tunnel selected"
        for tunnel_if in "$AMNEZIA_IF" "$XRAY_IF"; do
            ip route del default dev "$tunnel_if" 2>/dev/null || true
        done
        ip route flush table "$TABLE" 2>/dev/null || true
        if ! ip route show default | grep -q "$LAN_GW"; then
            ip route replace default via "$LAN_GW" dev "$LAN_IF"
        fi
    else
        # NAT on AmneziaWG only. XRay TUN receives routed packets and writes
        # replies back itself; source-NAT before xray0 would hide LAN clients
        # from the TUN stack and break return traffic.
        if [[ "$NEED_TUNNEL_NAT" == "1" ]] && ipt_add nat POSTROUTING -o "$VPN_IF" -j MASQUERADE; then
            echo "Added NAT MASQUERADE on $VPN_IF"
        fi

        # FORWARD: LAN -> VPN (all traffic)
        if ipt_add filter FORWARD -i "$LAN_IF" -o "$VPN_IF" -j ACCEPT; then
            echo "Added FORWARD $LAN_IF -> $VPN_IF"
        fi
        if ipt_add filter FORWARD -i "$VPN_IF" -o "$LAN_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT; then
            echo "Added FORWARD $VPN_IF -> $LAN_IF (established)"
        fi

        # Default route through VPN in main table (if interface exists)
        if ip link show "$VPN_IF" &>/dev/null; then
            ip route replace default dev "$VPN_IF"
            echo "Main table: default via $VPN_IF"
        else
            echo "WARNING: $VPN_IF not found"
            if ! ip route show default | grep -q "$LAN_GW"; then
                ip route replace default via "$LAN_GW" dev "$LAN_IF"
            fi
        fi
    fi
    ;;

  all-direct)
    # Route ALL traffic directly (bypass VPN)

    # Skip MASQUERADE for inter-subnet (private) traffic — preserves
    # source IP so return packets route correctly across subnets.
    ipt_add nat POSTROUTING -o "$LAN_IF" -d 10.0.0.0/8 -j RETURN || true
    ipt_add nat POSTROUTING -o "$LAN_IF" -d 172.16.0.0/12 -j RETURN || true
    ipt_add nat POSTROUTING -o "$LAN_IF" -d 192.168.0.0/16 -j RETURN || true

    # NAT only internet-bound traffic on LAN interface
    if ipt_add nat POSTROUTING -o "$LAN_IF" -j MASQUERADE; then
        echo "Added NAT MASQUERADE on $LAN_IF (internet only)"
    fi

    # FORWARD: LAN direct only
    if ipt_add filter FORWARD -i "$LAN_IF" -o "$LAN_IF" -j ACCEPT; then
        echo "Added FORWARD $LAN_IF -> $LAN_IF"
    fi

    # Ensure default route via ISP
    if ! ip route show default | grep -q "$LAN_GW"; then
        ip route replace default via "$LAN_GW" dev "$LAN_IF"
    fi
    echo "Main table: default via $LAN_GW"
    ;;

  *)
    # Split tunneling (default) — route only selected domains through VPN

    # --- ipset ---
    if ! ipset list "$IPSET_NAME" &>/dev/null; then
        ipset create "$IPSET_NAME" hash:net maxelem "$MAXELEM"
        echo "Created ipset $IPSET_NAME"
    else
        echo "ipset $IPSET_NAME already exists"
    fi

    # --- Load static IP networks ---
    NETWORKS_DIR="/opt/vpngateway/config"
    for lst in "$NETWORKS_DIR"/*-networks.lst; do
        [[ -f "$lst" ]] || continue
        count=0
        while IFS= read -r cidr; do
            cidr="${cidr%%#*}"
            cidr="${cidr// /}"
            [[ -z "$cidr" ]] && continue
            ipset add "$IPSET_NAME" "$cidr" 2>/dev/null && ((count++)) || true
        done < "$lst"
        echo "Loaded $count entries from $(basename "$lst")"
    done

    # --- ip rule ---
    if ! ip rule show | grep -q "fwmark ${FWMARK} lookup ${TABLE}"; then
        ip rule add fwmark "$FWMARK" table "$TABLE" priority 100
        echo "Added ip rule: fwmark $FWMARK -> table $TABLE"
    else
        echo "ip rule already exists"
    fi

    # --- ip route table 100 ---
    ROUTE_TABLE_READY=0
    if [[ -z "$VPN_IF" ]]; then
        echo "WARNING: no external tunnel selected, skipping route table setup"
        ip route flush table "$TABLE" 2>/dev/null || true
    elif ip link show "$VPN_IF" &>/dev/null; then
        ip route replace default dev "$VPN_IF" table "$TABLE"
        echo "Route table $TABLE: default via $VPN_IF"
        ROUTE_TABLE_READY=1
    else
        echo "WARNING: $VPN_IF not found, skipping route table setup"
        ip route flush table "$TABLE" 2>/dev/null || true
    fi

    # --- mangle: mark packets destined for VPN domains ---
    # Remove existing mark rules first; when external tunnel is `none`, we
    # intentionally leave split traffic unmarked so it follows the main table.
    ipt_del mangle PREROUTING -m mark --mark 0x0 -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
    ipt_del mangle OUTPUT -m mark --mark 0x0 -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
    # Remove pre-4.0 legacy mark rules that overwrote socket marks in OUTPUT.
    ipt_del mangle PREROUTING -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true
    ipt_del mangle OUTPUT -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK" || true

    if [[ "$ROUTE_TABLE_READY" == "1" ]]; then
        if ipt_add mangle PREROUTING -m mark --mark 0x0 -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK"; then
            echo "Added mangle PREROUTING rule"
        fi
        if ipt_add mangle OUTPUT -m mark --mark 0x0 -m set --match-set "$IPSET_NAME" dst -j MARK --set-mark "$FWMARK"; then
            echo "Added mangle OUTPUT rule"
        fi

    else
        echo "Skipped mangle mark rules (external route table not ready)"
    fi

    if [[ "$NEED_TUNNEL_NAT" == "1" && "$ROUTE_TABLE_READY" == "1" ]]; then
        # --- TCPMSS clamping on AmneziaWG ---
        # AmneziaWG MTU is 1420; without clamping, LAN clients (MTU 1500, MSS 1460)
        # send TCP segments that don't fit through the tunnel. The kernel can't
        # forward them as-is and ICMP frag-needed often doesn't reach the
        # original sender (PMTU blackhole) — large TLS ClientHello packets get
        # silently dropped between us and the destination, and the remote side
        # eventually RSTs the half-stuck connection. Symptom: ERR_CONNECTION_RESET
        # in the browser specifically for sites with bulky TLS hellos (Cloudflare-
        # hosted ones, e.g. medium.com, are the canonical trip-up).
        #
        # We use a fixed `--set-mss 1320`, NOT `--clamp-mss-to-pmtu`. Reason:
        # `--clamp-mss-to-pmtu` looks at the OUTGOING interface MTU. For
        # `-o amn0` it correctly clamps the client's SYN (MSS 1460 -> 1380).
        # But `-i amn0` (server SYN-ACK travelling LAN-ward) would read the
        # eth0 MTU (1500 -> MSS 1460) and DO NOTHING — leaving the server's
        # announced MSS=1400 unchanged. The client then thinks it can send up
        # to 1400-byte payloads, which exceed amn0's actual on-the-wire budget
        # (AmneziaWG obfuscation adds bytes beyond the standard 40-byte WG
        # header). Result: first big TCP segment of a TLS Hello gets dropped,
        # remote sends sack+RST, browser shows ERR_CONNECTION_RESET.
        #
        # 1320 = 1420 (AWG MTU) - 40 (TCP+IP) - ~60 (extra obfuscation slack).
        # Confirmed empirically: medium.com (Cloudflare, big TLS Hello) loads
        # cleanly with mss=1320 in both directions; --clamp-mss-to-pmtu didn't
        # cut it.
        if ipt_add mangle FORWARD -o "$VPN_IF" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1320; then
            echo "Added mangle FORWARD MSS=1320 -o $VPN_IF"
        fi
        if ipt_add mangle FORWARD -i "$VPN_IF" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1320; then
            echo "Added mangle FORWARD MSS=1320 -i $VPN_IF"
        fi
    fi

    # --- NAT ---
    # VPN interface: MASQUERADE only for AmneziaWG. XRay TUN does not need it.
    if [[ "$NEED_TUNNEL_NAT" == "1" && "$ROUTE_TABLE_READY" == "1" ]] && ipt_add nat POSTROUTING -o "$VPN_IF" -j MASQUERADE; then
        echo "Added NAT MASQUERADE on $VPN_IF"
    fi

    # LAN interface: skip MASQUERADE for inter-subnet (private) traffic —
    # preserves source IP so return packets route correctly across subnets.
    ipt_add nat POSTROUTING -o "$LAN_IF" -d 10.0.0.0/8 -j RETURN || true
    ipt_add nat POSTROUTING -o "$LAN_IF" -d 172.16.0.0/12 -j RETURN || true
    ipt_add nat POSTROUTING -o "$LAN_IF" -d 192.168.0.0/16 -j RETURN || true

    # NAT only internet-bound traffic on LAN interface
    if ipt_add nat POSTROUTING -o "$LAN_IF" -j MASQUERADE; then
        echo "Added NAT MASQUERADE on $LAN_IF (internet only)"
    fi

    # Force LAN clients through gateway dnsmasq so DNS-based split routing can
    # populate vpn_domains even when clients try public DNS directly.
    if ipt_add nat PREROUTING -i "$LAN_IF" -p udp --dport 53 -j REDIRECT --to-ports 53; then
        echo "Added DNS redirect UDP/53 -> local dnsmasq"
    fi
    if ipt_add nat PREROUTING -i "$LAN_IF" -p tcp --dport 53 -j REDIRECT --to-ports 53; then
        echo "Added DNS redirect TCP/53 -> local dnsmasq"
    fi

    # --- FORWARD ---
    if [[ "$ROUTE_TABLE_READY" == "1" ]]; then
        if ipt_add filter FORWARD -i "$LAN_IF" -o "$VPN_IF" -j ACCEPT; then
            echo "Added FORWARD $LAN_IF -> $VPN_IF"
        fi
        if ipt_add filter FORWARD -i "$VPN_IF" -o "$LAN_IF" -m state --state RELATED,ESTABLISHED -j ACCEPT; then
            echo "Added FORWARD $VPN_IF -> $LAN_IF (established)"
        fi
    fi
    if ipt_add filter FORWARD -i "$LAN_IF" -o "$LAN_IF" -j ACCEPT; then
        echo "Added FORWARD $LAN_IF -> $LAN_IF"
    fi

    # Restart dnsmasq so it re-attaches to the (possibly recreated) ipset.
    # After teardown destroys ipset and setup recreates it, dnsmasq holds
    # a stale reference and silently stops adding IPs to ipset.
    if systemctl is-active --quiet dnsmasq || systemctl is-failed --quiet dnsmasq; then
        systemctl reset-failed dnsmasq 2>/dev/null || true
        systemctl restart dnsmasq
        echo "Restarted dnsmasq (ipset re-attach)"
    fi
    ;;
esac

echo "=== Routing setup complete (mode: $MODE) ==="
