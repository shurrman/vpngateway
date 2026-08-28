"""VPN Gateway API configuration. Reads values from vpngateway.conf."""

from pathlib import Path

# Base paths
VPNGATEWAY_DIR = Path("/opt/vpngateway")
CONFIG_DIR = VPNGATEWAY_DIR / "config"
SCRIPTS_DIR = VPNGATEWAY_DIR / "scripts"
GATEWAY_CONF = CONFIG_DIR / "vpngateway.conf"

# Read gateway configuration
def _read_gateway_conf() -> dict:
    conf = {}
    if GATEWAY_CONF.exists():
        for line in GATEWAY_CONF.read_text().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                # Strip quotes from values
                v = v.strip().strip('"').strip("'")
                conf[k.strip()] = v
    return conf

_conf = _read_gateway_conf()

# Config files
#
# Domain category files live in CONFIG_DIR/domains/<category>.lst.
# `<category>` is a short id (e.g. "main", "aws", "cloudflare"); each
# file produces its own /etc/dnsmasq.d/vpn-domains-<category>.conf
# but they all populate the same vpn_domains ipset.
#
# DOMAINS_DIR is the canonical location. DOMAINS_FILE is kept as an
# alias to <DOMAINS_DIR>/main.lst for the few places that read "the
# main list" specifically.
DOMAINS_DIR = CONFIG_DIR / "domains"
DOMAINS_FILE = DOMAINS_DIR / "main.lst"
IPLISTS_FILE = CONFIG_DIR / "iplist-sources.lst"
DNSMASQ_CONF = Path("/etc/dnsmasq.conf")

# AmneziaWG configs library (one .conf per VPN endpoint).
# Filename without .conf is the stable config id. IDs may be a plain country
# code (`CH`) or a country plus variant (`DE-VLESS`) for display.
VPN_CONFIGS_DIR = CONFIG_DIR / "configs"
VPN_ACTIVE_FILE = VPN_CONFIGS_DIR / ".active"

# External VPN selector. Public-internet split traffic can egress through
# AmneziaWG (`amn0`) or an XRay client TUN (`xray0`). OpenVPN `tun0` remains
# an independent private-subnet side tunnel and is not selected here.
EXTERNAL_TUNNEL_FILE = CONFIG_DIR / "external-tunnel"
AMNEZIA_INTERFACE = _conf.get("VPN_INTERFACE", "amn0")
XRAY_TUN_INTERFACE = _conf.get("XRAY_TUN_INTERFACE", "xray0")

# XRay client configs library. These are user-supplied VLESS/SS configs and
# may contain UUIDs/passwords/keys, so this directory is runtime-only.
XRAY_CLIENT_DIR = CONFIG_DIR / "xray-client"
XRAY_CLIENT_CONFIGS_DIR = XRAY_CLIENT_DIR / "configs"
XRAY_CLIENT_SUBSCRIPTIONS_DIR = XRAY_CLIENT_DIR / "subscriptions"
XRAY_CLIENT_SUBSCRIPTION_STATE_DIR = XRAY_CLIENT_DIR / "subscription-state"
XRAY_CLIENT_ACTIVE_FILE = XRAY_CLIENT_CONFIGS_DIR / ".active"
XRAY_CLIENT_CONFIG_FILE = XRAY_CLIENT_DIR / "client.json"
XRAY_CLIENT_HWID_FILE = XRAY_CLIENT_DIR / "hwid"

# OpenVPN configs library (one .ovpn per OpenVPN server).
# OpenVPN runs SIDE-BY-SIDE with Amnezia and is NOT used for the public
# internet split-tunneling — it only carries traffic to the subnets the
# OpenVPN server pushes (e.g. a home LAN like 192.168.60.0/24).
OPENVPN_DIR = CONFIG_DIR / "openvpn"
OPENVPN_ACTIVE_FILE = OPENVPN_DIR / ".active"
# Runtime state dir written by the OpenVPN up/down scripts.
OPENVPN_STATE_DIR = Path("/run/vpngw-openvpn")

