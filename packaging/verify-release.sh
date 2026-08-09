#!/bin/bash
# Verify checksums and package contents without installation.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-}"
VERSION="${VERSION#v}"
DIST="${2:-$ROOT/dist}"
[[ -n "$VERSION" ]] || VERSION="$(sed -n 's/^API_VERSION = "\([^"]*\)"/\1/p' "$ROOT/api/config.py")"

tarball="$DIST/vpngateway-$VERSION-linux.tar.gz"
deb="$DIST/vpngateway_${VERSION}_all.deb"
rpm="$DIST/vpngateway-$VERSION-1.noarch.rpm"
for path in "$tarball" "$deb" "$rpm" "$DIST/SHA256SUMS"; do
    [[ -f "$path" ]] || { echo "ERROR: missing artifact: $path" >&2; exit 2; }
done

(cd "$DIST" && sha256sum -c SHA256SUMS)
tar_list="$(tar -tzf "$tarball")"
deb_list="$(dpkg-deb --contents "$deb")"
rpm_list="$(rpm -qpl "$rpm")"

grep -q "^vpngateway-$VERSION/install.sh$" <<<"$tar_list"
grep -q "^vpngateway-$VERSION/config/vpngateway.conf.example$" <<<"$tar_list"
grep -q './usr/lib/vpngateway/install.sh' <<<"$deb_list"
grep -q './usr/sbin/vpngateway-install' <<<"$deb_list"
grep -q '/usr/lib/vpngateway/install.sh' <<<"$rpm_list"
grep -q '/usr/sbin/vpngateway-install' <<<"$rpm_list"

[[ "$(dpkg-deb -f "$deb" Package)" == vpngateway ]]
[[ "$(dpkg-deb -f "$deb" Version)" == "$VERSION" ]]
[[ "$(dpkg-deb -f "$deb" Architecture)" == all ]]
[[ "$(rpm -qp --qf '%{NAME}' "$rpm")" == vpngateway ]]
[[ "$(rpm -qp --qf '%{VERSION}' "$rpm")" == "$VERSION" ]]
[[ "$(rpm -qp --qf '%{ARCH}' "$rpm")" == noarch ]]

all_lists="$tar_list
$deb_list
$rpm_list"
if grep -Eiq '(^|/)(AGENTS|MEMORY|CLAUDE|CHANGELOG|PLAN|QUICKSTART)\.md$|(^|/)certs/|\.env$|\.vpngwkey$|\.ovpn$|\.key$' <<<"$all_lists"; then
    echo "ERROR: forbidden internal/runtime file found in release artifact" >&2
    exit 3
fi

echo "Release artifacts verified for v$VERSION"
