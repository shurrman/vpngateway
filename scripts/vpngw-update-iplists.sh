#!/bin/bash
# Download IP ranges from external sources and add them to the vpn_domains ipset.
# Sources are listed in iplist-sources.lst (one URL per line).

set -euo pipefail

SOURCES_FILE="/opt/vpngateway/config/iplist-sources.lst"
IPSET_NAME="vpn_domains"
TMPDIR_BASE="/tmp/vpngw-iplists"

echo "=== vpngw-update-iplists ==="

if [[ ! -f "$SOURCES_FILE" ]]; then
    echo "ERROR: $SOURCES_FILE not found"
    exit 1
fi

# Ensure ipset exists
if ! ipset list "$IPSET_NAME" &>/dev/null; then
    echo "WARNING: ipset $IPSET_NAME does not exist, skipping"
    exit 0
fi

mkdir -p "$TMPDIR_BASE"

added=0
errors=0

while IFS= read -r url; do
    url="${url%%#*}"        # strip comments
    url="${url// /}"        # strip spaces
    [[ -z "$url" ]] && continue

    filename=$(echo "$url" | md5sum | cut -d' ' -f1)
    tmpfile="$TMPDIR_BASE/$filename.txt"

    echo "Downloading: $url"
    if curl -sSf --max-time 30 -o "$tmpfile" "$url"; then
        count=0
        while IFS= read -r cidr; do
            cidr="${cidr// /}"
            [[ -z "$cidr" ]] && continue
            [[ "$cidr" == \#* ]] && continue
            # Validate CIDR format (basic check)
            if [[ "$cidr" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$ ]]; then
                ipset add "$IPSET_NAME" "$cidr" 2>/dev/null || true
                ((count++)) || true
            fi
        done < "$tmpfile"
        echo "  Added $count entries"
        ((added += count)) || true
        rm -f "$tmpfile"
    else
        echo "  ERROR: Failed to download $url"
        ((errors++)) || true
    fi
done < "$SOURCES_FILE"

rmdir "$TMPDIR_BASE" 2>/dev/null || true

echo "=== Done: $added entries added, $errors errors ==="
