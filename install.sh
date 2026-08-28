#!/bin/bash
# VPN Gateway installer
# Deploys split tunneling configuration to /opt/vpngateway/
# Must be run as root on the target machine.
#
# Before running: edit config/vpngateway.conf with your network settings.

set -euo pipefail

INSTALL_DIR="/opt/vpngateway"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF_FILE="${VPNGATEWAY_CONF_FILE:-$SCRIPT_DIR/config/vpngateway.conf}"

install_os_packages() {
    local -a packages

    if command -v apt-get >/dev/null 2>&1; then
        packages=(
            ca-certificates curl dnsmasq iproute2 ipset iptables nmap openssl
            python3-pip python3-venv unzip
        )
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}" > /dev/null
    elif command -v dnf >/dev/null 2>&1; then
        packages=(
            ca-certificates curl dnsmasq iproute ipset iptables nmap openssl
            python3 python3-pip systemd unzip
        )
        dnf install -y -q "${packages[@]}"
    elif command -v yum >/dev/null 2>&1; then
        packages=(
            ca-certificates curl dnsmasq iproute ipset iptables nmap openssl
            python3 python3-pip systemd unzip
        )
        yum install -y -q "${packages[@]}"
    else
        echo "ERROR: supported package manager not found (apt-get, dnf, or yum)" >&2
        exit 1
    fi

    echo "Packages installed: ${packages[*]}"
}

# --- Check root ---
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# --- Check config ---
if [[ ! -f "$CONF_FILE" ]]; then
    echo "ERROR: $CONF_FILE not found"
    echo "Copy config/vpngateway.conf.example and edit it first, or set VPNGATEWAY_CONF_FILE."
    exit 1
fi

source "$CONF_FILE"

echo "=== VPN Gateway Installer ==="
echo "Source: $SCRIPT_DIR"
echo "Target: $INSTALL_DIR"
echo "Gateway: ${GATEWAY_IP} (${GATEWAY_HOSTNAME})"
echo "LAN: ${LAN_SUBNET} via ${LAN_GATEWAY} (${LAN_INTERFACE})"
echo "VPN interface: ${VPN_INTERFACE}"
echo ""

# --- Install packages ---
echo "--- Installing packages ---"
install_os_packages

# --- Disable systemd-resolved (conflicts with dnsmasq on port 53) ---
if systemctl is-active --quiet systemd-resolved; then
    echo "--- Disabling systemd-resolved ---"
    systemctl stop systemd-resolved
    systemctl disable systemd-resolved
    rm -f /etc/resolv.conf
    cat > /etc/resolv.conf <<EOF
# Managed by vpngateway setup — dnsmasq handles DNS
nameserver 127.0.0.1
EOF
    echo "systemd-resolved disabled, /etc/resolv.conf updated"
fi

# --- Copy files ---
echo "--- Deploying files ---"
mkdir -p "$INSTALL_DIR"/{config,scripts,certs,api}

# Copy only known deployable configuration. Do not use a broad config/* copy:
# local checkouts may contain ignored AmneziaWG, OpenVPN, XRay, or site-only
# files next to the public templates.
for config_file in \
    iplist-sources.lst \
    mode \
    notifications.conf \
    sysctl-vpngateway.conf; do
    if [[ -f "$SCRIPT_DIR/config/$config_file" ]]; then
        cp "$SCRIPT_DIR/config/$config_file" "$INSTALL_DIR/config/"
    fi
done
install -m 0600 "$CONF_FILE" "$INSTALL_DIR/config/vpngateway.conf"
find "$SCRIPT_DIR/config" -maxdepth 1 -type f -name '*-networks.lst' \
    ! -name '._*' \
    -exec cp {} "$INSTALL_DIR/config/" \;
mkdir -p "$INSTALL_DIR/config/domains" "$INSTALL_DIR/config/xray"
for domain_file in \
    aws.lst \
    cloudflare.lst \
    devtools.lst \
    mail.lst \
    main.lst \
    openai.lst \
    publishing.lst \
    slack.lst; do
    if [[ -f "$SCRIPT_DIR/config/domains/$domain_file" ]]; then
        cp "$SCRIPT_DIR/config/domains/$domain_file" "$INSTALL_DIR/config/domains/"
    fi
