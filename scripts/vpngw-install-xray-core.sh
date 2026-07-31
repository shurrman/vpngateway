#!/bin/bash
# Install xray-core runtime binary used by vpngw-xray-client and vpngw-xray.

set -euo pipefail

VERSION="${XRAY_CORE_VERSION:-latest}"
INSTALL_BIN="${XRAY_CORE_BIN:-/usr/local/bin/xray}"
ASSET_DIR="${XRAY_CORE_ASSET_DIR:-/usr/local/share/xray}"
REPO_URL="https://github.com/XTLS/Xray-core"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must be run as root" >&2
    exit 1
fi

case "$(uname -m)" in
    x86_64|amd64)
        ASSET="Xray-linux-64.zip"
        ;;
    aarch64|arm64)
        ASSET="Xray-linux-arm64-v8a.zip"
        ;;
    armv7l)
        ASSET="Xray-linux-arm32-v7a.zip"
        ;;
    *)
        echo "ERROR: unsupported architecture: $(uname -m)" >&2
        exit 2
        ;;
esac

if [[ "$VERSION" == "latest" ]]; then
    EFFECTIVE_URL="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$REPO_URL/releases/latest")"
    VERSION="${EFFECTIVE_URL##*/}"
fi
if [[ "$VERSION" != v* ]]; then
    VERSION="v${VERSION}"
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

BASE_URL="$REPO_URL/releases/download/$VERSION"
ZIP="$TMPDIR/$ASSET"
DGST="$TMPDIR/$ASSET.dgst"
UNPACK="$TMPDIR/xray"

echo "Installing xray-core $VERSION ($ASSET)"
curl -fL --retry 3 --connect-timeout 15 -o "$ZIP" "$BASE_URL/$ASSET"

if curl -fL --retry 3 --connect-timeout 15 -o "$DGST" "$BASE_URL/$ASSET.dgst"; then
    EXPECTED_SHA256="$(awk 'tolower($0) ~ /(sha256|sha2-256)/ {print $NF; exit}' "$DGST" | tr -d '\r')"
    ACTUAL_SHA256="$(sha256sum "$ZIP" | awk '{print $1}')"
    if [[ -z "$EXPECTED_SHA256" ]]; then
        echo "ERROR: SHA256 not found in $ASSET.dgst" >&2
        exit 3
    fi
    if [[ "$EXPECTED_SHA256" != "$ACTUAL_SHA256" ]]; then
        echo "ERROR: checksum mismatch for $ASSET" >&2
        echo "expected: $EXPECTED_SHA256" >&2
        echo "actual:   $ACTUAL_SHA256" >&2
        exit 4
    fi
    echo "Checksum OK"
else
    echo "ERROR: checksum file not available: $BASE_URL/$ASSET.dgst" >&2
    exit 5
fi

mkdir -p "$UNPACK"
if command -v unzip >/dev/null 2>&1; then
    unzip -q "$ZIP" -d "$UNPACK"
elif command -v python3 >/dev/null 2>&1; then
    python3 -m zipfile -e "$ZIP" "$UNPACK"
else
    echo "ERROR: need unzip or python3 to extract $ASSET" >&2
    exit 6
fi

install -d -m 0755 "$(dirname "$INSTALL_BIN")"
install -m 0755 "$UNPACK/xray" "$INSTALL_BIN"
install -d -m 0755 "$ASSET_DIR"
install -m 0644 "$UNPACK/geoip.dat" "$ASSET_DIR/geoip.dat"
install -m 0644 "$UNPACK/geosite.dat" "$ASSET_DIR/geosite.dat"
install -d -m 0755 /var/log/xray

"$INSTALL_BIN" version | sed -n '1,4p'