# XRay (VLESS + XHTTP) — public-facing inbound proxy that re-egresses
# client traffic through the AmneziaWG tunnel (amn0). Lives behind
# nginx on :443 with a Let's Encrypt cert (cloud VM only — there is
# nothing client-facing on a local gateway). See README §XRay.
#
# Layout:
#   /opt/vpngateway/config/xray/
#     server.json           generated from server.json.template
#     server-keys.json      x25519 keypair (NOT in repo, mode 600)
#     clients.json          registered clients [{name,uuid,created}]
#     stub/                 static "default page" nginx serves on /
XRAY_DIR = CONFIG_DIR / "xray"
XRAY_CONFIG_FILE = XRAY_DIR / "server.json"
XRAY_KEYS_FILE = XRAY_DIR / "server-keys.json"
XRAY_CLIENTS_FILE = XRAY_DIR / "clients.json"
XRAY_TEMPLATE = XRAY_DIR / "server.json.template"
# Local plain-HTTP port xray's xhttp inbound listens on (nginx fronts TLS).
XRAY_INTERNAL_PORT = 8443
# gRPC stats API for /xray/status counters.
XRAY_STATS_PORT = 10085
# Public host (set in vpngateway.conf as XRAY_PUBLIC_HOST). Used both to
# render server-side config and to assemble vless:// share URLs.
XRAY_PUBLIC_HOST = _conf.get("XRAY_PUBLIC_HOST", "")

# Scripts (whitelist)
SCRIPTS = {
    "setup-routing": SCRIPTS_DIR / "vpngw-setup-routing.sh",
    "teardown-routing": SCRIPTS_DIR / "vpngw-teardown-routing.sh",
    "fix-routes": SCRIPTS_DIR / "vpngw-fix-routes.sh",
    "update-domains": SCRIPTS_DIR / "vpngw-update-domains.sh",
    "update-iplists": SCRIPTS_DIR / "vpngw-update-iplists.sh",
    "switch-vpn": SCRIPTS_DIR / "vpngw-switch-vpn.sh",
    "openvpn-run": SCRIPTS_DIR / "vpngw-openvpn-run.sh",
    "openvpn-up": SCRIPTS_DIR / "vpngw-openvpn-up.sh",
    "openvpn-down": SCRIPTS_DIR / "vpngw-openvpn-down.sh",
    "select-external-tunnel": SCRIPTS_DIR / "vpngw-select-external-tunnel.sh",
    "xray-client-render-config": SCRIPTS_DIR / "vpngw-xray-client-render-config.py",
    "xray-init": SCRIPTS_DIR / "vpngw-xray-init.sh",
    "xray-render-config": SCRIPTS_DIR / "vpngw-xray-render-config.sh",
    "xray-add-client": SCRIPTS_DIR / "vpngw-xray-add-client.sh",
    "xray-remove-client": SCRIPTS_DIR / "vpngw-xray-remove-client.sh",
    "xray-stats": SCRIPTS_DIR / "vpngw-xray-stats.sh",
    "xray-stats-snapshot": SCRIPTS_DIR / "vpngw-xray-stats-snapshot.py",
}

# Systemd services (whitelist)
ALLOWED_SERVICES = {
    "vpngw-routing",
    "vpngw-vpn",
    "vpngw-watch-vpn",
    "vpngw-update-iplists",
    "vpngw-openvpn",
    "vpngw-xray-client",
    "vpngw-xray",
    "vpngw-xray-stats-snapshot",
    "dnsmasq",
    "nginx",
}

# Network (from vpngateway.conf with defaults)
IPSET_NAME = _conf.get("IPSET_NAME", "vpn_domains")
VPN_INTERFACE = AMNEZIA_INTERFACE
LAN_INTERFACE = _conf.get("LAN_INTERFACE", "ens160")
LAN_GATEWAY = _conf.get("LAN_GATEWAY", "192.168.50.1")

# Allowed client subnets (LAN-only access)
_subnets_str = _conf.get("API_ALLOWED_SUBNETS", "192.168.50.0/24,127.0.0.0/8")
ALLOWED_SUBNETS = [s.strip() for s in _subnets_str.split(",") if s.strip()]

# API
# IMPORTANT: bump the patch component (X.Y.Z → X.Y.Z+1) and update
# API_VERSION_DATE on EVERY change to the project. See CLAUDE.md
# (раздел "Правила для разработки") for the rule and the format.
API_VERSION = "4.2.24"
API_VERSION_DATE = "2026-08-29"
API_PORT = 443