done
find "$SCRIPT_DIR/config/xray" -maxdepth 1 -type f \
    \( -name 'README.md' -o -name '*.template' -o -name '*.example' -o -name '.gitignore' \) \
    -exec cp {} "$INSTALL_DIR/config/xray/" \;
cp "$SCRIPT_DIR"/scripts/* "$INSTALL_DIR/scripts/"
find "$INSTALL_DIR/scripts" -maxdepth 1 -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod +x {} +

# XRay client/public-inbound services use /usr/local/bin/xray.
# Set INSTALL_XRAY_CORE=0 to skip this network download on Amnezia-only installs.
if [[ "${INSTALL_XRAY_CORE:-1}" == "1" ]]; then
    "$INSTALL_DIR/scripts/vpngw-install-xray-core.sh"
else
    echo "Skipping xray-core install (INSTALL_XRAY_CORE=0)"
fi

# Optional compatibility sidecar for Outline-prefixed ss://...?prefix= links.
if [[ "${INSTALL_OUTLINE_SS_LOCAL:-1}" == "1" ]]; then
    "$INSTALL_DIR/scripts/vpngw-install-outline-ss-local.sh" || {
        echo "WARNING: failed to install vpngw-outline-ss-local; Outline-prefixed SS configs will not work"
    }
else
    echo "Skipping Outline SS sidecar install (INSTALL_OUTLINE_SS_LOCAL=0)"
fi

# Copy API code
if [[ -d "$SCRIPT_DIR/api" ]]; then
    cp -r "$SCRIPT_DIR"/api/* "$INSTALL_DIR/api/"
fi

echo "Files copied to $INSTALL_DIR"

# --- Prepare API (Python venv, deps installed later after DNS is up) ---
echo "--- Preparing API ---"
if [[ ! -d "$INSTALL_DIR/api/venv" ]]; then
    python3 -m venv "$INSTALL_DIR/api/venv"
    echo "Python venv created"
fi

# --- Generate dnsmasq config from template ---
echo "--- Configuring dnsmasq ---"
mkdir -p /etc/dnsmasq.d

DNSMASQ_CONF="$INSTALL_DIR/config/dnsmasq-vpngateway.conf"
{
    echo "# VPN Gateway dnsmasq configuration"
    echo "# Auto-generated by install.sh from vpngateway.conf"
    echo ""
    echo "listen-address=127.0.0.1"
    echo "listen-address=${GATEWAY_IP}"
    echo "bind-dynamic"
    echo "no-resolv"
    echo ""
    # Upstream DNS servers
    for dns in $DNS_UPSTREAM; do
        echo "server=$dns"
    done
    echo ""
    # Local DNS zones
    for zone_entry in $DNS_LOCAL_ZONES; do
        echo "server=/$zone_entry"
    done
    if [[ -n "${DNS_LOCAL_HOSTS:-}" ]]; then
        echo ""
        # Local DNS host overrides
        for host_entry in $DNS_LOCAL_HOSTS; do
            echo "address=/$host_entry"
        done
    fi
    echo ""
    echo "conf-dir=/etc/dnsmasq.d/,*.conf"
    echo "cache-size=${DNS_CACHE_SIZE:-10000}"
    echo "dns-forward-max=${DNS_FORWARD_MAX:-1000}"
    echo "domain-needed"
    echo "bogus-priv"
} > "$DNSMASQ_CONF"

cp "$DNSMASQ_CONF" /etc/dnsmasq.conf

# Generate ipset config from domains list
"$INSTALL_DIR/scripts/vpngw-update-domains.sh"

# --- Generate SSL certificates ---
echo "--- Generating SSL certificates ---"
CERTS_DIR="$INSTALL_DIR/certs"
if [[ ! -f "$CERTS_DIR/server.crt" ]]; then
    # Generate CA
    openssl genrsa -out "$CERTS_DIR/ca.key" 4096 2>/dev/null
    openssl req -x509 -new -nodes -key "$CERTS_DIR/ca.key" -sha256 -days 3650 \
        -subj "/C=XX/O=Home Network/CN=Home Network CA" \
        -out "$CERTS_DIR/ca.crt"

    # Generate server certificate
    openssl genrsa -out "$CERTS_DIR/server.key" 2048 2>/dev/null
    openssl req -new -key "$CERTS_DIR/server.key" \
        -subj "/C=XX/O=Home Network/CN=${GATEWAY_HOSTNAME}" \
        -out "$CERTS_DIR/server.csr"

    cat > "$CERTS_DIR/server.ext" <<EXTEOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=@alt_names

[alt_names]
DNS.1 = ${GATEWAY_HOSTNAME}
DNS.2 = $(echo "$GATEWAY_HOSTNAME" | cut -d. -f1)
IP.1 = ${GATEWAY_IP}
EXTEOF

    openssl x509 -req -in "$CERTS_DIR/server.csr" -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" \
        -CAcreateserial -out "$CERTS_DIR/server.crt" -days 1825 -sha256 -extfile "$CERTS_DIR/server.ext" 2>/dev/null

    chmod 600 "$CERTS_DIR/ca.key" "$CERTS_DIR/server.key"
    echo "SSL certificates generated for ${GATEWAY_HOSTNAME} / ${GATEWAY_IP}"
else
    echo "SSL certificates already exist, skipping"
fi

# Make CA cert available for download
cp "$CERTS_DIR/ca.crt" "$INSTALL_DIR/api/static/ca.crt" 2>/dev/null || true

# --- sysctl ---
echo "--- Applying sysctl ---"
cp "$INSTALL_DIR/config/sysctl-vpngateway.conf" /etc/sysctl.d/99-vpngateway.conf
sysctl -p /etc/sysctl.d/99-vpngateway.conf
echo "IP forwarding enabled"

# --- systemd services ---
echo "--- Installing systemd services ---"
cp "$SCRIPT_DIR"/systemd/*.service "$SCRIPT_DIR"/systemd/*.timer /etc/systemd/system/

systemctl daemon-reload

# Enable services
systemctl enable vpngw-routing.service
systemctl enable vpngw-external-tunnel.service
systemctl enable vpngw-watch-vpn.service
systemctl enable vpngw-update-iplists.timer
systemctl enable vpngw-health-check.timer
systemctl enable vpngw-api.service

# Start services
# Reset any failed states before starting
echo "--- Starting services ---"
systemctl reset-failed dnsmasq 2>/dev/null || true
systemctl restart dnsmasq
systemctl start vpngw-external-tunnel.service
systemctl start vpngw-routing.service
systemctl start vpngw-watch-vpn.service
systemctl start vpngw-update-iplists.timer
systemctl start vpngw-health-check.timer
# --- Install API dependencies (needs DNS, so must be after dnsmasq + routing) ---
echo "--- Installing API dependencies ---"
"$INSTALL_DIR/api/venv/bin/pip" install -q -r "$INSTALL_DIR/api/requirements.txt"
echo "API dependencies installed"

systemctl start vpngw-api.service

echo ""
echo "=== Installation complete ==="
echo ""
echo "Services status:"
systemctl is-active vpngw-routing.service     && echo "  vpngw-routing:       active" || echo "  vpngw-routing:       inactive"
systemctl is-active vpngw-external-tunnel.service && echo "  vpngw-external-tunnel: active" || echo "  vpngw-external-tunnel: inactive"
systemctl is-active vpngw-watch-vpn.service  && echo "  vpngw-watch-vpn:     active" || echo "  vpngw-watch-vpn:     inactive"
systemctl is-active vpngw-update-iplists.timer && echo "  vpngw-update-iplists timer: active" || echo "  vpngw-update-iplists timer: inactive"
systemctl is-active vpngw-health-check.timer  && echo "  vpngw-health-check timer:  active" || echo "  vpngw-health-check timer:  inactive"
systemctl is-active vpngw-api.service         && echo "  vpngw-api:           active" || echo "  vpngw-api:           inactive"
systemctl is-active dnsmasq                   && echo "  dnsmasq:             active" || echo "  dnsmasq:             inactive"
echo ""
echo "Next steps (manual):"
echo "  1. Set static IP: ${GATEWAY_IP}, gateway ${LAN_GATEWAY}, DNS 127.0.0.1"
echo "  2. Install at least one AmneziaWG or XRay client config and select the external tunnel"
echo "  3. Configure router DHCP: gateway=${GATEWAY_IP}, dns=${GATEWAY_IP}"
echo "  4. Install CA certificate on client devices: https://${GATEWAY_HOSTNAME}/static/ca.crt"
echo ""
echo "Admin console: https://${GATEWAY_HOSTNAME}/"
echo "Swagger API:   https://${GATEWAY_HOSTNAME}/api/docs"
