#!/bin/bash
# One-time bootstrap for the XRay (VLESS+XHTTP) inbound.
#
# What it does (idempotent — safe to re-run):
#   1. Create /opt/vpngateway/config/xray/ and /var/log/xray/.
#   2. Generate server-params.json (XHTTP path + public host) if missing.
#      The XHTTP path is a deployment secret; rotating it invalidates
#      all existing client share-URLs, hence "only if missing".
#   3. Generate clients.json with one default client ("test") if missing.
#   4. Re-render server.json from clients + params.
#
# Run this BEFORE the first `systemctl start vpngw-xray`.
#
# The public host name comes from vpngateway.conf's XRAY_PUBLIC_HOST.

set -euo pipefail

XRAY_DIR="/opt/vpngateway/config/xray"
PARAMS_FILE="$XRAY_DIR/server-params.json"
CLIENTS_FILE="$XRAY_DIR/clients.json"
LOG_DIR="/var/log/xray"
GATEWAY_CONF="/opt/vpngateway/config/vpngateway.conf"
SCRIPTS_DIR="/opt/vpngateway/scripts"

# Pull XRAY_PUBLIC_HOST out of vpngateway.conf (KEY=value form, optionally quoted).
read_conf_value() {
    local key="$1"
    awk -F= -v k="$key" '
        /^[[:space:]]*#/ { next }
        $1 == k {
            v=$2
            gsub(/^[ \t"'\''"]+|[ \t"'\''"]+$/, "", v)
            print v
            exit
        }
    ' "$GATEWAY_CONF" 2>/dev/null
}

PUBLIC_HOST="$(read_conf_value XRAY_PUBLIC_HOST)"
if [[ -z "$PUBLIC_HOST" ]]; then
    echo "error: XRAY_PUBLIC_HOST is not set in $GATEWAY_CONF" >&2
    echo "add a line like:  XRAY_PUBLIC_HOST=vpn.example.com" >&2
    exit 1
fi

mkdir -p "$XRAY_DIR" "$LOG_DIR"
# 755 (not 700): nginx (www-data) needs +x to traverse into stub/ and
# serve the default page. Sensitive files inside (clients.json, server-
# params.json, server.json) keep mode 600 — traversal-only access lets
# nginx see directory entries but not read any non-stub file.
chmod 755 "$XRAY_DIR"
chown root:root "$XRAY_DIR" "$LOG_DIR"

# server-params.json — generated once, kept stable.
if [[ ! -f "$PARAMS_FILE" ]]; then
    # 24 hex chars = 96 bits of entropy in the path component. Short
    # enough to fit comfortably in a URL, long enough to be unguessable.
    XHTTP_PATH="/$(head -c 18 /dev/urandom | base64 | tr -d '=+/\n' | tr 'A-Z' 'a-z' | head -c 24)"
    cat > "$PARAMS_FILE" <<JSON
{
  "xhttp_path": "$XHTTP_PATH",
  "public_host": "$PUBLIC_HOST"
}
JSON
    chmod 600 "$PARAMS_FILE"
    echo "init: created $PARAMS_FILE (xhttp_path=$XHTTP_PATH, public_host=$PUBLIC_HOST)"
else
    # If the host in the file disagrees with vpngateway.conf, warn loudly
    # — we don't auto-rotate because that breaks existing client URLs.
    current_host="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("public_host",""))' "$PARAMS_FILE")"
    if [[ "$current_host" != "$PUBLIC_HOST" ]]; then
        echo "warn: $PARAMS_FILE public_host=$current_host but vpngateway.conf XRAY_PUBLIC_HOST=$PUBLIC_HOST" >&2
        echo "      not auto-changing (would break existing client share-URLs); edit by hand if intentional." >&2
    else
        echo "init: $PARAMS_FILE already present, leaving as-is"
    fi
fi

# clients.json — empty array if missing, plus auto-create one "test" client
# so a fresh install is immediately usable.
if [[ ! -f "$CLIENTS_FILE" ]]; then
    echo "[]" > "$CLIENTS_FILE"
    chmod 600 "$CLIENTS_FILE"
    "$SCRIPTS_DIR/vpngw-xray-add-client.py" --name test --no-restart
    echo "init: created $CLIENTS_FILE + default 'test' client"
else
    echo "init: $CLIENTS_FILE already present, leaving as-is"
fi

# Render server.json from current state.
"$SCRIPTS_DIR/vpngw-xray-render-config.sh"
echo "init: done"
