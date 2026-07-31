#!/bin/bash
# Install the small Outline-prefixed Shadowsocks local SOCKS sidecar.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/usr/local/bin/vpngw-outline-ss-local"

if ! command -v go >/dev/null 2>&1; then
    echo "error: go toolchain is required to build vpngw-outline-ss-local" >&2
    exit 78
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Building vpngw-outline-ss-local"
GOCACHE="${GOCACHE:-$tmp/go-build-cache}" \
GOMODCACHE="${GOMODCACHE:-$tmp/go-mod-cache}" \
GOOS=linux GOARCH=amd64 \
    go build -C "$REPO_DIR" -o "$tmp/vpngw-outline-ss-local" ./cmd/vpngw-outline-ss-local

install -m 0755 "$tmp/vpngw-outline-ss-local" "$OUT"
echo "Installed $OUT"
